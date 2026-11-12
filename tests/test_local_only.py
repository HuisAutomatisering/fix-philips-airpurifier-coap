"""The integration only talks to the configured purifier.

The runtime half of the "local only" badge: the integration's real client
(aioairctrl, encrypted CoAP over UDP) runs against a fake purifier on a
loopback address. Every connection and datagram the integration makes during
the config flow, setup, push updates and commands is recorded and must go to
the configured host: CoAP on port 5683, plus the one documented exception,
getmac's empty UDP packet to the same host (port 55555) that fills the ARP
table for the MAC lookup. The static half is scripts/check_local_only.py,
which is tested here as well.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
import importlib.util
import json
from pathlib import Path
import shutil
import socket
from typing import Any
from unittest.mock import patch

import pytest
import pytest_socket

from custom_components.philips_airpurifier_local.const import DOMAIN
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import DOMAIN_MODULE
from .const import STATUS_AC2889
from .fake_device import COAP_PORT, FakePhilipsDevice, start_fake_device

ROOT = Path(__file__).resolve().parents[1]
# A loopback address that is not 127.0.0.1, so getmac really runs its lookup.
FAKE_HOST = "127.0.0.2"
# getmac fills the ARP table with an empty UDP packet to this port of the host.
GETMAC_PROBE_PORT = 55555


def _load_checker() -> Any:
    spec = importlib.util.spec_from_file_location(
        "check_local_only", ROOT / "scripts" / "check_local_only.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def expected_lingering_timers() -> bool:
    """aiocoap may keep protocol timers (message deduplication) briefly after shutdown."""
    return True


@pytest.fixture
async def fake_device(
    socket_enabled: None, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[tuple[FakePhilipsDevice, list[tuple[str, int]]]]:
    """Start the fake purifier and record every destination the integration uses."""
    pytest_socket.socket_allow_hosts(["127.0.0.1", FAKE_HOST])
    transport, device = await start_fake_device(dict(STATUS_AC2889), host=FAKE_HOST)
    destinations: list[tuple[str, int]] = []
    real_connect = socket.socket.connect
    real_sendto = socket.socket.sendto

    def _is_fake_device(sock: socket.socket) -> bool:
        try:
            return tuple(sock.getsockname()[:2]) == (FAKE_HOST, COAP_PORT)
        except OSError:
            return False

    def _record(sock: socket.socket, address: Any) -> None:
        if isinstance(address, tuple) and not _is_fake_device(sock):
            destinations.append((address[0], address[1]))

    def connect(self: socket.socket, address: Any) -> Any:
        _record(self, address)
        return real_connect(self, address)

    def sendto(self: socket.socket, data: bytes, *args: Any) -> Any:
        _record(self, args[-1])
        return real_sendto(self, data, *args)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "sendto", sendto)
    yield device, destinations
    transport.close()


async def _wait_for(condition: Any, timeout: float = 5) -> None:
    """Wait until condition() is true."""
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.05)


async def test_all_traffic_goes_to_the_device(
    hass: HomeAssistant,
    fake_device: tuple[FakePhilipsDevice, list[tuple[str, int]]],
) -> None:
    """Config flow, setup, push updates and commands only reach the configured purifier."""
    device, destinations = fake_device

    # the icon files are served by Home Assistant's own web server, not needed here
    with patch(f"{DOMAIN_MODULE}.async_setup", return_value=True):
        # config flow: connection test with the real client
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data={CONF_HOST: FAKE_HOST}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        entry = result["result"]

        # setup: MAC lookup, connection and status observation
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        coordinator = entry.runtime_data.coordinator

        # push updates (this device pushes instead of being polled)
        device.push(pm25=42)
        await _wait_for(lambda: (coordinator.status or {}).get("pm25") == 42)

        # command
        fan = hass.states.async_entity_ids("fan")[0]
        await hass.services.async_call("fan", "turn_off", {"entity_id": fan}, blocking=True)
        assert device.commands == [{"pwr": "0"}]
        await _wait_for(lambda: (coordinator.status or {}).get("pwr") == "0")

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert {path for path, _ in device.requests} == {
        "/sys/dev/sync",
        "/sys/dev/status",
        "/sys/dev/control",
    }
    assert (FAKE_HOST, COAP_PORT) in destinations, "the test made no CoAP traffic"
    assert {host for host, _ in destinations} == {FAKE_HOST}
    assert set(destinations) <= {(FAKE_HOST, COAP_PORT), (FAKE_HOST, GETMAC_PROBE_PORT)}


def test_static_check_passes() -> None:
    """The integration passes scripts/check_local_only.py."""
    checker = _load_checker()
    assert checker.main(["check_local_only.py"]) == 0


def test_static_check_catches_leaks(tmp_path: Path) -> None:
    """The check fails on an integration that could send data elsewhere."""
    checker = _load_checker()
    leaky = tmp_path / "leaky"
    shutil.copytree(ROOT / "custom_components" / "philips_airpurifier_local", leaky)

    manifest = json.loads((leaky / "manifest.json").read_text())
    manifest.update(
        iot_class="cloud_polling",
        requirements=[*manifest["requirements"], "phonehome==1.0"],
        dependencies=[*manifest["dependencies"], "cloud"],
    )
    (leaky / "manifest.json").write_text(json.dumps(manifest))

    # the device client with another port, and an icon list without login
    coordinator = leaky / "coordinator.py"
    coordinator.write_text(
        coordinator.read_text().replace(
            "CoAPClient.create(self.host)", "CoAPClient.create(self.host, port=5684)"
        )
    )
    init = leaky / "__init__.py"
    init.write_text(init.read_text().replace("requires_auth = True", "requires_auth = False"))

    # the frontend phoning home
    main_js = leaky / "main.js"
    main_js.write_text(
        main_js.read_text() + '\nnavigator.sendBeacon("https://stats.example.com/hit");\n'
    )

    (leaky / "telemetry.py").write_text(
        "import asyncio\n"
        "import socket\n"
        "import aiohttp\n"
        "from aioairctrl import CoAPClient\n"
        "from getmac import get_mac_address\n"
        "from homeassistant.helpers.aiohttp_client import async_get_clientsession\n"
        "from homeassistant.helpers.http import HomeAssistantView\n\n\n"
        "async def leak(hass):\n"
        "    session = async_get_clientsession(hass)\n"
        "    await session.post('https://telemetry.example.com/collect')\n"
        "    await CoAPClient.create('8.8.8.8')\n"
        "    get_mac_address(ip='10.1.2.3')\n"
        "    await asyncio.start_server(None, '0.0.0.0', 8080)\n"
        "    socket.socket().sendto(b'x', ('1.1.1.1', 53))\n"
        "    return 'analytics.vendor.io'\n"
    )

    problems = checker.check_manifest(leaky)
    for path in sorted(leaky.glob("*.py")):
        problems += checker.check_source(path, f"leaky/{path.name}")
    problems += checker.check_frontend(main_js, "leaky/main.js")
    text = "\n".join(problems)
    for expected in (
        "iot_class",
        "phonehome",
        "dependency 'cloud'",
        "CoAPClient.create(self.host, ...) is not the configured host",
        "does not set requires_auth = True",
        "sendBeacon",
        "https://stats.example.com/hit",
        "imports socket",
        "imports aiohttp",
        "imports homeassistant.helpers.aiohttp_client",
        "leaky/telemetry.py:7: imports homeassistant.helpers.http outside",
        "imports getmac outside",
        "CoAPClient.create() outside",
        "get_mac_address() outside",
        "async_get_clientsession() opens or serves",
        "start_server() opens or serves",
        "sendto() opens or serves",
        "https://telemetry.example.com",
        "8.8.8.8",
        "1.1.1.1",
        "analytics.vendor.io",
    ):
        assert expected in text, expected
    assert checker.main(["check_local_only.py", str(leaky)]) == 1
