"""Regressionstests zu docs/PRUEFBERICHT_KI_2026-11-05.md – je Befund der dort beschriebene Nachweis."""

import os
from datetime import date
from decimal import Decimal
import subprocess
import tarfile
from pathlib import Path

from app.config import get_settings

PROJECT = Path(__file__).resolve().parents[2]


def _env(**extra):
    # nie die Anwendungsdatenbank: Sicherung und Wiederherstellung laufen gegen die Testdatenbank
    return {**os.environ, "DATABASE_URL": get_settings().test_database_url, **extra}


def _backup(tmp_path, imports, documents):
    result = subprocess.run(
        [str(PROJECT / "scripts/backup.sh"), str(tmp_path / "ziel")],
        env=_env(IMPORT_DIR=str(imports), DOCUMENT_DIR=str(documents)),
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    (archive,) = (tmp_path / "ziel").glob("imports_*.tar.gz")
    (dump,) = (tmp_path / "ziel").glob("finanzplaner_*.dump")
    return dump, archive


# N37 – Backup sichert Belege auch ohne Import-Unterordner
def test_n37_backup_ohne_importordner_enthaelt_belege(tmp_path):
    imports, documents = tmp_path / "imports", tmp_path / "docs"
    imports.mkdir()
    (documents / "1").mkdir(parents=True)
    (documents / "1" / "beleg.pdf").write_bytes(b"%PDF-1.4 beleg")
    _, archive = _backup(tmp_path, imports, documents)
    with tarfile.open(archive) as tar:
        assert "documents/1/beleg.pdf" in tar.getnames()


# N38 – Restore bricht bei vorhandenen Belegen ohne --yes ab
def test_n38_restore_ueberschreibt_belege_nicht_ohne_yes(tmp_path):
    imports, documents = tmp_path / "imports", tmp_path / "docs"
    (imports / "archive").mkdir(parents=True)
    documents.mkdir()
    (documents / "beleg.pdf").write_bytes(b"ALT")
    dump, archive = _backup(tmp_path, imports, documents)
    ziel_docs = tmp_path / "ziel-docs"
    ziel_docs.mkdir()
    (ziel_docs / "beleg.pdf").write_bytes(b"VORHANDEN")
    result = subprocess.run(
        [str(PROJECT / "scripts/restore.sh"), str(dump), str(archive), "--target-db", "fin_n38_nie_angelegt"],
        env=_env(IMPORT_DIR=str(tmp_path / "ziel-imports"), DOCUMENT_DIR=str(ziel_docs)),
        capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
    )
    assert result.returncode != 0
    assert "beleg.pdf" in result.stderr
    assert (ziel_docs / "beleg.pdf").read_bytes() == b"VORHANDEN"


# --- Gemeinsame Helfer für die API-Befunde -------------------------------------------------------

import pytest  # noqa: E402

from app import clock  # noqa: E402

HEUTE = date(2026, 11, 20)
IBAN_A, IBAN_B = "DE89370400440532013000", "DE02120300000000202051"


@pytest.fixture
def api(client, headers, user, monkeypatch, tmp_path):
    monkeypatch.setattr(clock, "today", lambda: HEUTE)
    monkeypatch.setattr(get_settings(), "document_dir", tmp_path / "documents")

    class Api:
        def req(self, method, path, body=None, expected=200, **params):
            r = client.request(method, path, json=body, headers=headers, params=params or None)
            assert r.status_code == expected, (path, r.status_code, r.text)
            return r.json() if r.content else None

        def raw(self, method, path, body=None):
            return client.request(method, path, json=body, headers=headers)

        def account(self, name="Giro", **extra):
            return self.req("POST", "/accounts", {"name": name, "type": "checking", "opening_balance": "5000",
                                                  "opening_balance_date": "2026-01-01", **extra}, 201)

        def category(self, name, type="expense"):
            return self.req("POST", "/categories", {"name": name, "type": type}, 201)

        def tx(self, account, amount, day, description="Prüfbuchung", **extra):
            return self.req("POST", "/transactions", {"account_id": account["id"], "amount": amount,
                                                      "booking_date": day, "description": description, **extra}, 201)

        def series(self, amount="-20", counterparty="Anbieter", iban=IBAN_B, months=(9, 10, 11), account=None,
                   category=None):
            account = account or self.account()
            category = category or self.category("Vertrag")
            txs = [self.tx(account, amount, f"2026-{m:02d}-02", "Vertrag", counterparty=counterparty,
                           counterparty_iban=iban, category_id=category["id"]) for m in months]
            return account, txs

        def refresh(self, detector=None):
            return self.req("POST", "/suggestions/refresh", **({"detector": detector} if detector else {}))

        def suggestions(self, kind):
            return self.req("GET", "/suggestions", kind=kind)

        def mode(self, key, value):
            return self.req("PATCH", f"/users/{user['id']}/settings", {key: value})

        def fixed(self, **extra):
            return self.req("POST", "/fixed-costs", {"name": "Vertrag", "amount": "20", "due_day": 2, **extra}, 201)

        def budget(self, month="2026-11-01"):
            return self.req("GET", "/budget/month", month=month)

        def upload_png(self):
            r = client.post("/documents", files={"file": ("beleg.png", b"\x89PNG\r\n\x1a\n", "image/png")},
                            headers=headers)
            assert r.status_code == 201, r.text
            return r.json()

        def transfer_pair(self):
            a = self.account(iban=IBAN_A)
            b = self.account("Zweitkonto", iban=IBAN_B)
            t = self.tx(a, "-100", "2026-11-02", "Transfer", counterparty_iban=IBAN_B)
            u = self.tx(b, "100", "2026-11-02")
            self.refresh("matching")
            (s,) = self.suggestions("transfer_match")
            return t, u, s

    return Api()


# N01 – veralteter Umbuchungsvorschlag erzeugt kein unausgeglichenes Paar
def test_n01_veralteter_umbuchungsvorschlag_wird_abgelehnt(api):
    t, u, s = api.transfer_pair()
    api.req("PATCH", f"/transactions/{u['id']}", {"amount": "200"})
    r = api.raw("POST", f"/suggestions/{s['id']}/accept", {})
    assert r.status_code == 409 and r.json()["error"]["code"] == "suggestion_stale"
    assert [api.req("GET", f"/transactions/{i['id']}")["kind"] for i in (t, u)] == ["regular", "regular"]


# N02 – Rücknahme einer Umbuchung macht sie wirklich rückgängig
def test_n02_ruecknahme_loest_das_umbuchungspaar(api):
    t, u, s = api.transfer_pair()
    api.req("POST", f"/suggestions/{s['id']}/accept", {})
    assert api.req("POST", f"/suggestions/{s['id']}/revert")["status"] == "reverted"
    for i in (t, u):
        current = api.req("GET", f"/transactions/{i['id']}")
        assert current["kind"] == "regular" and current["transfer_peer_id"] is None


# N03 – Preisanpassung lässt sich direkt danach zurücknehmen, samt Betragsgeschichte
def test_n03_preisanpassung_ist_ruecknehmbar(api):
    a = api.account()
    f = api.fixed()
    for m in (10, 11):
        t = api.tx(a, "-30", f"2026-{m}-02")
        api.req("POST", f"/fixed-costs/{f['id']}/payments", {"transaction_id": t["id"], "due_month": f"2026-{m}-01"},
                201)
    api.refresh("fixed_cost_changes")
    (s,) = api.suggestions("fixed_cost_change")
    api.req("POST", f"/suggestions/{s['id']}/accept", {})
    assert api.req("GET", f"/fixed-costs/{f['id']}")["amount"] == "30.00"
    assert api.req("POST", f"/suggestions/{s['id']}/revert")["status"] == "reverted"
    assert api.req("GET", f"/fixed-costs/{f['id']}")["amount"] == "20.00"
    assert api.req("GET", f"/fixed-costs/{f['id']}/amounts") == []
    assert api.budget()["items"][0]["amount"] == "20.00"


# N04 – Probelauf-Vorschläge werden beim Wechsel auf „auto“ übernommen
def test_n04_probelauf_wird_bei_automatik_uebernommen(api):
    api.series()
    api.mode("automation.fixed_cost", "dry_run")
    api.refresh()
    assert api.suggestions("fixed_cost_new")[0]["status"] == "dry_run"
    api.mode("automation.fixed_cost", "auto")
    api.refresh()
    assert api.suggestions("fixed_cost_new")[0]["status"] == "auto_applied"
    assert len(api.req("GET", "/fixed-costs")) == 1


# N05 – „Aus“ erzeugt keine Vorschläge
def test_n05_ausgeschaltete_erkennung_erzeugt_nichts(api):
    api.series()
    api.mode("automation.fixed_cost", "off")
    api.refresh()
    assert [s for s in api.suggestions("fixed_cost_new") if s["status"] in ("open", "dry_run")] == []
    api.mode("automation.fixed_cost", "suggest")
    api.refresh()
    assert api.suggestions("fixed_cost_new")[0]["status"] == "open"


# N06 – Übernahme prüft die aktuellen Beträge der Belege
def test_n06_geaenderte_belegbetraege_machen_vorschlag_veraltet(api):
    _, txs = api.series()
    api.refresh()
    (s,) = api.suggestions("fixed_cost_new")
    for t in txs:
        api.req("PATCH", f"/transactions/{t['id']}", {"amount": "-75"})
    r = api.raw("POST", f"/suggestions/{s['id']}/accept", {})
    assert r.status_code == 409 and r.json()["error"]["code"] == "suggestion_stale"
    assert api.req("GET", "/fixed-costs") == []


# N07 – zwischenzeitlich manuell angelegte Fixkost verhindert die doppelte Übernahme
def test_n07_manuelle_fixkost_verhindert_doppelte_uebernahme(api):
    api.series()
    api.refresh()
    (s,) = api.suggestions("fixed_cost_new")
    api.fixed(name="Schon manuell angelegt", match_text="Anbieter")
    r = api.raw("POST", f"/suggestions/{s['id']}/accept", {})
    assert r.status_code == 409 and r.json()["error"]["code"] == "suggestion_stale"
    assert len(api.req("GET", "/fixed-costs")) == 1


# N08 – Zahlung auf einem anderen Konto erledigt die Fixkost nicht
def test_n08_zahlung_auf_anderem_konto_zaehlt_nicht(api):
    a = api.account()
    b = api.account("Zweitkonto")
    api.fixed(account_id=a["id"], match_text="Internet")
    api.tx(b, "-20", "2026-11-02", "Internet")
    assert api.budget()["items"][0]["status"] != "paid"


# N09 – nachträglich positiver Betrag gilt nicht mehr als Fixkostenzahlung
def test_n09_positiv_gewordene_zahlung_zaehlt_nicht(api):
    a = api.account()
    f = api.fixed()
    t = api.tx(a, "-20", "2026-11-02")
    api.req("POST", f"/fixed-costs/{f['id']}/payments", {"transaction_id": t["id"], "due_month": "2026-11-01"}, 201)
    api.req("PATCH", f"/transactions/{t['id']}", {"amount": "20"})
    item = api.budget()["items"][0]
    assert item["status"] != "paid"


# N10 – eine Gehaltszahlung erledigt nicht mehrere Einnahmenserien
def test_n10_eine_zahlung_erledigt_nur_eine_einnahme(api):
    a = api.account()
    lohn = api.category("Lohn", "income")
    for name, text, amount in [("Job A", "Arbeitgeber A", "2000"), ("Job B", "Arbeitgeber B", "500")]:
        api.req("POST", "/expected-incomes", {"name": name, "amount": amount, "due_day": 28, "account_id": a["id"],
                                              "category_id": lohn["id"], "match_text": text}, 201)
    api.tx(a, "2000", "2026-11-19", "Gehalt", category_id=lohn["id"], counterparty="Arbeitgeber A")
    events = api.req("GET", f"/accounts/{a['id']}/forecast", until="2026-11-30")["events"]
    assert [e["name"] for e in events] == ["Job B"]


# N11 – bereits erfasste künftige Buchungen zählen in der Vorschau
def test_n11_kuenftige_buchung_erscheint_in_der_vorschau(api):
    a = api.account()
    api.fixed(account_id=a["id"], match_text="Internet", due_day=25)
    api.tx(a, "-20", "2026-11-25", "Internet")
    result = api.req("GET", f"/accounts/{a['id']}/forecast", until="2026-11-30")
    assert result["end_balance"] == "4980.00"
    assert len(result["events"]) == 1 and result["events"][0]["amount"] == "-20.00"


# N12 – Assistent summiert nur die passenden Teilbuchungen
def test_n12_assistent_summiert_splits_anteilig(api, session, user):
    from app.models import User
    from app.services import assistant

    a = api.account()
    internet, telefon = api.category("Internet"), api.category("Telefon")
    api.tx(a, "-100", "2026-11-02", "Sammelrechnung", splits=[{"amount": "-30", "category_id": internet["id"]},
                                                           {"amount": "-70", "category_id": telefon["id"]}])
    u = session.get(User, user["id"])
    params = {"date_from": "2026-11-01", "date_to": "2026-11-20", "kategorie_id": internet["id"]}
    assert assistant._execute(session, u, "transactions_search", params)[0]["sum"] == Decimal("-30")
    groups = assistant._execute(session, u, "sum_by", params)[0]["groups"]
    assert [(g["name"], Decimal(str(g["sum"]))) for g in groups] == [("Internet", Decimal("-30"))]


# N13/N14 – lokaler Erfassungs-Fallback: „vorgestern“ und Tausenderbeträge
def test_n13_n14_fallback_versteht_vorgestern_und_tausender(api, monkeypatch):
    from app.services import ai_gateway

    monkeypatch.setattr(ai_gateway, "enabled", lambda: False)
    assert api.req("POST", "/entries/parse", {"text": "Vorgestern 18,50 Euro Mittagessen"})["booking_date"] \
        == "2026-11-18"
    assert api.req("POST", "/entries/parse", {"text": "Heute 1.234,56 Euro Miete"})["amount"] == "-1234.56"


# N15 – KI-Abschaltung des Profils gilt für Erfassung und wartende Aufträge
def test_n15_profil_ohne_ki_fragt_die_ki_nicht(api, monkeypatch):
    from app.services import ai_gateway

    calls = []
    monkeypatch.setattr(ai_gateway, "enabled", lambda: True)
    monkeypatch.setattr(ai_gateway, "ask", lambda *a, **k: calls.append(a) or {})
    api.mode("ai.enabled", False)
    parsed = api.req("POST", "/entries/parse", {"text": "Heute 18,50 Euro Essen"})
    assert calls == [] and parsed["ai_used"] is False and parsed["amount"] == "-18.50"


def test_n15_wartender_auftrag_laeuft_nach_abschaltung_nicht(api, session, monkeypatch):
    from sqlmodel import select

    from app.models import AiJob
    from app.services import ai_gateway, ai_jobs

    monkeypatch.setattr(get_settings(), "ai_url", "http://ki.local:11434")
    doc = api.upload_png()
    api.mode("ai.enabled", False)
    calls = []
    monkeypatch.setattr(ai_gateway, "ask_vision", lambda *a, **k: calls.append(a) or {})
    ai_jobs.run_one(session)
    job = session.exec(select(AiJob).where(AiJob.ref_id == doc["id"])).one()
    assert calls == [] and job.status != "done"


# N16 – Beleg in Fremdwährung wird keiner EUR-Buchung zugeordnet
def test_n16_usd_beleg_wird_nicht_zugeordnet(api, session, user):
    from app.models import AiJob, Document
    from app.services import documents

    a = api.account()
    api.tx(a, "-100", "2026-11-02")
    doc = Document(user_id=user["id"], kind="receipt", original_filename="usd.pdf", stored_path="unused.pdf",
                   sha256="a" * 64, mime="application/pdf", size=1)
    session.add(doc)
    session.flush()
    job = AiJob(user_id=user["id"], kind=documents.EXTRACT, ref_type="document", ref_id=doc.id)
    session.add(job)
    session.flush()
    documents._finish(session, job, {"art": "beleg", "haendler": "Shop", "datum": "2026-11-02", "betrag": "100",
                                     "waehrung": "USD", "positionen": [], "vertrag": None, "fundstellen": []})
    session.flush()
    assert api.suggestions("receipt_match") == []


# N17 – normale Betragsänderung wirkt auch mit Betragsgeschichte
def test_n17_patch_betrag_wirkt_trotz_historie(api):
    f = api.fixed()
    api.req("POST", f"/fixed-costs/{f['id']}/amounts", {"amount": "30", "valid_from": "2026-10-01"}, 201)
    assert api.req("PATCH", f"/fixed-costs/{f['id']}", {"amount": "40"})["amount"] == "40.00"
    assert api.budget("2026-12-01")["items"][0]["amount"] == "40.00"
    assert api.budget("2026-10-01")["items"][0]["amount"] == "30.00"


# N18 – mehrere Erstattungen übersteigen den Einkauf nicht
def test_n18_erstattungen_hoechstens_bis_zum_einkauf(api):
    a = api.account()
    kleidung = api.category("Kleidung")
    api.tx(a, "-100", "2026-11-01", "Einkauf", counterparty="Shop", category_id=kleidung["id"])
    for day in (2, 3):
        api.tx(a, "100", f"2026-11-0{day}", "Gutschrift", counterparty="Shop")
    api.refresh("matching")
    for s in api.suggestions("refund_match"):
        api.raw("POST", f"/suggestions/{s['id']}/accept", {})
    accepted = [s for s in api.suggestions("refund_match") if s["status"] == "accepted"]
    assert len(accepted) == 1
    api.refresh("matching")
    assert [s for s in api.suggestions("refund_match") if s["status"] == "open"] == []


# N19 – Automatik übergeht keine KI-Einschätzung „keine Verpflichtung“
def test_n19_automatik_beachtet_negative_ki_einschaetzung(api, session):
    from app.models import Suggestion

    api.series()
    api.refresh()
    (s,) = api.suggestions("fixed_cost_new")
    obj = session.get(Suggestion, s["id"])
    obj.payload = {**obj.payload, "ai": {"ist_verpflichtung": False}}
    session.flush()
    api.mode("automation.fixed_cost", "auto")
    api.refresh()
    assert api.suggestions("fixed_cost_new")[0]["status"] == "open"


def test_n19_automatik_wartet_auf_die_ki(api, monkeypatch):
    from app.services import ai_gateway

    monkeypatch.setattr(ai_gateway, "enabled", lambda: True)
    api.mode("automation.fixed_cost", "auto")
    api.series()
    api.refresh()
    assert api.suggestions("fixed_cost_new")[0]["status"] == "open"


# N24 – nicht aufeinanderfolgende Abweichungen ändern den Plan nicht dauerhaft
def test_n24_luecke_zwischen_abweichungen_ist_nur_einmalig(api):
    a = api.account()
    f = api.fixed()
    for m in (8, 11):
        t = api.tx(a, "-30", f"2026-{m:02d}-02")
        api.req("POST", f"/fixed-costs/{f['id']}/payments",
                {"transaction_id": t["id"], "due_month": f"2026-{m:02d}-01"}, 201)
    api.mode("automation.fixed_cost_change", "auto")
    api.refresh("fixed_cost_changes")
    (s,) = api.suggestions("fixed_cost_change")
    assert s["payload"]["change"] == "einmalig" and s["status"] == "open"
    assert api.req("GET", f"/fixed-costs/{f['id']}")["amount"] == "20.00"


# N25 – Rücknahmequote bezieht sich auf alle übernommenen Fälle
def test_n25_ruecknahmequote(api):
    api.series()
    api.refresh()
    (s,) = api.suggestions("fixed_cost_new")
    api.req("POST", f"/suggestions/{s['id']}/accept", {})
    api.req("POST", f"/suggestions/{s['id']}/revert")
    (item,) = api.req("GET", "/suggestions/metrics", kind="fixed_cost_new")["items"]
    assert item["revert_rate"] == 1.0


# N26 – Split-Vorlage auf bereits (vorläufig) kategorisierter Buchung
def test_n26_split_vorlage_bei_vorkategorisierter_buchung(api, session):
    from app.models import Transaction

    a = api.account()
    internet, telefon = api.category("Internet"), api.category("Telefon")
    splits = [{"amount": "-30", "category_id": internet["id"]}, {"amount": "-70", "category_id": telefon["id"]}]
    for m in (9, 10):
        api.tx(a, "-100", f"2026-{m:02d}-02", "Sammelvertrag", counterparty="Provider", splits=splits)
    t = api.tx(a, "-100", "2026-11-02", "Sammelvertrag", counterparty="Provider")
    obj = session.get(Transaction, t["id"])
    obj.category_id, obj.category_source, obj.review_status = internet["id"], "ai", "auto_categorized"
    session.flush()
    api.refresh("matching")
    (s,) = api.suggestions("split_template")
    api.req("POST", f"/suggestions/{s['id']}/accept", {})
    current = api.req("GET", f"/transactions/{t['id']}")
    assert current["category_id"] is None and len(current["splits"]) == 2


# N27 – zwei Fixkosten aus verschiedenen Teilbuchungen derselben Buchung
def test_n27_zwei_fixkosten_aus_verschiedenen_splits(api):
    a = api.account()
    internet, telefon = api.category("Internet"), api.category("Telefon")
    splits = [{"amount": "-30", "category_id": internet["id"]}, {"amount": "-70", "category_id": telefon["id"]}]
    for m in (9, 10, 11):
        api.tx(a, "-100", f"2026-{m:02d}-02", "Sammelvertrag", counterparty="Provider", splits=splits)
    api.refresh()
    first, second = api.suggestions("fixed_cost_new")
    api.req("POST", f"/suggestions/{first['id']}/accept", {"name": "Internet"})
    api.req("POST", f"/suggestions/{second['id']}/accept", {"name": "Telefon"})
    assert len(api.req("GET", "/fixed-costs")) == 2


# N28 – Änderung erwarteter Einnahmen prüft die Spanne
def test_n28_umgekehrte_spanne_wird_abgelehnt(api):
    a = api.account()
    i = api.req("POST", "/expected-incomes", {"name": "Gehalt", "amount": "1500", "due_day": 28, "amount_min": "1000",
                                              "amount_max": "2000", "account_id": a["id"]}, 201)
    r = api.raw("PATCH", f"/expected-incomes/{i['id']}", {"amount_min": "3000"})
    assert r.status_code == 422
    assert api.req("GET", "/expected-incomes")[0]["amount_min"] == "1000.00"


# N29 – ungültige Übernahmewerte ergeben 422
def test_n29_ungueltiger_override_ist_422(api):
    api.series()
    api.refresh()
    (s,) = api.suggestions("fixed_cost_new")
    r = api.raw("POST", f"/suggestions/{s['id']}/accept", {"amount": "0"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


# N30 – alter Erstattungsvorschlag überschreibt keine manuelle Entscheidung
def test_n30_erstattung_ueberschreibt_manuelle_kategorie_nicht(api):
    a = api.account()
    kleidung, gehalt = api.category("Kleidung"), api.category("Gehalt", "income")
    api.tx(a, "-100", "2026-11-01", "Einkauf", counterparty="Shop", category_id=kleidung["id"])
    t = api.tx(a, "100", "2026-11-02", "Gutschrift", counterparty="Shop")
    api.refresh("matching")
    (s,) = api.suggestions("refund_match")
    api.req("PATCH", f"/transactions/{t['id']}", {"category_id": gehalt["id"]})
    r = api.raw("POST", f"/suggestions/{s['id']}/accept", {})
    assert r.status_code == 409
    assert api.req("GET", f"/transactions/{t['id']}")["category_id"] == gehalt["id"]


# N20 – nach IBAN-Treffer zählen auch Referenz-Aliasse des Vertrags
def test_n20_iban_treffer_verdeckt_vertragsalias_nicht(api, session, user):
    from app.services import merchants

    api.account()
    m = api.req("POST", "/merchants", {"name": "Mobilfunk"}, 201)
    api.req("POST", f"/merchants/{m['id']}/aliases", {"match_type": "iban", "value": IBAN_B}, 201)
    c = api.req("POST", f"/merchants/{m['id']}/contracts", {"label": "Ein Vertrag", "reference": "ABCD"}, 201)
    api.req("POST", f"/merchants/{m['id']}/aliases", {"match_type": "reference", "value": "EFGH",
                                                       "contract_id": c["id"]}, 201)
    resolver = merchants.Resolver(session, user["id"])
    assert resolver.resolve("Mobilfunk", IBAN_B, "Referenz ABCD").contract.id == c["id"]
    assert resolver.resolve("Mobilfunk", IBAN_B, "Referenz EFGH").contract.id == c["id"]


# N21 – Referenzen werden als ganzes Wort verglichen
def test_n21_referenz_ist_kein_teilstring(api, session, user):
    from app.services import merchants

    m = api.req("POST", "/merchants", {"name": "Mobilfunk"}, 201)
    api.req("POST", f"/merchants/{m['id']}/contracts", {"label": "Erster", "reference": "1234"}, 201)
    d = api.req("POST", f"/merchants/{m['id']}/contracts", {"label": "Zweiter", "reference": "12345"}, 201)
    resolved = merchants.Resolver(session, user["id"]).resolve("Mobilfunk", None, "Vertrag 12345")
    assert resolved.contract.id == d["id"]


# N22 – abgelehnte Rückfragen blockieren keine neuen
def test_n22_abgelehnte_rueckfragen_machen_platz(api):
    a = api.account()
    for n in range(4):
        m = api.req("POST", "/merchants", {"name": f"Anbieter {n}"}, 201)
        api.req("POST", f"/merchants/{m['id']}/aliases", {"match_type": "name", "value": f"Anbieter {n}"}, 201)
        for day, ref in [(1, "ABCD"), (2, "EFGH"), (3, "ABCD")]:
            api.tx(a, "-20", f"2026-11-0{day}", f"Vertrag {ref}", counterparty=f"Anbieter {n}")
    api.refresh("questions")
    before = api.suggestions("question")
    assert len(before) == 3
    for s in before:
        api.req("POST", f"/suggestions/{s['id']}/reject")
    api.refresh("questions")
    assert len([s for s in api.suggestions("question") if s["status"] == "open"]) == 1


# N31 – ein weiterer Vertrag bringt eine abgelehnte Serie nicht zurück
def test_n31_abgelehnte_serie_bleibt_abgelehnt(api):
    a, txs = api.series()
    api.refresh()
    (s,) = api.suggestions("fixed_cost_new")
    api.req("POST", f"/suggestions/{s['id']}/reject")
    for m in (9, 10, 11):
        api.tx(a, "-70", f"2026-{m:02d}-05", "Zweiter Vertrag", counterparty="Anbieter", counterparty_iban=IBAN_B,
               category_id=txs[0]["category_id"])
    api.refresh()
    found = api.suggestions("fixed_cost_new")
    assert not any(x["status"] == "open" and Decimal(x["payload"]["amount"]) == 20 for x in found)
    assert any(x["status"] == "open" and Decimal(x["payload"]["amount"]) == 70 for x in found)


def test_n31_alter_fingerprint_wird_uebernommen(api, session):
    from app.models import Suggestion

    api.series()
    api.refresh()
    (s,) = api.suggestions("fixed_cost_new")
    api.req("POST", f"/suggestions/{s['id']}/reject")
    obj = session.get(Suggestion, s["id"])
    obj.fingerprint = obj.fingerprint.rsplit("|~", 1)[0]  # Stand vor der Korrektur
    session.flush()
    api.refresh()
    found = api.suggestions("fixed_cost_new")
    assert [(x["id"], x["status"]) for x in found] == [(s["id"], "rejected")]


# N32 – Namenskonflikt in der Automatik ergibt keinen Serverfehler
def test_n32_namenskonflikt_in_der_automatik(api):
    api.series()
    api.fixed(name="Anbieter", active=False)
    api.mode("automation.fixed_cost", "auto")
    r = api.raw("POST", "/suggestions/refresh?detector=fixed_costs")
    assert r.status_code == 200, r.text
    assert api.suggestions("fixed_cost_new")[0]["status"] == "open"


# N33 – Regel-Rücknahme bemerkt eine manuelle Änderung von case_sensitive
def test_n33_regel_ruecknahme_beachtet_case_sensitive(api):
    a, txs = api.series()
    api.refresh("rules")
    (s,) = api.suggestions("rule")
    accepted = api.req("POST", f"/suggestions/{s['id']}/accept", {})
    api.req("PATCH", f"/mapping-rules/{accepted['result_id']}", {"case_sensitive": True})
    r = api.raw("POST", f"/suggestions/{s['id']}/revert")
    assert r.status_code == 409 and r.json()["error"]["code"] == "changed_since"
    assert len(api.req("GET", "/mapping-rules")) == 1


# N34 – Automatik übernimmt keinen inzwischen manuell übernommenen Vorschlag
def test_n34_automatik_und_manuelle_uebernahme_doppeln_nicht(api, session, user, monkeypatch):
    from app.models import User
    from app.services import suggestions as service

    a, txs = api.series()
    for m in (7, 8):
        api.tx(a, "-20", f"2026-{m:02d}-02", "Vertrag", counterparty="Anbieter", category_id=txs[0]["category_id"])
    api.refresh("rules")
    (s,) = api.suggestions("rule")
    api.mode("automation.rules", "auto")
    u = session.get(User, user["id"])
    original_lock = service._lock

    def manual_first(session_, user_, suggestion_id):
        # zwischen Auswahl und Sperre übernimmt jemand den Vorschlag von Hand
        monkeypatch.setattr(service, "_lock", original_lock)
        service.accept(session_, user_, suggestion_id)
        return original_lock(session_, user_, suggestion_id)

    monkeypatch.setattr(service, "_lock", manual_first)
    service._automate(session, u, "rule")
    session.flush()
    assert len(api.req("GET", "/mapping-rules")) == 1
    assert api.suggestions("rule")[0]["status"] == "accepted"


# N35 – Importassistent: falsche Dateien und Optionen ergeben 4xx statt 500
@pytest.mark.parametrize("body", [b"Keine CSV Tabelle", b"1;2;3\n4;5;6\n"])
def test_n35_entwurf_aus_ungueltiger_datei(client, headers, body):
    r = client.post("/import-profiles/draft", files={"file": ("a.csv", body, "text/csv")}, headers=headers)
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("options", ["[]", "null", '"text"', "{nicht json"])
def test_n35_vorschau_mit_ungueltigen_optionen(client, headers, options):
    csv = b"Datum;Betrag;Verwendungszweck\n02.11.2026;-20,00;Test\n"
    r = client.post("/import-profiles/preview", files={"file": ("a.csv", csv, "text/csv")},
                    data={"settings": options}, headers=headers)
    assert r.status_code == 422, r.text


# N36 – KI-Spaltenerkennung bekommt Beispielzeilen
def test_n36_ki_bekommt_beispielzeilen(client, headers, monkeypatch):
    from app.services import ai_gateway

    captured = {}

    def fake_ask(task, data, schema, **kw):
        captured.update(data)
        return {"zuordnung": []}

    monkeypatch.setattr(ai_gateway, "enabled", lambda: True)
    monkeypatch.setattr(ai_gateway, "ask", fake_ask)
    r = client.post("/import-profiles/draft", params={"ai": "true"}, headers=headers,
                    files={"file": ("x.csv", b"Tag;Wert;Partner;Notiz\n02.11.2026;-20,00;Laden;Einkauf\n", "text/csv")})
    assert r.status_code == 200, r.text
    assert captured["beispielzeilen"] == [{"Tag": "02.11.2026", "Wert": "-20,00", "Partner": "Laden",
                                           "Notiz": "Einkauf"}]
