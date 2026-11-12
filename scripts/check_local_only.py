"""Check that a Home Assistant integration only talks to its own device.

Runs with the Python standard library only (no installs), on Python 3.10+.
It reads the integration's manifest, Python code and front-end JavaScript and
fails when it finds anything that could send data elsewhere:

1. Manifest: the IoT class is local, only the dependencies and Python
   requirements explicitly allowed below.
2. Device client: aioairctrl's CoAPClient (encrypted CoAP over UDP, port 5683)
   is only created in the files allowed below, only for the configured host,
   and never with another port.
3. No other network use: no other network libraries, no listeners, sockets,
   HTTP client sessions or webhooks. The one exception: the icon files served
   to Home Assistant's own frontend (see HTTP_VIEW_FILES).
4. No hard-coded internet addresses in the Python code or the JavaScript.

What it does not cover: Home Assistant itself, and the code of an allowed
requirement. The runtime side (all traffic goes to the configured host and
port) is checked by tests/test_local_only.py.

Usage: python3 scripts/check_local_only.py [path/to/custom_components/<domain>]
"""

from __future__ import annotations

import ast
import ipaddress
import json
from pathlib import Path
import re
import sys

# ---------------------------------------------------------------------------
# Settings for this integration (Philips CoAP: UDP to the device, port 5683)
# ---------------------------------------------------------------------------
# The only network client: aioairctrl's CoAPClient.create(host). It talks
# encrypted CoAP over UDP to coap://<host>:5683 and nowhere else.
CLIENT_FACTORY = ("CoAPClient", "create")
# Files that may create the client: config flow (connection test), setup and
# the coordinator (reconnect).
CONNECTION_FILES = {"__init__.py", "config_flow.py", "coordinator.py"}
# The only accepted host arguments: the configured host. coap_host() wraps an
# IPv6 address in brackets; the coordinator stores that value in self.host.
# No other arguments are accepted, so the device port (5683) cannot change.
CLIENT_HOST_ARGUMENTS = {"coap_host(host)", "self.host"}

# Python requirements that are allowed, with the reason.
ALLOWED_REQUIREMENTS = {
    # The device's own protocol library: encrypted CoAP over UDP to the
    # configured host on port 5683 (it uses aiocoap as client only).
    "aioairctrl": "device protocol library",
    # Looks up the device's MAC address for the device registry. It reads the
    # local ARP/neighbour table; to fill that table it may send an ARP request
    # or an empty UDP packet to the device's own IP address (port 55555).
    # Nothing is sent anywhere else.
    "getmac": "MAC address of the configured device",
}
# The MAC lookup is only allowed here, and only with the configured host
# (keyword ip, ip6 or hostname, never a literal value).
MAC_LOOKUP_FILES = {"__init__.py"}
MAC_LOOKUP_FUNCTION = "get_mac_address"
MAC_LOOKUP_KEYWORDS = {"ip", "ip6", "hostname"}

# Manifest dependencies that are allowed: the integration serves its icon
# files to Home Assistant's own frontend (no new port, nothing outgoing).
ALLOWED_DEPENDENCIES = {"frontend", "http"}
# The only file that may register those icon files and the icon list on
# Home Assistant's web server. Every view there must require a login.
HTTP_VIEW_FILES = {"__init__.py"}
HTTP_MODULES = {"homeassistant.components.http", "homeassistant.helpers.http"}
HTTP_REGISTER_CALLS = {"register_view", "async_register_static_paths"}

# Literal addresses that are allowed. The SVG XML namespace in main.js is an
# identifier required by the SVG standard; the browser never fetches it.
ALLOWED_ADDRESSES = {"http://www.w3.org/2000/svg"}

# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
# Modules that talk to the network on their own, or serve. aiohttp and aiocoap
# are forbidden too: the integration needs neither directly.
FORBIDDEN_MODULES = {
    "aiocoap",
    "aiohttp",
    "aiomqtt",
    "asyncio_mqtt",
    "ftplib",
    "http.client",
    "http.server",
    "httpx",
    "paho",
    "pysnmp",
    "requests",
    "smtplib",
    "socket",
    "socketserver",
    "telnetlib",
    "urllib.request",
    "urllib3",
    "websockets",
    "xmlrpc",
    "zeroconf",
    "homeassistant.components.cloud",
    "homeassistant.components.mqtt",
    "homeassistant.components.webhook",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.httpx_client",
}
# Calls that listen for, or open, connections. The integration makes none of
# these itself: all device traffic goes through the client above.
NETWORK_CALLS = {
    "create_connection",
    "create_datagram_endpoint",
    "create_server",
    "create_unix_server",
    "open_connection",
    "open_unix_connection",
    "sendto",
    "sock_connect",
    "start_server",
    "start_unix_server",
    "ws_connect",
    "async_create_clientsession",
    "async_get_clientsession",
    "async_generate_url",
    "async_register",
}
# Browser APIs that could send data from the frontend JavaScript.
FORBIDDEN_JS = re.compile(r"\b(?:WebSocket|EventSource|XMLHttpRequest|sendBeacon|importScripts)\b")

