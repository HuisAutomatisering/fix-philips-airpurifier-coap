"""Shared fixtures for Philips AirPurifier CoAP tests."""

import asyncio
from collections.abc import AsyncGenerator, Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant

from .const import MAC, STATUS_AC2889

DOMAIN_MODULE = "custom_components.philips_airpurifier_coap"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations for all tests."""


@pytest.fixture(autouse=True)
def mock_http_frontend(hass: HomeAssistant) -> None:
    """Mark the http and frontend dependencies as loaded.

    The integration only needs them to serve its icons; the icon setup itself
    (async_setup) is patched in the tests that load the integration.
    """
    hass.config.components.add("http")
    hass.config.components.add("frontend")


def make_client(status: dict[str, Any] | None = None) -> MagicMock:
    """Return a mocked aioairctrl CoAPClient."""
    status = status if status is not None else STATUS_AC2889
    client = MagicMock()
    client.get_status = AsyncMock(return_value=(dict(status), 60))
    client.shutdown = AsyncMock()
    client.set_control_value = AsyncMock(return_value=True)
    client.set_control_values = AsyncMock(return_value=True)

    async def _observe() -> AsyncGenerator[dict[str, Any]]:
        yield dict(status)
        # keep the observation open until the coordinator cancels it
        await asyncio.Event().wait()

    client.observe_status = _observe
    return client


@pytest.fixture
def mock_flow_client() -> Generator[MagicMock]:
    """Patch the CoAP client used by the config flow."""
    client = make_client()
    with patch(
        f"{DOMAIN_MODULE}.config_flow.CoAPClient.create",
        new=AsyncMock(return_value=client),
    ) as create:
        create.client = client
        yield create


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Prevent the config entry from being set up during config flow tests."""
    with (
        patch(f"{DOMAIN_MODULE}.async_setup", return_value=True),
        patch(f"{DOMAIN_MODULE}.async_setup_entry", return_value=True) as setup_entry,
    ):
        yield setup_entry


@pytest.fixture
def mock_integration_client() -> Generator[MagicMock]:
    """Patch the CoAP client and MAC lookup used when the integration is set up."""
    client = make_client()
    with (
        patch(f"{DOMAIN_MODULE}.async_setup", return_value=True),
        patch(f"{DOMAIN_MODULE}.get_mac_address", return_value=MAC),
        # __init__ and the coordinator share the same aioairctrl CoAPClient class
        patch(
            f"{DOMAIN_MODULE}.CoAPClient.create",
            new=AsyncMock(return_value=client),
        ) as create,
    ):
        create.client = client
        yield create
