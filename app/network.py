"""Netzsperre: Profile haben kein Passwort, deshalb antwortet der Finanzplaner nur im Heimnetz.

Reine ASGI-Middleware für API und ausgelieferte Oberfläche. Erlaubt sind die Netze aus
`allowed_networks` (Standard: Loopback und private Adressbereiche); alles andere bekommt
403 `local_network_only` im üblichen Fehlerformat.
"""

import ipaddress
import json
from functools import lru_cache

from app.config import get_settings


@lru_cache(maxsize=8)
def _networks(nets: tuple[str, ...]):
    return tuple(ipaddress.ip_network(net) for net in nets)


def is_allowed(host: str | None) -> bool:
    try:
        address = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    if address.version == 6 and address.ipv4_mapped:  # ::ffff:192.168.1.5
        address = address.ipv4_mapped
    return any(address in net for net in _networks(tuple(get_settings().allowed_networks)))


class LocalNetworkOnly:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            client = scope.get("client")
            if not is_allowed(client[0] if client else None):
                await _reject(scope, send)
                return
        await self.app(scope, receive, send)


async def _reject(scope, send) -> None:
    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1008})
        return
    body = json.dumps({"error": {
        "code": "local_network_only",
        "message": "Der Finanzplaner ist nur im Heimnetz erreichbar",
        "details": None,
    }}).encode()
    await send({
        "type": "http.response.start",
        "status": 403,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
    })
    await send({"type": "http.response.body", "body": body})
