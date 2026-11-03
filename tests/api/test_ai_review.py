"""Lokale KI in der Prüfliste: Warteschlange, Vorschläge, Schutz vor Überschreiben, Endpunkte.

Der KI-Server wird nicht aufgerufen – `ai_review.chat` liefert eine vorgegebene Antwort.
"""

import json
import threading
import time
from datetime import UTC, datetime

import pytest

from app.config import get_settings
from app.models import Transaction
from app.services import ai_review


@pytest.fixture
def giro(make_account):
    return make_account("Giro")


@pytest.fixture
def tanken(client, headers):
    response = client.post("/categories", json={"name": "Tanken", "type": "expense"}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def ki(monkeypatch):
    """Gefälschte KI: merkt sich die Anfragen, antwortet mit `ki.answer`."""

    class FakeAi:
        answer: dict | str = {}
        calls: list[list[dict]] = []

        def __call__(self, messages):
            self.calls.append(messages)
            return self.answer if isinstance(self.answer, str) else json.dumps(self.answer)

    fake = FakeAi()
    fake.calls = []
    monkeypatch.setattr(ai_review, "chat", fake)
    return fake


def book(client, headers, giro, amount="-54.23", description="Kartenzahlung", counterparty="ARAL STATION 12", **extra):
    payload = {"account_id": giro["id"], "booking_date": "2026-11-02", "amount": amount, "description": description,
               "counterparty": counterparty, **extra}
    response = client.post("/transactions", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_vorschlag_wird_als_automatisch_zugeordnet_eingetragen(client, headers, session, giro, tanken, ki):
    tx = book(client, headers, giro)
    ki.answer = {"kategorie_id": tanken["id"], "sicherheit": "hoch", "begruendung": "ARAL ist eine Tankstelle."}

    suggestion = ai_review.review_one(session, tx["id"])
    assert suggestion is not None and suggestion.category_id == tanken["id"]

    data = client.get(f"/transactions/{tx['id']}", headers=headers).json()
    assert (data["category_id"], data["category_source"], data["review_status"]) == (
        tanken["id"], "ai", "auto_categorized",
    )
    assert data["ai_note"] == "ARAL ist eine Tankstelle. (Sicherheit: hoch)"
    # bleibt in der Prüfliste – die KI bestätigt nie selbst
    review = client.get("/review", params={"status": "auto_categorized"}, headers=headers).json()
    assert [i["transaction"]["id"] for i in review["items"]] == [tx["id"]]


def test_anfrage_enthaelt_nur_passende_kategorien_und_buchung(client, headers, session, giro, tanken, ki):
    client.post("/categories", json={"name": "Nebenjob", "type": "income"}, headers=headers)
    tx = book(client, headers, giro)
    ki.answer = {"kategorie_id": 0, "sicherheit": "niedrig", "begruendung": "-"}
    ai_review.review_one(session, tx["id"])

    prompt = ki.calls[0][1]["content"]
    assert f"{tanken['id']}: Tanken" in prompt
    assert "Nebenjob" not in prompt  # Einnahmekategorie bei einer Ausgabe nicht angeboten
    assert "Betrag: -54,23 EUR (Ausgabe)" in prompt and "ARAL STATION 12" in prompt


def test_bestaetigte_buchungen_derselben_gegenpartei_als_beispiel(client, headers, session, giro, tanken, ki):
    alt = book(client, headers, giro, amount="-60.00", description="Tanken Oktober")
    client.post(f"/review/{alt['id']}/confirm", json={"category_id": tanken["id"]}, headers=headers)
    tx = book(client, headers, giro)
    ki.answer = {"kategorie_id": tanken["id"], "sicherheit": "hoch", "begruendung": "wie bisher"}
    ai_review.review_one(session, tx["id"])
    assert "„Tanken Oktober“ → Tanken" in ki.calls[0][1]["content"]


@pytest.mark.parametrize("answer", [
    "kein json",
    {"kategorie_id": 99999, "sicherheit": "hoch", "begruendung": "erfunden"},
    {"kategorie_id": 0, "sicherheit": "mittel", "begruendung": "zu unklar"},
])
def test_unbrauchbare_oder_leere_antwort_laesst_buchung_offen(client, headers, session, giro, tanken, ki, answer):
    tx = book(client, headers, giro)
    ki.answer = answer
    ai_review.review_one(session, tx["id"])
    data = client.get(f"/transactions/{tx['id']}", headers=headers).json()
    assert (data["category_id"], data["review_status"], data["category_source"]) == (None, "needs_review", "none")
    assert data["ai_note"].startswith("Keine passende Kategorie")
    # nicht noch einmal vorlegen
    assert ai_review.next_pending_id(session) is None


def test_ki_nicht_erreichbar_buchung_bleibt_in_der_warteschlange(client, headers, session, giro, tanken, monkeypatch):
    tx = book(client, headers, giro)

    def down(_messages):
        raise ai_review.AiUnavailable("Verbindung abgelehnt")

    monkeypatch.setattr(ai_review, "chat", down)
    with pytest.raises(ai_review.AiUnavailable):
        ai_review.review_one(session, tx["id"])
    assert ai_review.next_pending_id(session) == tx["id"]


def test_in_der_zwischenzeit_bestaetigt_gewinnt_der_nutzer(client, headers, session, giro, tanken, ki):
    andere = client.post("/categories", json={"name": "Auto", "type": "expense"}, headers=headers).json()
    tx = book(client, headers, giro)

    def answer_after_user_confirmed(messages):
        client.post(f"/review/{tx['id']}/confirm", json={"category_id": andere["id"]}, headers=headers)
        return json.dumps({"kategorie_id": tanken["id"], "sicherheit": "hoch", "begruendung": "x"})

    ki.answer = None
    ai_review.chat = answer_after_user_confirmed  # monkeypatch aus `ki` stellt das Original wieder her
    assert ai_review.review_one(session, tx["id"]) is None
    data = client.get(f"/transactions/{tx['id']}", headers=headers).json()
    assert (data["category_id"], data["review_status"]) == (andere["id"], "confirmed")


def test_warteschlange_ohne_kategorisierte_umbuchungen_und_ausgeschlossene(client, headers, session, giro, tanken):
    offen = book(client, headers, giro)
    book(client, headers, giro, category_id=tanken["id"])  # schon kategorisiert
    raus = session.get(Transaction, book(client, headers, giro)["id"])
    raus.excluded_at, raus.excluded_reason = datetime.now(UTC), "Test"  # wie bei einer ausgeschlossenen Importbuchung
    session.commit()
    ids = [t.id for t in session.exec(ai_review.pending_query())]
    assert ids == [offen["id"]]


def test_regel_ueberschreibt_ki_vorschlag(client, headers, session, giro, tanken, ki):
    auto = client.post("/categories", json={"name": "Auto", "type": "expense"}, headers=headers).json()
    tx = book(client, headers, giro)
    ki.answer = {"kategorie_id": auto["id"], "sicherheit": "mittel", "begruendung": "x"}
    ai_review.review_one(session, tx["id"])
    client.post("/mapping-rules", json={"name": "Aral", "pattern": "ARAL", "match_type": "contains",
                                        "match_field": "counterparty", "target_category_id": tanken["id"]}, headers=headers)
    client.post("/mapping-rules/apply", params={"dry_run": False}, headers=headers)
    data = client.get(f"/transactions/{tx['id']}", headers=headers).json()
    assert (data["category_id"], data["category_source"]) == (tanken["id"], "rule")


def test_status_und_erneut_pruefen(client, headers, session, giro, tanken, ki, monkeypatch):
    status = client.get("/review/ai", headers=headers).json()
    assert status == {"enabled": False, "model": None, "reachable": None, "pending": 0}

    tx = book(client, headers, giro)
    monkeypatch.setattr(get_settings(), "ai_url", "http://192.168.1.50:11434")
    monkeypatch.setattr(ai_review, "reachable", lambda: True)
    status = client.get("/review/ai", headers=headers).json()
    assert status == {"enabled": True, "model": get_settings().ai_model, "reachable": True, "pending": 1}

    ki.answer = {"kategorie_id": 0, "sicherheit": "niedrig", "begruendung": "unklar"}
    ai_review.review_one(session, tx["id"])
    assert client.get("/review/ai", headers=headers).json()["pending"] == 0

    assert client.post("/review/ai/retry", headers=headers).json() == {"queued": 1}
    assert client.get("/review/ai", headers=headers).json()["pending"] == 1
    assert session.get(Transaction, tx["id"], populate_existing=True).ai_note is None


def test_note_kuerzt_und_beschreibt():
    assert ai_review.Suggestion(None, "niedrig", "x").note == "Keine passende Kategorie: x"
    assert len(ai_review.Suggestion(1, "hoch", "a" * 500).note) == 300


@pytest.mark.parametrize(("url", "api", "path", "answer"), [
    ("http://192.168.1.50:11434", "ollama", "/api/chat", {"message": {"content": "{}"}}),
    ("http://192.168.178.40:1234/v1", "openai", "/chat/completions", {"choices": [{"message": {"content": "{}"}}]}),
    ("http://192.168.178.40:1234/v1/", "openai", "/chat/completions", {"choices": [{"message": {"content": "{}"}}]}),
])
def test_schnittstelle_nach_adresse(monkeypatch, url, api, path, answer):
    monkeypatch.setattr(get_settings(), "ai_url", url)
    sent = []
    monkeypatch.setattr(ai_review, "_post", lambda p, body, timeout: sent.append((p, body)) or answer)
    assert get_settings().ai_api == api
    assert ai_review.chat([{"role": "user", "content": "x"}]) == "{}"
    (sent_path, body), = sent
    assert sent_path == path and body["model"] == get_settings().ai_model and body["messages"][0]["content"] == "x"
    if api == "openai":
        assert body["response_format"]["json_schema"]["schema"] == ai_review.RESPONSE_SCHEMA
        assert body["reasoning_effort"] == "none"
    else:
        assert body["format"] == ai_review.RESPONSE_SCHEMA and body["stream"] is False


def test_server_fehler_wird_zu_ai_unavailable(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_url", "http://192.168.178.40:1234/v1")

    def kaputt(*_args, **_kwargs):
        return {"unerwartet": True}

    monkeypatch.setattr(ai_review, "_post", kaputt)
    with pytest.raises(ai_review.AiUnavailable):
        ai_review.chat([{"role": "user", "content": "x"}])


# --- Parallele Anfragen --------------------------------------------------------------------


class _FakeQueue:
    """Warteschlange ohne Datenbank: liefert IDs, bis alle einmal vergeben sind."""

    def __init__(self, n, stop):
        self.todo, self.stop, self.done = list(range(n, 0, -1)), stop, []
        self.lock, self.active, self.max_active = threading.Lock(), 0, 0

    def next_ids(self, _session, limit, exclude=None):
        with self.lock:
            ids = [i for i in self.todo if i not in (exclude or set())][:limit]
            return ids

    def review(self, _sessions, tx_id, fail=None):
        with self.lock:
            self.todo.remove(tx_id)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.05)  # KI „rechnet“
        with self.lock:
            self.active -= 1
            self.done.append(tx_id)
            if not self.todo and self.active == 0:
                self.stop.set()
        if fail:
            raise fail


class _NoSession:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def rollback(self):
        pass


@pytest.mark.parametrize("parallel", [1, 4])
def test_hoechstens_parallel_viele_anfragen_gleichzeitig(monkeypatch, parallel):
    stop = threading.Event()
    fake = _FakeQueue(10, stop)
    monkeypatch.setattr(ai_review, "IDLE_SECONDS", 0.01)
    monkeypatch.setattr(ai_review, "next_pending_ids", fake.next_ids)
    monkeypatch.setattr(ai_review, "_review_task", fake.review)
    worker = threading.Thread(target=ai_review.work_queue, args=(_NoSession, stop, parallel, lambda _id: None))
    worker.start()
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert sorted(fake.done) == list(range(1, 11))  # jede Buchung genau einmal
    assert fake.max_active == parallel


def test_server_weg_keine_neuen_anfragen_bis_zur_pause(monkeypatch):
    stop = threading.Event()
    fake = _FakeQueue(10, stop)
    pauses = []
    monkeypatch.setattr(ai_review, "IDLE_SECONDS", 0.01)
    monkeypatch.setattr(ai_review, "next_pending_ids", fake.next_ids)
    monkeypatch.setattr(ai_review, "_review_task",
                        lambda s, tx_id: fake.review(s, tx_id, fail=ai_review.AiUnavailable("weg")))
    real_wait = stop.wait

    def pause(seconds):
        if seconds == ai_review.BACKOFF_SECONDS:
            pauses.append(len(fake.done))
            stop.set()
        return real_wait(0)

    monkeypatch.setattr(stop, "wait", pause)
    ai_review.work_queue(_NoSession, stop, 4, lambda _id: None)
    assert pauses == [4]  # erste Runde zu Ende gebracht, dann Pause statt weiterer Anfragen


def test_unerwarteter_fehler_markiert_nur_diese_buchung(monkeypatch):
    stop = threading.Event()
    fake = _FakeQueue(3, stop)
    given_up = []
    monkeypatch.setattr(ai_review, "IDLE_SECONDS", 0.01)
    monkeypatch.setattr(ai_review, "next_pending_ids", fake.next_ids)
    monkeypatch.setattr(ai_review, "_review_task",
                        lambda s, tx_id: fake.review(s, tx_id, fail=RuntimeError("kaputt") if tx_id == 2 else None))
    ai_review.work_queue(_NoSession, stop, 4, given_up.append)
    assert given_up == [2] and sorted(fake.done) == [1, 2, 3]


def test_alle_vorschlaege_mit_einem_klick_bestaetigen(client, headers, session, giro, tanken, ki):
    vorschlaege = [book(client, headers, giro, description=f"Tanken {i}") for i in range(3)]
    offen = book(client, headers, giro, counterparty="Unbekannt")
    ki.answer = {"kategorie_id": tanken["id"], "sicherheit": "hoch", "begruendung": "Tankstelle"}
    for tx in vorschlaege:
        ai_review.review_one(session, tx["id"])

    response = client.post("/review/confirm-all", headers=headers)
    assert response.json() == {"confirmed": 3, "skipped": 0}
    for tx in vorschlaege:
        data = client.get(f"/transactions/{tx['id']}", headers=headers).json()
        assert (data["review_status"], data["category_id"], data["category_source"]) == ("confirmed", tanken["id"], "ai")
    # Buchungen ohne Vorschlag bleiben offen
    assert client.get(f"/transactions/{offen['id']}", headers=headers).json()["review_status"] == "needs_review"
    assert client.post("/review/confirm-all", headers=headers).json() == {"confirmed": 0, "skipped": 0}
