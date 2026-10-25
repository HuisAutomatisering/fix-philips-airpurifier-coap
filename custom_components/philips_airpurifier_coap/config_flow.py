"""Config flow for the Philips AirPurifier integration."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
from typing import Any

from aioairctrl import CoAPClient
import voluptuous as vol

from homeassistant import config_entries, exceptions
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .const import CONF_DEVICE_ID, CONF_MODEL, CONF_STATUS, DOMAIN, PhilipsApi
from .helpers import extract_model, extract_name
from .philips import model_to_class

_LOGGER = logging.getLogger(__name__)

# seconds to wait for the CoAP handshake and for the first status message
CONNECT_TIMEOUT = 30


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate that the device could not be reached."""


def host_valid(host: str) -> bool:
    """Return True if hostname or IP address is valid."""
    try:
        if ipaddress.ip_address(host).version in [4, 6]:
            return True
    except ValueError:
        pass
    disallowed = re.compile(r"[^a-zA-Z\d\-]")
    return all(x and not disallowed.search(x) for x in host.split("."))


async def async_fetch_status(host: str) -> dict[str, Any]:
    """Connect to the device and return its current status.

    Raises TimeoutError when the device does not answer in time and
    CannotConnect for any other connection problem.
    """
    client: CoAPClient | None = None
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT):
            client = await CoAPClient.create(host)
            _LOGGER.debug("got a valid client for host %s", host)

        async with asyncio.timeout(CONNECT_TIMEOUT):
            status, _ = await client.get_status()
            _LOGGER.debug("got status for host %s: %s", host, status)

    except TimeoutError:
        _LOGGER.warning("Timeout, host %s doesn't answer", host)
        raise
    except Exception as ex:  # aioairctrl/aiocoap raise many different error types
        _LOGGER.warning("Failed to connect to host %s: %s", host, ex)
        raise CannotConnect(str(ex)) from ex
    finally:
        if client is not None:
            try:
                await client.shutdown()
            except Exception as ex:  # closing a half-open client must not hide the result
                _LOGGER.debug("Error while closing client for host %s: %s", host, ex)

    return status


def resolve_model(status: dict[str, Any]) -> str | None:
    """Return the supported model key for a device status, or None if unsupported."""
    model = extract_model(status)
    wifi_version = status.get(PhilipsApi.WIFI_VERSION) or ""
    model_long = f"{model} {wifi_version.split('@')[0]}"
    model_family = model[:6]

    for candidate in (model, model_long, model_family):
        if candidate and candidate in model_to_class:
            _LOGGER.info("Model %s supported", candidate)
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
        _LOGGER.debug("async_step_dhcp: called, found: %s", discovery_info)

        host = discovery_info.ip

        try:
            status = await async_fetch_status(host)
        except TimeoutError:
            return self.async_abort(reason="timeout")
        except CannotConnect:
            return self.async_abort(reason="cannot_connect")

        device_id = status.get(PhilipsApi.DEVICE_ID)
        if not device_id:
            return self.async_abort(reason="model_unsupported")

        # use the device ID as unique_id, update the host if we know the device already
        await self.async_set_unique_id(device_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

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
                try:
                    status = await async_fetch_status(host)
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
        if not device_id:
            return self.async_abort(reason="model_unsupported")

        await self.async_set_unique_id(device_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

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
                    status = await async_fetch_status(new_host)
                except TimeoutError:
                    errors[CONF_HOST] = "timeout"
                except CannotConnect:
                    errors[CONF_HOST] = "connect"
                else:
                    expected = self.config_entry.data[CONF_DEVICE_ID]
                    device_id = status.get(PhilipsApi.DEVICE_ID)
                    if device_id != expected:
                        _LOGGER.warning(
                            "Device at %s has id %s, does not match configured device %s",
                            new_host,
                            device_id,
                            expected,
                        )
                        errors[CONF_HOST] = "different_device"
                    else:
                        return self.async_create_entry(title="", data={CONF_HOST: new_host})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Required(CONF_HOST, default=current_host): cv.string}),
            errors=errors,
        )
