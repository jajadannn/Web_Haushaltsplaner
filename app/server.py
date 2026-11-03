"""Betrieb im Heimnetz über einen einzigen Port: API unter /api, Oberfläche als SPA.

    npm --prefix frontend run build
    uvicorn app.server:app --host 0.0.0.0 --port 8000

Danach ist der Finanzplaner im WLAN unter http://<rechner>:8000/ erreichbar, das
Wanddisplay unter http://<rechner>:8000/wand. Tests und Entwicklung nutzen weiter
`app.main:app` (ohne /api-Präfix, Vite leitet /api dorthin weiter).
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.main import app as api
from app.network import LocalNetworkOnly

DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def create_server(dist: Path = DIST) -> FastAPI:
    server = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    server.add_middleware(LocalNetworkOnly)
    server.mount("/api", api)
    root = dist.resolve()
    if (root / "assets").is_dir():
        # Dateinamen enthalten einen Inhalts-Hash – dürfen lange im Cache bleiben
        server.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @server.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        index = root / "index.html"
        if not index.is_file():
            return JSONResponse(status_code=503, content={"error": {
                "code": "frontend_not_built",
                "message": "Die Oberfläche ist noch nicht gebaut: npm --prefix frontend run build",
                "details": None,
            }})
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        # Client-Routen (/buchungen, /wand, …) lädt die SPA selbst
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return server


app = create_server()
