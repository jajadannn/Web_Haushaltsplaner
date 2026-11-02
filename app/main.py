from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.errors import register_error_handlers
from app.middleware import UploadSizeLimit
from app.routers import (
    accounts,
    categories,
    imports,
    institutions,
    loans,
    reports,
    rules,
    transactions,
    users,
)

DESCRIPTION = """
Interner Finanzplaner. Das Profil wird über den Header **X-User-Id** gewählt
(ohne Passwort – kein Zugriffsschutz, nur für das interne Netz).

Geldbeträge sind Dezimalstrings mit zwei Nachkommastellen, z. B. `"1234.56"`.
Fehler haben immer das Format `{"error": {"code", "message", "details"}}`.
"""


def create_app() -> FastAPI:
    app = FastAPI(title="Finanzplaner API", version="0.1.0", description=DESCRIPTION)
    # Uploadgröße begrenzen, bevor FastAPI den Multipart-Body zwischenspeichert.
    # Vor CORS registriert: Die zuletzt registrierte Middleware ist die äußerste, so trägt
    # auch die 413-Antwort die CORS-Header und das Frontend kann sie lesen.
    app.add_middleware(UploadSizeLimit)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    for module in (users, institutions, accounts, categories, transactions, loans, imports, rules, reports):
        app.include_router(module.router)

    @app.get("/health", tags=["System"])
    def health():
        return {"status": "ok"}

    return app


app = create_app()
