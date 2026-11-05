"""Regressionstests zu docs/PRUEFBERICHT_KI_2026-11-05.md – je Befund der dort beschriebene Nachweis."""

import os
from datetime import date
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
