"""Tests for quiet discovery of known devices, connection pacing and log levels."""

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.philips_airpurifier_local.config_flow import async_fetch_status
from custom_components.philips_airpurifier_local.const import DOMAIN
from custom_components.philips_airpurifier_local.coordinator import Coordinator
from homeassistant.config_entries import SOURCE_DHCP, SOURCE_IGNORE, SOURCE_USER
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .conftest import DOMAIN_MODULE, make_client
from .const import DEVICE_ID, ENTRY_DATA, HOST, NEW_HOST, STATUS_AC2889

OLD_HOST = "192.168.1.10"
MAC = "68:79:c4:aa:bb:cc"
DHCP_INFO = DhcpServiceInfo(ip=HOST, hostname="mxchip-abc", macaddress="6879c4aabbcc")

pytestmark = pytest.mark.usefixtures("mock_setup_entry")


def _add_entry(
    hass: HomeAssistant,
    host: str = HOST,
    options: dict[str, Any] | None = None,
    source: str = SOURCE_USER,
) -> MockConfigEntry:
    """Add a config entry for the test device."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DEVICE_ID,
        title="AC2889 Bedroom",
        data={**ENTRY_DATA, CONF_HOST: host},
        options=options or {},
        source=source,
    )
    entry.add_to_hass(hass)
    return entry


def _register_device(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Register the device with its MAC address, as the integration does."""
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, MAC)},
        identifiers={(DOMAIN, DEVICE_ID)},
    )


def _own_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """Return warnings and errors logged by this integration."""
    return [
        record
        for record in caplog.records
        if record.name.startswith(DOMAIN_MODULE) and record.levelno >= logging.WARNING
    ]


# --- DHCP discovery of known devices -----------------------------------------


async def test_dhcp_known_host_does_not_connect(
    hass: HomeAssistant, mock_flow_client: AsyncMock
) -> None:
    """A configured device found again by DHCP is recognised without connecting."""
    _add_entry(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_INFO
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    mock_flow_client.assert_not_awaited()


async def test_dhcp_known_mac_updates_host(
    hass: HomeAssistant, mock_flow_client: AsyncMock
) -> None:
    """A configured device with a new IP address is updated without connecting."""
    entry = _add_entry(hass, host=OLD_HOST)
    _register_device(hass, entry)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_INFO
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == HOST
    mock_flow_client.assert_not_awaited()


async def test_dhcp_known_mac_updates_options_host(
    hass: HomeAssistant, mock_flow_client: AsyncMock
) -> None:
    """A host set through the options flow is the one that gets updated."""
    entry = _add_entry(hass, host=OLD_HOST, options={CONF_HOST: NEW_HOST})
    _register_device(hass, entry)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_INFO
    )

    assert result["type"] is FlowResultType.ABORT
    assert entry.options[CONF_HOST] == HOST
    mock_flow_client.assert_not_awaited()


async def test_dhcp_ignored_device_stays_ignored(
    hass: HomeAssistant, mock_flow_client: AsyncMock
) -> None:
    """A device the user ignored is not offered again."""
    _add_entry(hass, host=OLD_HOST, source=SOURCE_IGNORE)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_INFO
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# --- manual setup of known devices -------------------------------------------


async def test_user_flow_same_host_does_not_connect(
    hass: HomeAssistant, mock_flow_client: AsyncMock
) -> None:
    """Adding a device again at its configured address aborts without connecting."""
    _add_entry(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data={CONF_HOST: HOST}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    mock_flow_client.assert_not_awaited()


async def test_user_flow_updates_options_host(
    hass: HomeAssistant, mock_flow_client: AsyncMock
) -> None:
    """Adding a known device at a new address updates the host in the options."""
    entry = _add_entry(hass, host=OLD_HOST, options={CONF_HOST: NEW_HOST})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data={CONF_HOST: HOST}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.options[CONF_HOST] == HOST


# --- one connection at a time --------------------------------------------------


async def test_setup_connections_are_serialized(
    hass: HomeAssistant, mock_flow_client: AsyncMock
) -> None:
    """Two setup connections to the same device never run at the same time."""
    client = mock_flow_client.client
    active = 0
    max_active = 0

    async def _create(host: str) -> Any:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return client

    mock_flow_client.side_effect = _create

    statuses = await asyncio.gather(async_fetch_status(hass, HOST), async_fetch_status(hass, HOST))

    assert max_active == 1
    assert all(status["DeviceId"] == DEVICE_ID for status in statuses)


# --- log levels ----------------------------------------------------------------


async def test_setup_timeout_not_logged_as_warning(
    hass: HomeAssistant, mock_flow_client: AsyncMock, caplog: pytest.LogCaptureFixture
) -> None:
    """A timeout during setup is shown in the form, not as a warning in the log."""
    caplog.set_level(logging.DEBUG, logger=DOMAIN_MODULE)
    mock_flow_client.side_effect = TimeoutError

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data={CONF_HOST: HOST}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_HOST: "timeout"}
    assert not _own_warnings(caplog)


async def test_lost_connection_logged_once(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """A lost connection is a single warning; repeats are debug; recovery is info."""
    caplog.set_level(logging.DEBUG, logger=DOMAIN_MODULE)
    coordinator = Coordinator(hass, make_client(), HOST, dict(STATUS_AC2889))

    with patch(
        f"{DOMAIN_MODULE}.coordinator.CoAPClient.create",
        new=AsyncMock(side_effect=OSError("unreachable")),
    ):
        for _ in range(3):
            await coordinator.reconnect()
            await coordinator._reconnect_task

    warnings = _own_warnings(caplog)
    assert len(warnings) == 1
    assert "Lost connection" in warnings[0].getMessage()

    client = make_client()

    async def _one_status() -> Any:
        yield dict(STATUS_AC2889)

    client.observe_status = _one_status
    coordinator.client = client
    caplog.clear()
    await coordinator._async_observe_status()

    assert any(
        record.levelno == logging.INFO and "restored" in record.getMessage()
        for record in caplog.records
    )
    await coordinator.shutdown()