_URL = re.compile(r"\b(?:https?|wss?|ftp|mqtts?|tcp|udp|coaps?)://([^\s/'\"`{}]+)[^\s'\"`]*", re.I)
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_TLDS = "com|net|org|io|dev|app|cloud|ai|co|eu|nl|de|be|uk|fr|info|biz|me|tv|us|cn"
_HOSTNAME = re.compile(rf"(?:[a-z0-9-]+\.)+(?:{_TLDS})", re.IGNORECASE)
# Example and local addresses never leave the network.
_HARMLESS_NETWORKS = [
    ipaddress.ip_network(net)
    for net in ("0.0.0.0/8", "127.0.0.0/8", "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")
]


def _harmless_ip(text: str) -> bool:
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return True  # Not an address (a version number, for instance).
    return any(address in network for network in _HARMLESS_NETWORKS)


def _call_name(node: ast.Call) -> tuple[str, str]:
    """Return (attribute or function name, name of the object it is called on)."""
    func = node.func
    if isinstance(func, ast.Attribute):
        owner = func.value
        if isinstance(owner, ast.Attribute):
            return func.attr, owner.attr
        if isinstance(owner, ast.Name):
            return func.attr, owner.id
        return func.attr, ""
    if isinstance(func, ast.Name):
        return func.id, ""
    return "", ""


def _addresses_in(text: str, where: str) -> list[str]:
    """Return problems for hard-coded addresses in a piece of text."""
    if text in ALLOWED_ADDRESSES:
        return []
    problems = [
        f"{where}: hard-coded address {match.group(0)!r}"
        for match in _URL.finditer(text)
        if match.group(0) not in ALLOWED_ADDRESSES
    ]
    problems += [
        f"{where}: hard-coded IP address {match.group(0)!r}"
        for match in _IPV4.finditer(text)
        if not _harmless_ip(match.group(0))
    ]
    if _HOSTNAME.fullmatch(text.strip()):
        problems.append(f"{where}: hard-coded host name {text!r}")
    return problems


def check_manifest(integration: Path) -> list[str]:
    """Check the manifest for cloud use, extra dependencies and requirements."""
    manifest = json.loads((integration / "manifest.json").read_text(encoding="utf-8"))
    problems = []
    iot_class = str(manifest.get("iot_class", ""))
    if not iot_class.startswith("local_"):
        problems.append(f"manifest.json: iot_class is {iot_class!r}, not local_*")
    dependencies = set(manifest.get("dependencies", [])) | set(
        manifest.get("after_dependencies", [])
    )
    for dependency in sorted(dependencies - ALLOWED_DEPENDENCIES):
        problems.append(f"manifest.json: dependency {dependency!r} is not allowed")
    allowed = {name.lower() for name in ALLOWED_REQUIREMENTS}
    for requirement in manifest.get("requirements", []):
        name = re.split(r"[<>=!~\[; ]", requirement, maxsplit=1)[0].lower()
        if name not in allowed:
            problems.append(f"manifest.json: requirement {requirement!r} is not allowed")
    return problems


def _check_client_call(node: ast.Call, filename: str, where: str) -> list[str]:
    """CoAPClient.create(): allowed files, configured host only, no port."""
    if filename not in CONNECTION_FILES:
        return [f"{where}: CoAPClient.create() outside {sorted(CONNECTION_FILES)}"]
    host = ast.unparse(node.args[0]) if len(node.args) == 1 else ""
    if node.keywords or host not in CLIENT_HOST_ARGUMENTS:
        return [
            f"{where}: CoAPClient.create({', '.join(ast.unparse(a) for a in node.args)}"
            f"{', ...' if node.keywords else ''}) is not the configured host"
        ]
    return []


def _check_mac_lookup(node: ast.Call, filename: str, where: str) -> list[str]:
    """get_mac_address (directly or through partial): allowed file, configured host only."""
    if filename not in MAC_LOOKUP_FILES:
        return [f"{where}: {MAC_LOOKUP_FUNCTION}() outside {sorted(MAC_LOOKUP_FILES)}"]
    problems = []
    for keyword in node.keywords:
        if keyword.arg not in MAC_LOOKUP_KEYWORDS or isinstance(keyword.value, ast.Constant):
            problems.append(f"{where}: {MAC_LOOKUP_FUNCTION}({keyword.arg}=...) is not allowed")
    if not node.keywords:
        problems.append(f"{where}: {MAC_LOOKUP_FUNCTION}() without the configured host")
    return problems


