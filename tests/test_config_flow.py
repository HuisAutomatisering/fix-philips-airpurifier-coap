"""Tests for the Philips AirPurifier config flow."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.philips_airpurifier_coap.config_flow import host_valid
from custom_components.philips_airpurifier_coap.const import (
    CONF_DEVICE_ID,
    CONF_MODEL,
    CONF_STATUS,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_DHCP, SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .const import (
    DEVICE_ID,
    ENTRY_DATA,
    HOST,
    NEW_HOST,
    OTHER_DEVICE_ID,
    STATUS_AC2889,
    STATUS_EXACT,
    STATUS_LONG,
    STATUS_NO_DEVICE_ID,
    STATUS_UNSUPPORTED,
)

pytestmark = pytest.mark.usefixtures("mock_setup_entry")

DHCP_INFO = DhcpServiceInfo(ip=HOST, hostname="mxchip-abc", macaddress="6879c4aabbcc")


def _set_status(mock_flow_client: AsyncMock, status: dict[str, Any]) -> None:
    """Let the mocked device answer with the given status."""
    mock_flow_client.client.get_status = AsyncMock(return_value=(dict(status), 60))


def _add_entry(hass: HomeAssistant, host: str = HOST) -> MockConfigEntry:
    """Add an existing config entry for the test device."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DEVICE_ID,
        title="AC2889 Bedroom",
        data={**ENTRY_DATA, CONF_HOST: host},
    )
    entry.add_to_hass(hass)
    return entry


# --- helpers ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "valid"),
    [
        ("192.168.1.50", True),
        ("fe80::1", True),
        ("purifier.local", True),
        ("my-purifier", True),
        ("", False),
        ("bad host", False),
        ("bad..host", False),
        ("under_score", False),
    ],
)
def test_host_valid(host: str, valid: bool) -> None:
    """Test hostname and IP address validation."""
    assert host_valid(host) is valid


# --- user flow -------------------------------------------------------------


async def test_user_flow_success(hass: HomeAssistant, mock_flow_client: AsyncMock) -> None:
    """Test a successful manual setup."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: f" {HOST} "}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "AC2889/10 Bedroom"
    assert result["data"] == {
        CONF_HOST: HOST,
        CONF_MODEL: "AC2889",
        CONF_NAME: "Bedroom",
        CONF_DEVICE_ID: DEVICE_ID,
        CONF_STATUS: STATUS_AC2889,
    }
    assert result["result"].unique_id == DEVICE_ID
    mock_flow_client.client.shutdown.assert_awaited_once()


@pytest.mark.parametrize(
    ("status", "model"),
    [
        (STATUS_EXACT, "AC0850/81"),
        (STATUS_LONG, "AC0850/11 AWS_Philips_AIR"),
        (STATUS_AC2889, "AC2889"),
    ],
)
async def test_user_flow_model_detection(
    hass: HomeAssistant,
    mock_flow_client: AsyncMock,
    status: dict[str, Any],
    model: str,
) -> None:
    """Test exact, model+firmware and model family detection."""
    _set_status(mock_flow_client, status)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data={CONF_HOST: HOST}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_MODEL] == model


async def test_user_flow_invalid_host(hass: HomeAssistant, mock_flow_client: AsyncMock) -> None:
    """Test an invalid host shows an error and the flow can recover."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data={CONF_HOST: "bad host"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_HOST: "host"}
    mock_flow_client.assert_not_awaited()

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (TimeoutError, "timeout"),
        (OSError("unreachable"), "connect"),
    ],
)
async def test_user_flow_connection_errors(
    hass: HomeAssistant,
    mock_flow_client: AsyncMock,
    side_effect: Exception,
    error: str,
) -> None:
    """Test connection problems show an error and the flow can recover."""
    client = mock_flow_client.client
    mock_flow_client.side_effect = side_effect

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data={CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_HOST: error}

    mock_flow_client.side_effect = None
    mock_flow_client.return_value = client
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_status_error_closes_client(
    hass: HomeAssistant, mock_flow_client: AsyncMock
) -> None:
    """Test the client is closed when reading the status fails."""
    client = mock_flow_client.client
    client.get_status = AsyncMock(side_effect=OSError("boom"))
    client.shutdown = AsyncMock(side_effect=OSError("already closed"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data={CONF_HOST: HOST}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_HOST: "connect"}
    client.shutdown.assert_awaited_once()


@pytest.mark.parametrize("status", [STATUS_UNSUPPORTED, STATUS_NO_DEVICE_ID])
async def test_user_flow_unsupported(
    hass: HomeAssistant, mock_flow_client: AsyncMock, status: dict[str, Any]
) -> None:
    """Test an unsupported model or unexpected status aborts the flow."""
    _set_status(mock_flow_client, status)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data={CONF_HOST: HOST}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "model_unsupported"


async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_flow_client: AsyncMock
) -> None:
    """Test the same device cannot be added twice and its host gets updated."""
    entry = _add_entry(hass, host="192.168.1.10")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data={CONF_HOST: HOST}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == HOST


