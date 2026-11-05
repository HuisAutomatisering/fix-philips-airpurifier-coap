"""Tests for the robustness, pacing and privacy measures."""

import asyncio
from collections.abc import AsyncGenerator
import logging
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.philips_airpurifier_local import ListingView, coordinator as coord_module
from custom_components.philips_airpurifier_local.const import DOMAIN
from custom_components.philips_airpurifier_local.coordinator import Coordinator
from custom_components.philips_airpurifier_local.helpers import (
    REDACTED,
    clamp_max_age,
    coap_host,
    redact_status,
)
from custom_components.philips_airpurifier_local.philips import PhilipsGenericControlBase
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError

from .conftest import DOMAIN_MODULE, make_client
from .const import DEVICE_ID, HOST, STATUS_AC2889

# --- helpers ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, 15), (-5, 15), (60, 60), (99999, 600), (None, 60), ("abc", 60), ("120", 120)],
)
def test_clamp_max_age(value: Any, expected: int) -> None:
    """The device-announced Max-Age is kept within sane bounds."""
    assert clamp_max_age(value) == expected


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("192.168.1.50", "192.168.1.50"),
        ("fe80::1", "[fe80::1]"),
        ("purifier.local", "purifier.local"),
    ],
)
def test_coap_host(host: str, expected: str) -> None:
    """IPv6 addresses are wrapped in brackets for the coap:// URI."""
    assert coap_host(host) == expected


def test_redact_status() -> None:
    """Identifiers and names are removed from logged status data."""
    redacted = redact_status(STATUS_AC2889)
    assert redacted["DeviceId"] == REDACTED
    assert redacted["ProductId"] == REDACTED
    assert redacted["name"] == REDACTED
    assert redacted["pm25"] == STATUS_AC2889["pm25"]
    assert redact_status("not a dict") == "not a dict"


def test_device_ids_not_recorded() -> None:
    """Device and product id attributes are excluded from the recorder."""
    assert {"device_id", "product_id"} <= PhilipsGenericControlBase._unrecorded_attributes


def test_icon_list_requires_auth() -> None:
    """The icon list endpoint is only available to logged-in users."""
    assert ListingView.requires_auth is True


# --- coordinator: watchdog and backoff --------------------------------------


async def test_first_refresh_clamps_max_age(hass: HomeAssistant) -> None:
    """A Max-Age of 0 must not turn the watchdog into a reconnect loop."""
    client = make_client()
    client.get_status = AsyncMock(return_value=(dict(STATUS_AC2889), 0))
    coordinator = Coordinator(hass, client, HOST, None)

    await coordinator.async_first_refresh()

    assert coordinator._timeout == 15
    assert coordinator._timer_disconnected._timeout == 45
    await coordinator.shutdown()


async def test_reconnect_backoff_and_reset(hass: HomeAssistant) -> None:
    """Failed reconnects back off up to the maximum; fresh data resets the interval."""
    coordinator = Coordinator(hass, make_client(), HOST, dict(STATUS_AC2889))
    coordinator._timeout = 15  # watchdog 45 s

    delays = []
    with patch(
        f"{DOMAIN_MODULE}.coordinator.CoAPClient.create",
        new=AsyncMock(side_effect=OSError("unreachable")),
    ):
        for _ in range(4):
            await coordinator.reconnect()
            await coordinator._reconnect_task
            delays.append(coordinator._timer_disconnected._timeout)

    assert delays == [90, 180, 300, 300]

    # the device answers again: back to the normal watchdog interval
    client = make_client()

    async def _one_status() -> AsyncGenerator[Any]:
        yield ["not", "a", "dict"]  # ignored
        yield dict(STATUS_AC2889)

    client.observe_status = _one_status
    coordinator.client = client
    await coordinator._async_observe_status()

    assert coordinator._failures == 0
    assert coordinator._timer_disconnected._timeout == 45
    await coordinator.shutdown()


# --- coordinator: command pacing --------------------------------------------


async def test_commands_one_at_a_time_and_paced(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Commands never overlap and keep a minimum pause between them."""
    monkeypatch.setattr(coord_module, "COMMAND_MIN_INTERVAL", 0.05)
    client = make_client()
    active = 0
    max_active = 0
    starts: list[float] = []

    async def _send(data: dict[str, Any]) -> bool:
        nonlocal active, max_active
        starts.append(time.monotonic())
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return True

    client.set_control_values = _send
    coordinator = Coordinator(hass, client, HOST, dict(STATUS_AC2889))

    results = await asyncio.gather(
        *(coordinator.async_set_control_value("pwr", str(i % 2)) for i in range(3))
    )

    assert results == [True, True, True]
    assert max_active == 1
    assert all(b - a >= 0.04 for a, b in zip(starts, starts[1:], strict=False))
    await coordinator.shutdown()


async def test_command_timeout(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> None:
    """A device that does not answer gives a clear error instead of hanging."""
    monkeypatch.setattr(coord_module, "COMMAND_TIMEOUT", 0.05)
    client = make_client()

    async def _hang(data: dict[str, Any]) -> bool:
        await asyncio.Event().wait()
        return True

    client.set_control_values = _hang
    coordinator = Coordinator(hass, client, HOST, dict(STATUS_AC2889))

    with pytest.raises(HomeAssistantError):
        await coordinator.async_set_control_value("pwr", "1")
    await coordinator.shutdown()


async def test_command_error_and_unconfirmed(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Transport errors become HomeAssistantError; unconfirmed commands are logged."""
    client = make_client()
    coordinator = Coordinator(hass, client, HOST, dict(STATUS_AC2889))

    client.set_control_values = AsyncMock(side_effect=OSError("boom"))
    with pytest.raises(HomeAssistantError):
        await coordinator.async_set_control_value("pwr", "1")

    client.set_control_values = AsyncMock(return_value=False)
    assert await coordinator.async_set_control_value("pwr", "1") is False
    assert "did not confirm" in caplog.text
    await coordinator.shutdown()


# --- privacy -----------------------------------------------------------------


@pytest.mark.usefixtures("mock_setup_entry")
async def test_debug_log_has_no_device_id(
    hass: HomeAssistant, mock_flow_client: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """The config flow does not write the device id to the debug log."""
    caplog.set_level(logging.DEBUG, logger=DOMAIN_MODULE)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data={CONF_HOST: HOST}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    own_records = [r for r in caplog.records if r.name.startswith(DOMAIN_MODULE)]
    assert own_records
    assert not any(DEVICE_ID in record.getMessage() for record in own_records)
