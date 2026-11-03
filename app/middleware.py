"""Begrenzung der Request-Größe für Uploads – VOR der Multipart-Verarbeitung.

FastAPI schreibt eine Multipart-Datei vollständig in eine temporäre Datei, bevor der
Handler läuft; eine Prüfung dort käme zu spät. Diese Middleware zählt die tatsächlich
eingehenden Bytes (ein `Content-Length`-Header allein ist nicht verlässlich) und antwortet
beim Überschreiten mit 413, ohne den Rest des Bodys zu lesen.
"""

import json

from app.config import get_settings

MULTIPART_OVERHEAD = 64 * 1024  # Rahmen und Formularfelder neben der Datei


class _TooLarge(Exception):
    pass


class UploadSizeLimit:
    def __init__(self, app, paths: tuple[str, ...] = ("/imports",)):
        self.app = app
        self.paths = paths

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        root = scope.get("root_path", "")
        if root and path.startswith(root):  # unter /api eingehängt (app/server.py)
            path = path[len(root):]
        if scope["type"] != "http" or scope["method"] != "POST" or path not in self.paths:
            await self.app(scope, receive, send)
            return
        limit_mb = get_settings().max_upload_mb
        limit = limit_mb * 1024 * 1024 + MULTIPART_OVERHEAD
        headers = dict(scope["headers"])
        declared = headers.get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await _reject(send, limit_mb)
            return

        received, exceeded, replied = 0, False, False

        async def limited_receive():
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    raise _TooLarge
            return message

        async def guarded_send(message):
            nonlocal replied
            if not exceeded:
                await send(message)
            elif not replied:  # Antwort der App (z. B. 400 „Body nicht lesbar“) durch 413 ersetzen
                replied = True
                await _reject(send, limit_mb)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _TooLarge:
            pass
        if exceeded and not replied:
            await _reject(send, limit_mb)


async def _reject(send, limit_mb: int) -> None:
    body = json.dumps(
        {"error": {"code": "file_too_large", "message": f"Datei größer als {limit_mb} MB", "details": None}}
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})