# --- dhcp flow -------------------------------------------------------------


async def test_dhcp_flow_success(hass: HomeAssistant, mock_flow_client: AsyncMock) -> None:
    """Test a device found by DHCP discovery can be confirmed."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_INFO
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"] == {"model": "AC2889", "name": "Bedroom"}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "AC2889 Bedroom"
    assert result["data"] == {
        CONF_HOST: HOST,
        CONF_MODEL: "AC2889",
        CONF_NAME: "Bedroom",
        CONF_DEVICE_ID: DEVICE_ID,
        CONF_STATUS: STATUS_AC2889,
    }
    assert result["result"].unique_id == DEVICE_ID


@pytest.mark.parametrize(
    ("side_effect", "reason"),
    [
        (TimeoutError, "timeout"),
        (OSError("unreachable"), "cannot_connect"),
    ],
)
async def test_dhcp_flow_connection_errors(
    hass: HomeAssistant,
    mock_flow_client: AsyncMock,
    side_effect: Exception,
    reason: str,
) -> None:
    """Test connection problems abort a DHCP discovery."""
    mock_flow_client.side_effect = side_effect

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_INFO
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason


@pytest.mark.parametrize("status", [STATUS_UNSUPPORTED, STATUS_NO_DEVICE_ID])
async def test_dhcp_flow_unsupported(
    hass: HomeAssistant, mock_flow_client: AsyncMock, status: dict[str, Any]
) -> None:
    """Test an unsupported device aborts a DHCP discovery."""
    _set_status(mock_flow_client, status)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_INFO
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "model_unsupported"


async def test_dhcp_flow_updates_host(hass: HomeAssistant, mock_flow_client: AsyncMock) -> None:
    """Test DHCP discovery of a known device updates its host."""
    entry = _add_entry(hass, host="192.168.1.10")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_INFO
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == HOST


# --- options flow ----------------------------------------------------------


async def test_options_flow_success(hass: HomeAssistant, mock_flow_client: AsyncMock) -> None:
    """Test changing the host of the same device."""
    entry = _add_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_HOST: NEW_HOST}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_HOST: NEW_HOST}


@pytest.mark.parametrize(
    ("host", "side_effect", "status", "error"),
    [
        ("bad host", None, STATUS_AC2889, "host"),
        (NEW_HOST, TimeoutError, STATUS_AC2889, "timeout"),
        (NEW_HOST, OSError("unreachable"), STATUS_AC2889, "connect"),
        (NEW_HOST, None, {**STATUS_AC2889, "DeviceId": OTHER_DEVICE_ID}, "different_device"),
    ],
)
async def test_options_flow_errors(
    hass: HomeAssistant,
    mock_flow_client: AsyncMock,
    host: str,
    side_effect: Exception | None,
    status: dict[str, Any],
    error: str,
) -> None:
    """Test the options flow reports errors and can recover."""
    entry = _add_entry(hass)
    client: MagicMock = mock_flow_client.client
    _set_status(mock_flow_client, status)
    mock_flow_client.side_effect = side_effect

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_HOST: host})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_HOST: error}

    mock_flow_client.side_effect = None
    mock_flow_client.return_value = client
    _set_status(mock_flow_client, STATUS_AC2889)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_HOST: NEW_HOST}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_HOST: NEW_HOST}
