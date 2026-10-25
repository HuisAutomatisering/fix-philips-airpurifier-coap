"""Module containing the ConfigEntryData class for the Philips Air Purifier integration."""

from dataclasses import dataclass

from aioairctrl import CoAPClient

from homeassistant.config_entries import ConfigEntry

from .coordinator import Coordinator
from .model import DeviceInformation, DeviceStatus


@dataclass
class ConfigEntryData:
    """Runtime data stored on the config entry (entry.runtime_data)."""

    device_information: DeviceInformation
    client: CoAPClient
    coordinator: Coordinator
    latest_status: DeviceStatus | None = None


type PhilipsConfigEntry = ConfigEntry[ConfigEntryData]
