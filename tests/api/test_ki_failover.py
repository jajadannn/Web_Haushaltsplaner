"""Zwei KI-Server mit Priorität: Priorität 1 zuerst, bei Ausfall Priorität 2 (Ausfallreihenfolge)."""

import json
import urllib.error

import pytest

from app.config import get_settings
from app.services import ai_gateway

SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"], "additionalProperties": False}
PRIMARY, SECONDARY = "http://ki-eins.local:11434", "http://ki-zwei.local:1234/v1"


@pytest.fixture
def server(monkeypatch):
    """Zwei gefälschte Server; `down` enthält die Adressen, die nicht antworten."""
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_url", PRIMARY)
    monkeypatch.setattr(settings, "ai_model", "modell-eins")
    monkeypatch.setattr(settings, "ai_vision_model", None)
    monkeypatch.setattr(settings, "ai_url_2", SECONDARY)
    monkeypatch.setattr(settings, "ai_model_2", "modell-zwei")
    monkeypatch.setattr(settings, "ai_vision_model_2", "bild-zwei")
    monkeypatch.setattr(settings, "ai_failover_cooldown_seconds", 60.0)
    ai_gateway.reset_health()

    class Fake:
        down: set = set()
        calls: list = []
        answer: dict = {"x": 1}

        def __call__(self, url, body, timeout):
            self.calls.append((url, body))
            if any(url.startswith(d) for d in self.down):
                raise urllib.error.URLError("Connection refused")
            content = json.dumps(self.answer)
            if url.endswith("/api/chat"):
                return {"message": {"content": content}}
            if url.endswith("/chat/completions"):
                return {"choices": [{"message": {"content": content}}]}
            return {"data": [{"id": "x"}]} if url.endswith("/models") else {"version": "0"}

    fake = Fake()
    fake.down, fake.calls = set(), []
    monkeypatch.setattr(ai_gateway, "_http", fake)
    monkeypatch.setattr(ai_gateway, "_connectable", lambda url: not any(url.startswith(d) for d in fake.down))
    yield fake
    ai_gateway.reset_health()


def test_prioritaet_eins_wird_zuerst_gefragt(server):
    assert ai_gateway.ask("Teste", {}, SCHEMA) == {"x": 1}
    assert [url for url, _ in server.calls] == [PRIMARY + "/api/chat"]
    assert server.calls[0][1]["model"] == "modell-eins"


def test_bei_ausfall_uebernimmt_prioritaet_zwei_mit_eigenem_modell_und_format(server):
    server.down = {PRIMARY}
    assert ai_gateway.ask("Teste", {}, SCHEMA) == {"x": 1}
    # der nicht erreichbare Server wird gar nicht erst mit der langen Anfrage belastet
    assert [url for url, _ in server.calls] == [SECONDARY + "/chat/completions"]
    assert server.calls[0][1]["model"] == "modell-zwei"
    assert ai_gateway.last_endpoint() == 2


def test_ausgefallener_server_wird_waehrend_der_abkuehlzeit_uebersprungen(server, monkeypatch):
    server.down = {PRIMARY}
    ai_gateway.ask("Teste", {}, SCHEMA)
    server.calls.clear()
    ai_gateway.ask("Teste", {"neu": 1}, SCHEMA)
    assert [url for url, _ in server.calls] == [SECONDARY + "/chat/completions"]
    # nach der Abkühlzeit wird Priorität 1 wieder versucht
    monkeypatch.setattr(ai_gateway, "_now", lambda: ai_gateway.time.monotonic() + 61)
    server.down, server.calls = set(), []
    ai_gateway.ask("Teste", {"neu": 2}, SCHEMA)
    assert [url for url, _ in server.calls] == [PRIMARY + "/api/chat"]


def test_fallen_beide_aus_gibt_es_einen_gemeinsamen_fehler(server):
    server.down = {PRIMARY, SECONDARY}
    with pytest.raises(ai_gateway.AiUnavailable) as exc:
        ai_gateway.ask("Teste", {}, SCHEMA)
    assert "Priorität 1" in str(exc.value) and "Priorität 2" in str(exc.value)


def test_ungueltige_antwort_fuehrt_nicht_zum_umschalten(server):
    server.answer = {"x": "kein int"}
    with pytest.raises(ai_gateway.AiInvalidAnswer):
        ai_gateway.ask("Teste", {}, SCHEMA)
    assert [url for url, _ in server.calls] == [PRIMARY + "/api/chat"]


def test_bild_nutzt_das_bildmodell_und_format_des_jeweiligen_servers(server):
    server.down = {PRIMARY}
    ai_gateway.ask_vision("Lies", b"\x89PNG", "image/png", SCHEMA)
    ((url, body),) = server.calls
    assert body["model"] == "bild-zwei" and isinstance(body["messages"][1]["content"], list)  # OpenAI-Format


def test_ohne_zweiten_server_bleibt_alles_wie_bisher(server, monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_url_2", None)
    server.down = {PRIMARY}
    with pytest.raises(ai_gateway.AiUnavailable):
        ai_gateway.ask("Teste", {}, SCHEMA)
    assert server.calls == []


def test_status_zeigt_beide_server(client, headers, server):
    server.down = {SECONDARY}
    status = client.get("/review/ai", headers=headers).json()
    assert status["enabled"] is True and status["reachable"] is True
    assert [(e["priority"], e["url"], e["model"], e["reachable"]) for e in status["endpoints"]] == [
        (1, PRIMARY, "modell-eins", True), (2, SECONDARY, "modell-zwei", False)]


def test_pruefliste_nutzt_ebenfalls_die_ausfallreihenfolge(server):
    from app.services import ai_review

    server.down = {PRIMARY}
    server.answer = {"kategorie_id": 0, "sicherheit": "niedrig", "begruendung": "keine passt"}
    content = ai_review.chat([{"role": "user", "content": "x"}])
    assert json.loads(content)["kategorie_id"] == 0
    assert server.calls[-1][0] == SECONDARY + "/chat/completions"


def test_bild_format_je_server(server):
    ai_gateway.ask_vision("Lies", b"\x89PNG", "image/png", SCHEMA)
    ((url, body),) = server.calls
    assert url == PRIMARY + "/api/chat" and "images" in body["messages"][1]  # Ollama-Format bei Priorität 1


@pytest.mark.echter_verbindungstest
def test_unerreichbarer_server_wird_schnell_erkannt(monkeypatch):
    import socket

    monkeypatch.setattr(get_settings(), "ai_connect_timeout_seconds", 0.5)
    seen = {}

    def fake_connect(address, timeout):
        seen["timeout"] = timeout
        raise TimeoutError("timed out")

    monkeypatch.setattr(socket, "create_connection", fake_connect)
    assert ai_gateway._connectable("http://192.0.2.1:1234/v1") is False and seen["timeout"] == 0.5


def test_fehlertext_des_servers_bleibt_erhalten(server, monkeypatch):
    import io

    def http_400(url, body, timeout):
        raise urllib.error.HTTPError(url, 400, "Bad Request", {}, io.BytesIO(b'{"error":"context length exceeded"}'))

    monkeypatch.setattr(get_settings(), "ai_url_2", None)
    monkeypatch.setattr(ai_gateway, "_http", http_400)
    with pytest.raises(ai_gateway.AiUnavailable) as exc:
        ai_gateway.ask("Teste", {}, SCHEMA)
    assert "context length exceeded" in str(exc.value)
