"""A fake Philips purifier for tests.

It speaks the real protocol (encrypted CoAP over UDP, as implemented by
aioairctrl) on 127.0.0.1, so the integration's real client can be used
against it: sync, status with observation (push), and control commands.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
from typing import Any

from aioairctrl.coap.encryption import EncryptionContext
from aiocoap import NON, Message
from aiocoap.numbers.codes import CHANGED, CONTENT, NOT_FOUND

COAP_PORT = 5683
_PROTOCOL_FIELDS = {"CommandType", "DeviceId", "EnduserId"}


class FakePhilipsDevice(asyncio.DatagramProtocol):
    """Answers the Philips CoAP requests and pushes status updates."""

    def __init__(self, status: dict[str, Any], max_age: int = 60) -> None:
        """Initialize with the status the device reports."""
        self.status = dict(status)
        self.max_age = max_age
        self.transport: asyncio.DatagramTransport | None = None
        self.requests: list[tuple[str, tuple[str, int]]] = []
        self.commands: list[dict[str, Any]] = []
        self._observers: dict[tuple[str, int], bytes] = {}
        self._mids = itertools.count(1)
        self._observe_seq = itertools.count(2)
        self._encryption = EncryptionContext()
        self._encryption.set_client_key("00000000")

    # --- asyncio protocol ---------------------------------------------------

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Store the transport."""
        self.transport = transport  # type: ignore[assignment]

    def error_received(self, exc: Exception) -> None:
        """Ignore ICMP errors for clients that already closed their socket."""

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle one CoAP request."""
        try:
            request = Message.decode(data)
        except ValueError:
            return
        if not request.code.is_request():
            return  # resets and acknowledgements from the client
        path = "/" + "/".join(request.opt.uri_path)
        self.requests.append((path, addr))

        if path == "/sys/dev/sync":
            self._send(addr, request.token, CHANGED, os.urandom(4).hex().upper().encode())
        elif path == "/sys/dev/status":
            if request.opt.observe == 0:
                self._observers[addr] = request.token
            elif request.opt.observe == 1:
                self._observers.pop(addr, None)
            self._send(
                addr,
                request.token,
                CONTENT,
                self._encrypted_status(),
                observe=addr in self._observers,
            )
        elif path == "/sys/dev/control":
            payload = json.loads(self._encryption.decrypt(request.payload.decode()))
            desired = {
                key: value
                for key, value in payload["state"]["desired"].items()
                if key not in _PROTOCOL_FIELDS
            }
            self.commands.append(desired)
            self.status.update(desired)
            self._send(addr, request.token, CHANGED, json.dumps({"status": "success"}).encode())
            self.push()  # a real device reports its new state right away
        else:
            self._send(addr, request.token, NOT_FOUND, b"")

    # --- helpers ------------------------------------------------------------

    def push(self, **changes: Any) -> None:
        """Apply status changes and notify all observers (the device's push updates)."""
        self.status.update(changes)
        for addr, token in list(self._observers.items()):
            self._send(addr, token, CONTENT, self._encrypted_status(), observe=True)

    def _encrypted_status(self) -> bytes:
        payload = json.dumps({"state": {"reported": self.status}})
        return self._encryption.encrypt(payload).encode()

    def _send(
        self,
        addr: tuple[str, int],
        token: bytes,
        code: Any,
        payload: bytes,
        observe: bool = False,
    ) -> None:
        message = Message(mtype=NON, mid=next(self._mids) % 0x10000, code=code, token=token)
        message.payload = payload
        if observe:
            message.opt.observe = next(self._observe_seq)
            message.opt.max_age = self.max_age
        if self.transport is not None:
            self.transport.sendto(message.encode(), addr)


async def start_fake_device(
    status: dict[str, Any], host: str = "127.0.0.1"
) -> tuple[asyncio.DatagramTransport, FakePhilipsDevice]:
    """Start the fake device on host:5683."""
    loop = asyncio.get_running_loop()
    transport, device = await loop.create_datagram_endpoint(
        lambda: FakePhilipsDevice(status), local_addr=(host, COAP_PORT)
    )
    return transport, device  # type: ignore[return-value]
