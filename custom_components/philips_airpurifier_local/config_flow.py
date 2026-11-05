"""Config flow for the Philips AirPurifier integration."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
from typing import Any

from aioairctrl import CoAPClient
import voluptuous as vol

from homeassistant import config_entries, data_entry_flow, exceptions
from homeassistant.config_entries import ConfigEntry, ConfigEntryState, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .const import CONF_DEVICE_ID, CONF_MODEL, CONF_STATUS, DOMAIN, PhilipsApi
from .helpers import MAX_HOST_LENGTH, coap_host, extract_model, extract_name, redact_status
from .philips import model_to_class

_LOGGER = logging.getLogger(__name__)

# seconds to wait for the CoAP handshake and for the first status message
CONNECT_TIMEOUT = 30
# hass.data key for the per-host connection locks of the config flows
CONNECT_LOCKS = f"{DOMAIN}_connect_locks"


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate that the device could not be reached."""


def host_valid(host: str) -> bool:
    """Return True if hostname or IP address is valid."""
    if not host or len(host) > MAX_HOST_LENGTH:
        return False
    try:
        if ipaddress.ip_address(host).version in [4, 6]:
            return True
    except ValueError:
        pass
    disallowed = re.compile(r"[^a-zA-Z\d\-]")
    return all(x and not disallowed.search(x) for x in host.split("."))


def _connect_lock(hass: HomeAssistant, host: str) -> asyncio.Lock:
    """Return the lock that allows only one setup connection per device at a time."""
    locks: dict[str, asyncio.Lock] = hass.data.setdefault(CONNECT_LOCKS, {})
    return locks.setdefault(host, asyncio.Lock())


async def async_fetch_status(hass: HomeAssistant, host: str) -> dict[str, Any]:
    """Connect to the device and return its current status.

    Only one connection per device at a time: Philips devices get confused by
    parallel sessions (for example DHCP discovery and a manual setup).
    Problems are logged at debug level only, the user sees them in the form.

    Raises TimeoutError when the device does not answer in time and
    CannotConnect for any other connection problem.
    """
    async with _connect_lock(hass, host):
        client: CoAPClient | None = None
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT):
                client = await CoAPClient.create(coap_host(host))
                _LOGGER.debug("got a valid client for host %s", host)

            async with asyncio.timeout(CONNECT_TIMEOUT):
                status, _ = await client.get_status()
                _LOGGER.debug("got status for host %s: %s", host, redact_status(status))

        except TimeoutError:
            _LOGGER.debug("Timeout, host %s doesn't answer (yet)", host)
            raise
        except Exception as ex:  # aioairctrl/aiocoap raise many different error types
            _LOGGER.debug("Failed to connect to host %s: %s", host, ex)
            raise CannotConnect(str(ex)) from ex
        finally:
            if client is not None:
                try:
                    await client.shutdown()
                # closing a half-open client must not hide the real result; logged, not raised
                except Exception as ex:  # noqa: BLE001
                    _LOGGER.debug("Error while closing client for host %s: %s", host, ex)

    if not isinstance(status, dict):
        _LOGGER.debug("Unexpected status format from host %s", host)
        raise CannotConnect("unexpected status format")
    return status


def resolve_model(status: dict[str, Any]) -> str | None:
    """Return the supported model key for a device status, or None if unsupported."""
    model = extract_model(status)
    wifi_version = str(status.get(PhilipsApi.WIFI_VERSION) or "")
    model_long = f"{model} {wifi_version.split('@')[0]}"
    model_family = model[:6]

    for candidate in (model, model_long, model_family):
        if candidate and candidate in model_to_class:
            _LOGGER.debug("Model %s supported", candidate)
            return candidate

    _LOGGER.warning("Model %s of family %s not supported", model, model_family)
    return None


class PhilipsAirPurifierConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for Philips AirPurifier."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler()

    def __init__(self) -> None:
        """Initialize."""
        self._host: str | None = None
        self._model: str | None = None
        self._name: str | None = None
        self._device_id: str | None = None
        self._status: dict[str, Any] | None = None

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        """Handle a device found by DHCP discovery."""
        _LOGGER.debug("async_step_dhcp: device found at %s", discovery_info.ip)

        host = discovery_info.ip

        # A configured device is recognised without connecting to it: DHCP renewals
        # would otherwise open a second session next to the running integration.
        self._async_abort_entries_match({CONF_HOST: host})
        mac = dr.format_mac(discovery_info.macaddress)
        device = dr.async_get(self.hass).async_get_device(
            connections={(dr.CONNECTION_NETWORK_MAC, mac)}
        )
        if device is not None:
            for entry_id in device.config_entries:
                entry = self.hass.config_entries.async_get_entry(entry_id)
                if entry is not None and entry.domain == DOMAIN:
                    self._async_update_host(entry, host)
                    return self.async_abort(reason="already_configured")

        try:
            status = await async_fetch_status(self.hass, host)
        except TimeoutError:
            return self.async_abort(reason="timeout")
        except CannotConnect:
            return self.async_abort(reason="cannot_connect")

        device_id = status.get(PhilipsApi.DEVICE_ID)
        if not device_id or not isinstance(device_id, str):
            return self.async_abort(reason="model_unsupported")

        # use the device ID as unique_id, update the host if we know the device already
        await self.async_set_unique_id(device_id)
        self._abort_if_known_device(host)

        model = resolve_model(status)
        if model is None:
            return self.async_abort(reason="model_unsupported")

        self._host = host
        self._model = model
        self._name = extract_name(status)
        self._device_id = device_id
        self._status = status

        self.context["title_placeholders"] = {CONF_NAME: f"{self._model} {self._name}"}

        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the dhcp discovered device."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"{self._model} {self._name}",
                data={
                    CONF_HOST: self._host,
                    CONF_MODEL: self._model,
                    CONF_NAME: self._name,
                    CONF_DEVICE_ID: self._device_id,
                    CONF_STATUS: self._status,
                },
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"model": str(self._model), "name": str(self._name)},
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle a device added manually by the user."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()

            if not host_valid(host):
                errors[CONF_HOST] = "host"
            else:
                # already configured at this address: no need to disturb the device
                self._async_abort_entries_match({CONF_HOST: host})
                try:
                    status = await async_fetch_status(self.hass, host)
                except TimeoutError:
                    errors[CONF_HOST] = "timeout"
                except CannotConnect:
                    errors[CONF_HOST] = "connect"
                else:
                    return await self._async_create_from_status(host, status)

        default_host = user_input.get(CONF_HOST, "") if user_input else ""
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST, default=default_host): cv.string}),
            errors=errors,
        )

    async def _async_create_from_status(
        self, host: str, status: dict[str, Any]
    ) -> ConfigFlowResult:
        """Create the config entry for a device that answered with its status."""
        device_id = status.get(PhilipsApi.DEVICE_ID)
        if not device_id or not isinstance(device_id, str):
            return self.async_abort(reason="model_unsupported")

        await self.async_set_unique_id(device_id)
        self._abort_if_known_device(host)

        model = resolve_model(status)
        if model is None:
            return self.async_abort(reason="model_unsupported")

        name = extract_name(status)
        return self.async_create_entry(
            title=f"{extract_model(status)} {name}",
            data={
                CONF_HOST: host,
                CONF_MODEL: model,
                CONF_NAME: name,
                CONF_DEVICE_ID: device_id,
                CONF_STATUS: status,
            },
        )

    def _abort_if_known_device(self, host: str) -> None:
        """Abort if the device (unique id) is configured already, storing its new host.

        Like _abort_if_unique_id_configured, but also updates a host that was
        changed through the options flow (stored in the entry options).
        """
        entry = self.hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, self.unique_id)
        if entry is None:
            return
        if entry.source == config_entries.SOURCE_IGNORE:
            if self.source == config_entries.SOURCE_USER:
                return  # the user may still set up a device that was ignored earlier
            raise data_entry_flow.AbortFlow("already_configured")
        self._async_update_host(entry, host)
        raise data_entry_flow.AbortFlow("already_configured")

    @callback
    def _async_update_host(self, entry: ConfigEntry, host: str) -> None:
        """Store a new host for a configured device and reload it when needed."""
        if entry.options.get(CONF_HOST, entry.data.get(CONF_HOST)) == host:
            return
        _LOGGER.debug("Updating host of configured device to %s", host)
        if CONF_HOST in entry.options:
            # an options change reloads a loaded entry through its update listener
            self.hass.config_entries.async_update_entry(
                entry, options={**entry.options, CONF_HOST: host}
            )
            return
        self.hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_HOST: host})
        if entry.state in (ConfigEntryState.LOADED, ConfigEntryState.SETUP_RETRY):
            self.hass.config_entries.async_schedule_reload(entry.entry_id)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Philips AirPurifier."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle options flow to change the device host address."""
        errors: dict[str, str] = {}
        current_host = self.config_entry.options.get(CONF_HOST, self.config_entry.data[CONF_HOST])

        if user_input is not None:
            new_host = user_input[CONF_HOST].strip()
            if not host_valid(new_host):
                errors[CONF_HOST] = "host"
            else:
                try:
                    status = await async_fetch_status(self.hass, new_host)
                except TimeoutError:
                    errors[CONF_HOST] = "timeout"
                except CannotConnect:
                    errors[CONF_HOST] = "connect"
                else:
                    expected = self.config_entry.data[CONF_DEVICE_ID]
                    device_id = status.get(PhilipsApi.DEVICE_ID)
                    if device_id != expected:
                        _LOGGER.debug("Device at %s is not the configured device", new_host)
                        errors[CONF_HOST] = "different_device"
                    else:
                        return self.async_create_entry(title="", data={CONF_HOST: new_host})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Required(CONF_HOST, default=current_host): cv.string}),
            errors=errors,
        )
