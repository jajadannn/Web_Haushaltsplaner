"""Test-Infrastruktur: eigene PostgreSQL-Testdatenbank, Rollback nach jedem Test.

Das Schema wird pro Testlauf frisch per Alembic aufgebaut (prüft damit auch die Migrationen).
Jede Anfrage bekommt – wie im Betrieb – eine eigene Session; alle Sessions hängen über
SAVEPOINTs an einer äußeren Testtransaktion. `commit()` gibt nur den Savepoint frei,
eine fehlgeschlagene Anfrage verwirft ihre Änderungen, am Testende wird alles zurückgerollt.
"""

from collections.abc import Callable, Iterator

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.engine import Connection, Engine
from sqlmodel import Session

from alembic import command
from app.config import get_settings
from app.db import get_session
from app.main import app


@pytest.fixture(autouse=True)
def import_dir(tmp_path, monkeypatch):
    """Importordner je Test in einem temporären Verzeichnis."""
    path = tmp_path / "imports"
    monkeypatch.setattr(get_settings(), "import_dir", path)
    return path


def pytest_configure(config):
    config.addinivalue_line("markers", "echter_verbindungstest: prüft den echten KI-Verbindungstest (Socket gefälscht)")


@pytest.fixture(autouse=True)
def ki_ohne_netz(request, monkeypatch):
    """Tests sprechen nie mit echten KI-Servern: der kurze Verbindungstest gilt als erfolgreich."""
    from app.services import ai_gateway
    from tests.helpers.ai import reset_ai_health

    if request.node.get_closest_marker("echter_verbindungstest") is None:
        monkeypatch.setattr(ai_gateway, "_connectable", lambda url: True)
    reset_ai_health()


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    settings = get_settings()
    url = settings.test_database_url
    test_db, app_db = make_url(url), make_url(settings.database_url)
    # Schutz: das Schema wird gleich gelöscht – nie auf der Anwendungsdatenbank
    if "test" not in (test_db.database or "") or (test_db.host, test_db.port, test_db.database) == (
        app_db.host, app_db.port, app_db.database,
    ):
        pytest.exit(f"TEST_DATABASE_URL zeigt nicht auf eine eigene Testdatenbank: {test_db.database}", 2)
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def connection(engine: Engine) -> Iterator[Connection]:
    connection = engine.connect()
    outer = connection.begin()
    try:
        yield connection
    finally:
        outer.rollback()
        connection.close()


@pytest.fixture
def session(connection: Connection) -> Iterator[Session]:
    """Session für direkte DB-Zugriffe im Test (sieht alle Änderungen der Anfragen)."""
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        yield session


@pytest.fixture
def client(connection: Connection) -> Iterator[TestClient]:
    def request_session() -> Iterator[Session]:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session

    app.dependency_overrides[get_session] = request_session
    # wie ein Browser auf dem Rechner selbst – die Netzsperre lässt nur Heimnetz-Adressen zu
    with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --- Fabriken für häufige Testdaten -------------------------------------------


@pytest.fixture
def make_user(client: TestClient) -> Callable[..., dict]:
    def _make(name: str = "Alex") -> dict:
        response = client.post("/users", json={"name": name})
        assert response.status_code == 201, response.text
        user = response.json()
        user["headers"] = {"X-User-Id": str(user["id"])}
        return user

    return _make


@pytest.fixture
def user(make_user) -> dict:
    return make_user("Alex")


@pytest.fixture
def headers(user: dict) -> dict:
    return user["headers"]


@pytest.fixture
def other_user(make_user) -> dict:
    """Zweites Profil für Isolationstests."""
    return make_user("Kim")


@pytest.fixture
def make_institution(client: TestClient, headers: dict) -> Callable[..., dict]:
    def _make(name: str = "Sparkasse", hdrs: dict | None = None, **extra) -> dict:
        response = client.post("/institutions", json={"name": name, **extra}, headers=hdrs or headers)
        assert response.status_code == 201, response.text
        return response.json()

    return _make


@pytest.fixture
def make_account(client: TestClient, headers: dict) -> Callable[..., dict]:
    def _make(name: str = "Girokonto", hdrs: dict | None = None, **extra) -> dict:
        payload = {
            "name": name,
            "type": "checking",
            "opening_balance": "1000.00",
            "opening_balance_date": "2026-01-01",
            **extra,
        }
        response = client.post("/accounts", json=payload, headers=hdrs or headers)
        assert response.status_code == 201, response.text
        return response.json()

    return _make
