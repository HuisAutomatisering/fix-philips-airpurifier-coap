"""Module containing the Coordinator class to manage data requests from the Philips API."""

import asyncio
from asyncio.tasks import Task
from collections.abc import Callable
import logging
import time
from typing import Any

from aioairctrl import CoAPClient

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError

from .helpers import DEFAULT_MAX_AGE, clamp_max_age
from .timer import Timer

_LOGGER = logging.getLogger(__name__)

# missed status pushes before the watchdog reconnects
MISSED_PACKAGE_COUNT = 3
# seconds a single reconnect attempt may take
RECONNECT_TIMEOUT = 30
# upper limit in seconds for the growing pause between failed reconnects
BACKOFF_MAX = 300
# seconds a command (including the library's own retries) may take
COMMAND_TIMEOUT = 15
# minimum pause in seconds between two commands, so the device is never flooded
COMMAND_MIN_INTERVAL = 0.3


class Coordinator:
    """Class to coordinate the data requests from the Philips API."""

    def __init__(
        self, hass: HomeAssistant, client: CoAPClient, host: str, status: dict[str, Any] | None
    ) -> None:
        """Initialize the Coordinator.

        :param hass: HomeAssistant instance.
        :param client: CoAPClient instance.
        :param host: Host address of the device, as used in a coap:// URI.
        :param status: Initial status of the device.
        """

        self.hass = hass
        self.client = client
        self.host = host
        self.status = status

        self._listeners: list[CALLBACK_TYPE] = []
        self._task: Task | None = None

        self._reconnect_task: Task | None = None
        self._timeout: int = DEFAULT_MAX_AGE
        self._failures = 0

        self._command_lock = asyncio.Lock()
        self._last_command = 0.0

        self._timer_disconnected = Timer(
            timeout=self._watchdog,
            callback=self.reconnect,
            autostart=True,
        )
        self._timer_disconnected.setAutoRestart(True)

    @property
    def _watchdog(self) -> int:
        """Seconds without a status push before a reconnect is attempted."""
        return self._timeout * MISSED_PACKAGE_COUNT

    def _retry_delay(self) -> int:
        """Seconds until the next reconnect attempt, growing with each failure."""
        return min(self._watchdog * 2**self._failures, max(self._watchdog, BACKOFF_MAX))

    async def shutdown(self):
        """Shutdown the API connection."""

        if self._reconnect_task is not None:
            self._reconnect_task.cancel()

        if self._timer_disconnected is not None:
            self._timer_disconnected.cancel()

        if self._task is not None:
            self._task.cancel()
            self._task = None

        if self.client is not None:
            await self.client.shutdown()

    async def reconnect(self):
        """Reconnect after the watchdog expired (called by the timer)."""

        # every expiry without data counts as a failure: back off before the next attempt
        self._failures = min(self._failures + 1, 10)
        self._timer_disconnected.setTimeout(self._retry_delay())

        try:
            if self._reconnect_task is not None:
                self._reconnect_task.cancel()
                self._reconnect_task = None

            self._reconnect_task = asyncio.create_task(self._reconnect())

        except Exception:
            _LOGGER.exception("Exception on starting reconnect!")

    async def _reconnect(self):
        """Reconnect to the API connection."""

        try:
            try:
                await self.client.shutdown()
            # the old client may already be broken; logged, not raised
            except Exception as ex:  # noqa: BLE001
                _LOGGER.debug("Ignoring error while closing old client for %s: %s", self.host, ex)
            async with asyncio.timeout(RECONNECT_TIMEOUT):
                self.client = await CoAPClient.create(self.host)
            _LOGGER.debug("Reconnected to %s", self.host)
            self._start_observing()

        except asyncio.CancelledError:
            # A newer reconnect attempt replaced this one; nothing else to do.
            _LOGGER.debug("Reconnect attempt for %s was cancelled", self.host)

        except TimeoutError:
            _LOGGER.warning(
                "Reconnect to %s timed out after %ss, next attempt in %ss",
                self.host,
                RECONNECT_TIMEOUT,
                self._retry_delay(),
            )

        except Exception:
            _LOGGER.exception(
                "Reconnect to %s failed, next attempt in %ss", self.host, self._retry_delay()
            )

    async def async_first_refresh(self) -> None:
        """Refresh the data for the first time."""

        try:
            status, max_age = await self.client.get_status()
            if not isinstance(status, dict):
                raise TypeError("unexpected status format")
            self.status = status
            self._timeout = clamp_max_age(max_age)
            if self._timer_disconnected is not None:
                self._timer_disconnected.setTimeout(self._watchdog)
            _LOGGER.debug("finished first refresh for host %s", self.host)

        except Exception as ex:
            _LOGGER.exception("Config not ready, first refresh failed for host %s", self.host)
            raise ConfigEntryNotReady from ex

    async def async_set_control_values(self, data: dict[str, Any]) -> bool:
        """Send a command to the device: one at a time, paced and with a timeout."""

        async with self._command_lock:
            wait = COMMAND_MIN_INTERVAL - (time.monotonic() - self._last_command)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                async with asyncio.timeout(COMMAND_TIMEOUT):
                    result = await self.client.set_control_values(data=data)
            except TimeoutError as ex:
                raise HomeAssistantError(
                    f"Philips device at {self.host} did not answer within {COMMAND_TIMEOUT}s"
                ) from ex
            except Exception as ex:
                raise HomeAssistantError(
                    f"Sending command to Philips device at {self.host} failed: {ex}"
                ) from ex
            finally:
                self._last_command = time.monotonic()

        if not result:
            _LOGGER.warning("Device %s did not confirm command for %s", self.host, list(data))
        return result

    async def async_set_control_value(self, key: str, value: Any) -> bool:
        """Send a single value to the device."""
        return await self.async_set_control_values({key: value})

    @callback
    def async_add_listener(self, update_callback: CALLBACK_TYPE) -> Callable[[], None]:
        """Listen for data updates."""

        start_observing = not self._listeners
        self._listeners.append(update_callback)

        if start_observing:
            self._start_observing()

        @callback
        def remove_listener() -> None:
            """Remove update listener."""
            self.async_remove_listener(update_callback)

        return remove_listener

    @callback
    def async_remove_listener(self, update_callback) -> None:
        """Remove data update."""

        self._listeners.remove(update_callback)

        if not self._listeners and self._task:
            self._task.cancel()
            self._task = None

    async def _async_observe_status(self) -> None:
        """Observe the status of the device."""

        async for status in self.client.observe_status():
            if not isinstance(status, dict):
                _LOGGER.debug("Ignoring unexpected status from %s: %s", self.host, type(status))
                continue
            self.status = status
            if self._failures:
                # data flows again: back to the normal watchdog interval
                self._failures = 0
                self._timer_disconnected.setTimeout(self._watchdog)
            else:
                self._timer_disconnected.reset()
            for update_callback in self._listeners:
                update_callback()

    def _start_observing(self) -> None:
        """Schedule state observation."""

        if self._task:
            self._task.cancel()
            self._task = None

        self._task = asyncio.create_task(self._async_observe_status())
        self._timer_disconnected.reset()
