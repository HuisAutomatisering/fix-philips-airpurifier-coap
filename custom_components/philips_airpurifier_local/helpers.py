"""Helper functions for Philips air purifier status."""

from __future__ import annotations

from ipaddress import ip_address
import math
from typing import Any

from homeassistant.helpers.device_registry import format_mac

from .const import PhilipsApi

INVALID_MAC_ADDRESSES = {
    "00:00:00:00:00:00",
    "ff:ff:ff:ff:ff:ff",
}

# longest valid DNS name
MAX_HOST_LENGTH = 253

# bounds for the CoAP Max-Age the device announces; it drives the reconnect watchdog
DEFAULT_MAX_AGE = 60
MIN_MAX_AGE = 15
MAX_MAX_AGE = 600

REDACTED = "**REDACTED**"
SENSITIVE_STATUS_KEYS = frozenset(
    {
        PhilipsApi.DEVICE_ID,
        PhilipsApi.PRODUCT_ID,
        PhilipsApi.NAME,
        PhilipsApi.NEW_NAME,
        PhilipsApi.NEW2_NAME,
    }
)


def extract_name(status: dict) -> str:
    """Extract the name from the status."""
    for name_key in [PhilipsApi.NAME, PhilipsApi.NEW_NAME, PhilipsApi.NEW2_NAME]:
        name = status.get(name_key)
        if name:
            return str(name)
    return ""


def extract_model(status: dict) -> str:
    """Extract the model from the status."""
    for model_key in [
        PhilipsApi.MODEL_ID,
        PhilipsApi.NEW_MODEL_ID,
        PhilipsApi.NEW2_MODEL_ID,
    ]:
        model = status.get(model_key)
        if model:
            return str(model)[:9]
    return ""


def normalize_connection_mac(mac_address: str | None) -> str | None:
    """Normalize and validate a MAC address for device registry connections."""
    if not mac_address:
        return None

    formatted_mac = format_mac(mac_address)
    if formatted_mac in INVALID_MAC_ADDRESSES:
        return None

    return formatted_mac


def safe_int(value: Any) -> int | None:
    """Return a device value as int, or None when it is missing or unusable."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, bool | int | float | str):
        try:
            return int(value)
        except (ValueError, OverflowError):
            return None
    return None


def safe_float(value: Any) -> float | None:
    """Return a device value as float, or None when it is missing or unusable."""
    if isinstance(value, bool | int | float | str):
        try:
            result = float(value)
        except (ValueError, OverflowError):
            return None
        return result if math.isfinite(result) else None
    return None


def clamp_max_age(value: Any) -> int:
    """Return the device's CoAP Max-Age limited to sane bounds.

    A device announcing 0 (or a huge value) would otherwise make the
    reconnect watchdog fire continuously (or never).
    """
    max_age = safe_int(value)
    if max_age is None:
        return DEFAULT_MAX_AGE
    return min(max(max_age, MIN_MAX_AGE), MAX_MAX_AGE)


def coap_host(host: str) -> str:
    """Return the host in the form needed inside a coap:// URI (IPv6 in brackets)."""
    try:
        address = ip_address(host)
    except ValueError:
        return host
    return f"[{address}]" if address.version == 6 else host


def redact_status(status: Any) -> Any:
    """Return a copy of a device status that is safe to log."""
    if not isinstance(status, dict):
        return status
    return {
        key: REDACTED if key in SENSITIVE_STATUS_KEYS else value for key, value in status.items()
    }
