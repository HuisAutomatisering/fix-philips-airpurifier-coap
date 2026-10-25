"""Base entity for the Philips AirPurifier integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import Entity

from .config_entry_data import ConfigEntryData
from .const import DOMAIN, MANUFACTURER, PhilipsApi
from .helpers import extract_model


class PhilipsEntity(Entity):
    """Class to represent a generic Philips entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        config_entry_data: ConfigEntryData,
    ) -> None:
        """Initialize the PhilipsEntity."""

        super().__init__()

        self.hass = hass
        self.config_entry = entry
        self.config_entry_data = config_entry_data
        self.coordinator = self.config_entry_data.coordinator

        name = self.config_entry_data.device_information.name
        model = extract_model(self._device_status)

        self._attr_device_info = DeviceInfo(
            name=name,
            manufacturer=MANUFACTURER,
            model=model,
            sw_version=self._device_status[PhilipsApi.WIFI_VERSION],
            serial_number=self._device_status[PhilipsApi.DEVICE_ID],
            identifiers={(DOMAIN, self._device_status[PhilipsApi.DEVICE_ID])},
            connections={(CONNECTION_NETWORK_MAC, self.config_entry_data.device_information.mac)}
            if self.config_entry_data.device_information.mac is not None
            else set(),
        )

    @property
    def should_poll(self) -> bool:
        """No need to poll. Coordinator notifies entity of updates."""
        return False

    @property
    def available(self):
        """Return if the device is available."""
        return self.coordinator.status is not None

    @property
    def _device_status(self) -> dict[str, Any]:
        """Return the status of the device."""
        return self.coordinator.status

    async def async_added_to_hass(self) -> None:
        """Register with hass that routine got added."""

        remove_callback = self.coordinator.async_add_listener(self._handle_coordinator_update)

        self.async_on_remove(remove_callback)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.config_entry_data.latest_status = self._device_status
        self.async_write_ha_state()