def _is_mac_lookup(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name) and func.id == MAC_LOOKUP_FUNCTION:
        return True
    # partial(get_mac_address, ip=host), run in the executor
    return (
        isinstance(func, ast.Name)
        and func.id == "partial"
        and bool(node.args)
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == MAC_LOOKUP_FUNCTION
    )


def _check_view(node: ast.ClassDef, filename: str, where: str) -> list[str]:
    """HomeAssistantView subclasses: allowed file only, and they must require a login."""
    if not any(ast.unparse(base).endswith("HomeAssistantView") for base in node.bases):
        return []
    if filename not in HTTP_VIEW_FILES:
        return [f"{where}: HTTP view {node.name} outside {sorted(HTTP_VIEW_FILES)}"]
    requires_auth = any(
        isinstance(item, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "requires_auth" for t in item.targets)
        and isinstance(item.value, ast.Constant)
        and item.value.value is True
        for item in node.body
    )
    if not requires_auth:
        return [f"{where}: HTTP view {node.name} does not set requires_auth = True"]
    return []


def check_source(path: Path, relative: str) -> list[str]:
    """Check one Python file of the integration."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    filename = path.name
    problems = []

    for node in ast.walk(tree):
        where = f"{relative}:{getattr(node, 'lineno', '?')}"
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                + [f"{node.module}.{alias.name}" for alias in node.names if node.module]
            )
            for name in names:
                if any(name == m or name.startswith(f"{m}.") for m in FORBIDDEN_MODULES):
                    problems.append(f"{where}: imports {name}")
                elif filename not in HTTP_VIEW_FILES and any(
                    name == m or name.startswith(f"{m}.") for m in HTTP_MODULES
                ):
                    problems.append(f"{where}: imports {name} outside {sorted(HTTP_VIEW_FILES)}")
                elif name.split(".")[0] == "getmac" and filename not in MAC_LOOKUP_FILES:
                    problems.append(f"{where}: imports {name} outside {sorted(MAC_LOOKUP_FILES)}")
        elif isinstance(node, ast.ClassDef):
            problems += _check_view(node, filename, where)
        elif isinstance(node, ast.Call):
            name, owner = _call_name(node)
            if (owner, name) == CLIENT_FACTORY:
                problems += _check_client_call(node, filename, where)
            elif _is_mac_lookup(node):
                problems += _check_mac_lookup(node, filename, where)
            elif name in HTTP_REGISTER_CALLS and filename not in HTTP_VIEW_FILES:
                problems.append(f"{where}: {name}() outside {sorted(HTTP_VIEW_FILES)}")
            elif name in NETWORK_CALLS:
                problems.append(f"{where}: {name}() opens or serves a connection")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            problems += _addresses_in(node.value, where)
    return problems


def check_frontend(path: Path, relative: str) -> list[str]:
    """Check front-end JavaScript: no addresses, no other browser network APIs."""
    problems = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        where = f"{relative}:{number}"
        problems += [p for p in _addresses_in(line, where) if "host name" not in p]
        for match in FORBIDDEN_JS.finditer(line):
            problems.append(f"{where}: uses {match.group(0)} in the frontend")
    return problems


def find_integration(argv: list[str]) -> Path:
    """Return the integration folder (argument, or the only one in custom_components)."""
    if len(argv) > 1:
        return Path(argv[1])
    root = Path(__file__).resolve().parents[1] / "custom_components"
    folders = [p for p in root.iterdir() if (p / "manifest.json").is_file()]
    if len(folders) != 1:
        raise SystemExit(f"Expected one integration in {root}, found {len(folders)}")
    return folders[0]


def main(argv: list[str]) -> int:
    """Run all checks and report."""
    integration = find_integration(argv)
    problems = check_manifest(integration)
    files = sorted(integration.rglob("*.py"))
    for path in files:
        problems += check_source(path, str(path.relative_to(integration.parent)))
    scripts = sorted(integration.rglob("*.js"))
    for path in scripts:
        problems += check_frontend(path, str(path.relative_to(integration.parent)))

    print(
        f"Local-only check of {integration.name}: "
        f"{len(files)} Python files, {len(scripts)} JavaScript files"
    )
    if problems:
        for problem in problems:
            print(f"  FAIL {problem}")
        return 1
    print("  OK   manifest: local IoT class, only allowed dependencies and requirements")
    print(
        f"  OK   device client only from {', '.join(sorted(CONNECTION_FILES))}, "
        "configured host only, fixed port"
    )
    print("  OK   no other network use; icon views only in __init__.py and login-only")
    print("  OK   no hard-coded internet addresses")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
