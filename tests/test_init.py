"""Tests for setting up and unloading the Philips AirPurifier integration."""

from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.philips_airpurifier_coap.const import CONF_STATUS, DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DEVICE_ID, ENTRY_DATA, STATUS_AC2889


def _add_entry(hass: HomeAssistant, data: dict | None = None) -> MockConfigEntry:
    """Add a config entry for the test device."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DEVICE_ID,
        title="AC2889 Bedroom",
        data=data if data is not None else ENTRY_DATA,
    )
    entry.add_to_hass(hass)
    return entry


async def test_setup_and_unload(hass: HomeAssistant, mock_integration_client: AsyncMock) -> None:
    """Test the integration sets up its entities and unloads cleanly."""
    entry = _add_entry(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.device_information.device_id == DEVICE_ID
    assert hass.states.async_entity_ids("fan")

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, DEVICE_ID)})
    assert device is not None
    assert device.model == "AC2889/10"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    mock_integration_client.client.shutdown.assert_awaited()


async def test_setup_retry_when_unreachable(
    hass: HomeAssistant, mock_integration_client: AsyncMock
) -> None:
    """Test setup is retried when the device cannot be reached."""
    mock_integration_client.side_effect = OSError("unreachable")
    entry = _add_entry(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_fetches_missing_status(
    hass: HomeAssistant, mock_integration_client: AsyncMock
) -> None:
    """Test an old entry without stored status fetches and stores it."""
    data = {key: value for key, value in ENTRY_DATA.items() if key != CONF_STATUS}
    entry = _add_entry(hass, data)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.data[CONF_STATUS] == STATUS_AC2889

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_retry_when_status_fails(
    hass: HomeAssistant, mock_integration_client: AsyncMock
) -> None:
    """Test setup is retried and the client released when the first status fails."""
    client = mock_integration_client.client
    client.get_status = AsyncMock(side_effect=OSError("no answer"))
    data = {key: value for key, value in ENTRY_DATA.items() if key != CONF_STATUS}
    entry = _add_entry(hass, data)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    client.shutdown.assert_awaited_once()
