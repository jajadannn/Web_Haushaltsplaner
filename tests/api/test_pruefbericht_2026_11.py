"""Regressionstests zu docs/PRUEFBERICHT_2026-11-03.md (F1–F16) und docs/SINNFEHLER_2026-11-04.md (S1–S9).

Je Befund der dort beschriebene Nachweis in kleinster Form. Reine Frontend-Befunde stehen in den
Vitest-Dateien unter frontend/src.
"""

import json
import threading
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlmodel import Session

from app import clock
from app.errors import Invalid
from app.models import ImportBatch, User
from app.services import ai_review
from app.services.categorization import check_regex_size, compile_pattern
from tests.api.test_imports import COLUMN_MAP, IBAN_A, commit, csv_file, resolve, upload


@pytest.fixture
def bank(make_institution):
    return make_institution("Sparkasse")


@pytest.fixture
def giro(make_account, bank):
    return make_account("Giro", institution_id=bank["id"], iban=IBAN_A, opening_balance="5000.00")


@pytest.fixture
def profile(client, headers, bank):
    return client.post("/import-profiles", json={"name": "CSV", "institution_id": bank["id"], "format": "csv",
                                                 "column_map": COLUMN_MAP}, headers=headers).json()


def _loan(client, headers, **extra):
    payload = {"name": "Kredit", "loan_type": "annuity", "lender_name": "Bank", "annual_interest_rate": "0",
               "current_balance": "1000.00", "balance_date": "2026-01-01", "first_due_date": "2026-01-31",
               "term_months": 12, **extra}
    response = client.post("/loans", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _private(client, headers, giro, **extra):
    return _loan(client, headers, loan_type="private", term_months=None, first_due_date=None,
                 payment_account_id=giro["id"], **extra)


def _pay(client, headers, loan, day, amount, expect=201):
    response = client.post(f"/loans/{loan['id']}/payments", json={"booking_date": day, "amount": amount},
                           headers=headers)
    assert response.status_code == expect, response.text
    return response.json()


def _charge(client, headers, loan, day, amount):
    response = client.post(f"/loans/{loan['id']}/charges",
                           json={"booking_date": day, "amount": amount, "charge_type": "fee"}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _get_loan(client, headers, loan):
    return client.get(f"/loans/{loan['id']}", headers=headers).json()


def _cat(client, headers, name, type_="expense"):
    response = client.post("/categories", json={"name": name, "type": type_}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _tx(client, headers, account, day, amount, category=None, **extra):
    payload = {"account_id": account["id"], "booking_date": day, "amount": amount,
               "description": extra.pop("description", "Buchung"), **extra}
    if category:
        payload["category_id"] = category["id"]
    response = client.post("/transactions", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _budget(client, headers, month):
    response = client.get("/budget/month", params={"month": month}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def maerz(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: date(2026, 3, 31))


@pytest.fixture
def gehalt(client, headers, giro):
    """1.000 € Einnahmen im März."""
    category = _cat(client, headers, "Gehalt-Test", "income")
    _tx(client, headers, giro, "2026-03-01", "1000.00", category, description="Gehalt")
    return category


# --- F1: Regex-Schutz berücksichtigt Verschachtelung ------------------------------------------


@pytest.mark.parametrize("pattern", [r"((x{100}){100}){100}", r"(((x{75}){75}){75}){75}", r"(?:(a{50})+){50}"])
def test_f1_verschachtelte_wiederholungen_werden_abgelehnt(pattern):
    with pytest.raises(Invalid) as exc:
        check_regex_size(pattern)
    assert exc.value.code == "regex_too_complex"


@pytest.mark.parametrize("pattern", [r"\d{2}\.\d{2}\.\d{4}", r"(ab{2}){3}", r"[{}]x{3}", r"Miete\s+\d{1,6}"])
def test_f1_typische_muster_bleiben_erlaubt(pattern):
    check_regex_size(pattern)


def test_f1_schutz_gilt_auch_beim_kompilieren_gespeicherter_regeln():
    with pytest.raises(Invalid):
        compile_pattern(r"((x{100}){100}){100}", "regex", False)


# --- F2: Parallele Kreditzahlungen ------------------------------------------------------------


@pytest.fixture
def committed_loan(engine):
    """Kredit in echten, festgeschriebenen Daten – zwei Verbindungen sollen ihn sehen."""
    from app.schemas.loan import LoanCreate
    from app.services.loans.core import create_loan

    with Session(engine) as s:
        user = User(name="Parallel-F2")
        s.add(user)
        s.commit()
        from app.models import Account

        giro_acc = Account(user_id=user.id, name="Giro-F2", type="checking", opening_balance=Decimal("5000"),
                           opening_balance_date=date(2026, 1, 1))
        s.add(giro_acc)
        s.flush()
        loan = create_loan(s, user, LoanCreate(
            name="Kredit-F2", loan_type="private", lender_name="Oma", annual_interest_rate=Decimal("0"),
            current_balance=Decimal("1000.00"), balance_date=date(2026, 1, 1), payment_account_id=giro_acc.id))
        s.commit()
        ids = {"user": user.id, "loan": loan.id}
    yield ids
    with engine.begin() as conn:
        uid = ids["user"]
        conn.execute(text('UPDATE "transaction" SET transfer_peer_id = NULL WHERE user_id = :u'), {"u": uid})
        conn.execute(text("DELETE FROM loan WHERE user_id = :u"), {"u": uid})
        conn.execute(text('DELETE FROM "transaction" WHERE user_id = :u'), {"u": uid})
        conn.execute(text("DELETE FROM account WHERE user_id = :u"), {"u": uid})
        conn.execute(text("UPDATE category SET parent_id = NULL WHERE user_id = :u"), {"u": uid})
        conn.execute(text("DELETE FROM category WHERE user_id = :u"), {"u": uid})
        conn.execute(text('DELETE FROM app_user WHERE id = :u'), {"u": uid})


def test_f2_zweite_parallele_zahlung_wartet_und_sieht_die_erste(engine, committed_loan):
    from app.schemas.loan import LoanPaymentCreate
    from app.services.loans.core import get_loan, remaining_debt
    from app.services.loans.payments import record_payment

    data = LoanPaymentCreate(booking_date=date(2026, 2, 1), amount=Decimal("750.00"))
    first = Session(engine)
    user = first.get(User, committed_loan["user"])
    record_payment(first, user, get_loan(first, user, committed_loan["loan"]), data)  # Sperre gehalten

    outcome: dict = {}

    def second_payment():
        with Session(engine) as s:
            s.execute(text("SET lock_timeout = '10s'"))
            u = s.get(User, committed_loan["user"])
            try:
                record_payment(s, u, get_loan(s, u, committed_loan["loan"]), data)
                s.commit()
                outcome["result"] = "gebucht"
            except Invalid as exc:
                outcome["result"] = exc.code

    worker = threading.Thread(target=second_payment)
    worker.start()
    worker.join(1.0)
    first.commit()
    first.close()
    worker.join(15)
    assert outcome["result"] == "principal_exceeds_debt"
    with Session(engine) as s:
        u = s.get(User, committed_loan["user"])
        assert remaining_debt(s, get_loan(s, u, committed_loan["loan"])) == Decimal("250.00")


# --- F3/F4/F5: Monatsbudget mit tatsächlichen Zahlungen ---------------------------------------


def test_f3_zahlung_ohne_kreditplan_mindert_das_budget(client, headers, giro, gehalt, maerz):
    loan = _private(client, headers, giro)
    _pay(client, headers, loan, "2026-03-10", "250.00")
    assert _budget(client, headers, "2026-03-01")["available"] == "750.00"


def test_f4_mehrzahlung_auf_fixkost_verschwindet_nicht(client, headers, giro, gehalt, maerz):
    versicherung = _cat(client, headers, "Versicherung-Test")
    client.post("/fixed-costs", json={"name": "Versicherung", "amount": "100.00", "due_day": 5,
                                      "category_id": versicherung["id"]}, headers=headers)
    _tx(client, headers, giro, "2026-03-05", "-150.00", versicherung)
    budget = _budget(client, headers, "2026-03-01")
    assert budget["available"] == "850.00"
    assert budget["fixed_total"] == "150.00" and budget["variable_spent"] == "0.00"


def test_f4_mehrzahlung_auf_kreditrate_verschwindet_nicht(client, headers, giro, gehalt, maerz):
    loan = _loan(client, headers, balance_date="2026-03-01", first_due_date="2026-03-31", term_months=None,
                 installment_amount="100.00", payment_account_id=giro["id"])
    _pay(client, headers, loan, "2026-03-31", "250.00")
    assert _budget(client, headers, "2026-03-01")["available"] == "750.00"


def test_f5_kreditzinsen_zaehlen_nicht_zusaetzlich_als_fixkost(client, headers, giro, gehalt, maerz):
    zinsen = next(c for c in client.get("/categories", headers=headers).json() if c["system_key"] == "loan_interest")
    loan = _loan(client, headers, annual_interest_rate="12", balance_date="2026-03-01",
                 first_due_date="2026-03-31", term_months=None, installment_amount="100.00",
                 payment_account_id=giro["id"])
    client.post("/fixed-costs", json={"name": "Dispozins", "amount": "50.00", "due_day": 28,
                                      "category_id": zinsen["id"]}, headers=headers)
    payment = _pay(client, headers, loan, "2026-03-31", "100.00")
    assert payment["interest"] == "10.00"
    budget = _budget(client, headers, "2026-03-01")
    dispo = next(i for i in budget["items"] if i["kind"] == "fixed")
    assert dispo["status"] != "paid"
    assert (budget["fixed_paid"], budget["variable_spent"], budget["available"]) == ("100.00", "0.00", "850.00")


def test_f3_f4_rate_im_folgemonat_bezahlt(client, headers, giro, gehalt, maerz):
    loan = _loan(client, headers, balance_date="2026-02-01", first_due_date="2026-02-28", term_months=None,
                 installment_amount="100.00", payment_account_id=giro["id"])
    _pay(client, headers, loan, "2026-03-01", "100.00")  # Februarrate
    maerz_budget = _budget(client, headers, "2026-03-01")
    assert maerz_budget["available"] == "800.00"  # 1000 − 100 gezahlt − 100 offene Märzrate
    februar = _budget(client, headers, "2026-02-01")
    assert next(i for i in februar["items"] if i["kind"] == "loan")["status"] == "paid"


# --- F7: Importidentität in der API -----------------------------------------------------------


def test_f7_bankbestaetigte_manuelle_buchung_meldet_importidentitaet(client, headers, profile, giro):
    tx = _tx(client, headers, giro, "2026-01-02", "-10.00", description="manuell")
    assert tx["import_linked"] is False and tx["loan_payment_id"] is None
    batch = upload(client, headers, profile, csv_file(("02.01.2026", "-10,00", "Kauf")))
    resolve(client, headers, batch, action="duplicate", decision="ambiguous")
    assert commit(client, headers, batch).status_code == 200
    got = client.get(f"/transactions/{tx['id']}", headers=headers).json()
    assert got["source"] == "manual" and got["import_linked"] is True
    listed = next(t for t in client.get("/transactions", headers=headers).json()["items"] if t["id"] == tx["id"])
    assert listed["import_linked"] is True
    assert client.delete(f"/transactions/{tx['id']}", headers=headers).status_code == 409
    assert client.post(f"/transactions/{tx['id']}/exclude", json={"reason": "doppelt"},
                       headers=headers).status_code == 200


def test_f7_kreditzahlung_meldet_ihre_zahlung(client, headers, giro):
    loan = _private(client, headers, giro)
    payment = _pay(client, headers, loan, "2026-02-01", "100.00")
    tx = client.get(f"/transactions/{payment['payment_transaction_id']}", headers=headers).json()
    assert tx["loan_payment_id"] == payment["id"]


# --- F12: Importpfade relativ zum Importordner ------------------------------------------------


def test_f12_dateipfad_folgt_einem_neuen_importordner(client, headers, profile, giro, session, import_dir,
                                                       tmp_path, monkeypatch):
    from app.config import get_settings
    from app.services import import_jobs

    batch = upload(client, headers, profile, csv_file(("02.01.2026", "-1,00", "X")), process=False)
    stored = session.get(ImportBatch, batch["id"]).stored_path
    assert not Path(stored).is_absolute()
    old_file = import_jobs.stored_file(stored)
    # Restore an einen anderen Ort: Dateien liegen unter dem neuen Importordner
    new_root = tmp_path / "neu"
    (new_root / old_file.parent.name).mkdir(parents=True)
    old_file.rename(new_root / old_file.parent.name / old_file.name)
    monkeypatch.setattr(get_settings(), "import_dir", new_root)
    assert import_jobs.stored_file(stored).read_bytes().startswith(b"Auftragskonto")


def test_f12_alte_absolute_pfade_werden_auf_den_aktuellen_ordner_umgelenkt(import_dir):
    from app.services import import_jobs

    (import_dir / "archive").mkdir(parents=True, exist_ok=True)
    (import_dir / "archive" / "7_datei.csv").write_text("x")
    old = "/alter/server/imports/archive/7_datei.csv"
    assert import_jobs.stored_file(old) == import_dir / "archive" / "7_datei.csv"


# --- F15: Name ändern lässt Konditionen unverändert -------------------------------------------


def test_f15_unveraenderte_laufzeit_im_patch_aendert_den_plan_nicht(client, headers, giro):
    loan = _loan(client, headers, loan_type="installment", term_months=10, annual_interest_rate="0",
                 payment_account_id=giro["id"])
    _pay(client, headers, loan, "2026-01-31", "100.00")
    before = _get_loan(client, headers, loan)
    assert before["open_installments"] == 9
    response = client.patch(f"/loans/{loan['id']}", json={"name": "Neu", "term_months": 10,
                                                          "fixed_principal": before["fixed_principal"]},
                            headers=headers)
    assert response.status_code == 200, response.text
    after = response.json()
    assert after["open_installments"] == 9 and after["final_due_date"] == before["final_due_date"]


# --- F16: KI übernimmt keine inzwischen ungültige Kategorie -----------------------------------


@pytest.mark.parametrize("change", [{"active": False}, {"type": "income"}])
def test_f16_ki_vorschlag_mit_inzwischen_geaenderter_kategorie_wird_verworfen(
    client, headers, session, giro, monkeypatch, change
):
    tanken = _cat(client, headers, "Tanken-Test")
    tx = _tx(client, headers, giro, "2026-11-02", "-54.23", description="Kartenzahlung", counterparty="ARAL")

    def chat(messages):
        response = client.patch(f"/categories/{tanken['id']}", json=change, headers=headers)
        assert response.status_code == 200, response.text
        return json.dumps({"kategorie_id": tanken["id"], "sicherheit": "hoch", "begruendung": "Tankstelle"})

    monkeypatch.setattr(ai_review, "chat", chat)
    ai_review.review_one(session, tx["id"])
    got = client.get(f"/transactions/{tx['id']}", headers=headers).json()
    assert got["category_id"] is None and got["review_status"] == "needs_review"


def test_f16_alles_bestaetigen_ueberspringt_deaktivierte_kategorie(client, headers, session, giro, monkeypatch):
    tanken = _cat(client, headers, "Tanken-Test")
    tx = _tx(client, headers, giro, "2026-11-02", "-54.23", description="Kartenzahlung", counterparty="ARAL")
    answer = json.dumps({"kategorie_id": tanken["id"], "sicherheit": "hoch", "begruendung": "x"})
    monkeypatch.setattr(ai_review, "chat", lambda m: answer)
    ai_review.review_one(session, tx["id"])
    assert client.get(f"/transactions/{tx['id']}", headers=headers).json()["review_status"] == "auto_categorized"
    client.patch(f"/categories/{tanken['id']}", json={"active": False}, headers=headers)
    result = client.post("/review/confirm-all", headers=headers).json()
    assert (result["confirmed"], result["skipped"]) == (0, 1)


# --- S1: Belastung nach späterer Zahlung löschen ----------------------------------------------


def test_s1_belastung_mit_spaeterer_zahlung_laesst_sich_nicht_einfach_loeschen(client, headers, giro):
    loan = _private(client, headers, giro)
    charge = _charge(client, headers, loan, "2026-01-10", "100.00")
    _pay(client, headers, loan, "2026-01-20", "1100.00")
    response = client.delete(f"/loans/{loan['id']}/charges/{charge['id']}", headers=headers)
    assert response.status_code == 409 and response.json()["error"]["code"] == "charge_has_later_payments"
    assert _get_loan(client, headers, loan)["remaining_debt"] == "0.00"


# --- S2: Zinsen abschnittsweise, Restschuld am Zahlungstag ------------------------------------


def test_s2_zinsen_folgen_den_datierten_saldoaenderungen(client, headers, giro):
    loan = _private(client, headers, giro, annual_interest_rate="36.5")
    _charge(client, headers, loan, "2026-01-06", "1000.00")
    payment = _pay(client, headers, loan, "2026-01-11", "100.00")
    assert payment["interest"] == "15.00"  # 5 Tage × 1.000 € + 5 Tage × 2.000 € bei 0,1 % je Tag


def test_s2_spaetere_belastung_erlaubt_keine_fruehere_ueberzahlung(client, headers, giro):
    loan = _private(client, headers, giro)
    _charge(client, headers, loan, "2026-03-01", "100.00")
    response = client.post(f"/loans/{loan['id']}/payments", json={"booking_date": "2026-02-01",
                                                                  "amount": "1100.00"}, headers=headers)
    assert response.status_code == 422 and response.json()["error"]["code"] == "principal_exceeds_debt"


# --- S3: Storno nach Ratenpause ---------------------------------------------------------------


def test_s3_storno_vor_einer_spaeteren_ratenpause_wird_abgelehnt(client, headers, giro):
    loan = _loan(client, headers, term_months=10, payment_account_id=giro["id"])
    payment = _pay(client, headers, loan, "2026-01-31", "100.00")
    assert client.post(f"/loans/{loan['id']}/schedule/2/skip", headers=headers).status_code == 200
    response = client.delete(f"/loans/{loan['id']}/payments/{payment['id']}", headers=headers)
    assert response.status_code == 409 and response.json()["error"]["code"] == "payment_followed_by_skip"
    plan = client.get(f"/loans/{loan['id']}/schedule", headers=headers).json()
    assert (plan[0]["seq"], plan[0]["status"]) == (1, "paid")


# --- S4: Historischer Kreditbericht -----------------------------------------------------------


def test_s4_kreditbericht_bezieht_restschuld_auf_den_stichtag(client, headers, giro):
    loan = _private(client, headers, giro)
    _pay(client, headers, loan, "2026-02-28", "100.00")
    report = client.get("/reports/loans", params={"until": "2026-01-31", "months": 1}, headers=headers).json()
    item = report["loans"][0]
    assert item["remaining_debt"] == "1000.00"
    assert item["remaining_by_month"][0]["remaining_debt"] == "1000.00"
    assert "current_as_of" in report


# --- S5: Tilgungsfortschritt aus tatsächlichen Zahlungen --------------------------------------


def test_s5_kredit_liefert_tatsaechlich_getilgten_betrag(client, headers, giro):
    loan = _loan(client, headers, annual_interest_rate="12", term_months=None, installment_amount="100.00",
                 payment_account_id=giro["id"])
    payment = _pay(client, headers, loan, "2026-01-31", "250.00")
    assert payment["principal"] == "240.00"
    got = _get_loan(client, headers, loan)
    assert (got["principal_repaid"], got["remaining_debt"]) == ("240.00", "760.00")


# --- S8: Kapitalisierte Zinsen getrennt von gezahlten -----------------------------------------


def test_s8_kreditbericht_trennt_gezahlte_und_belastete_zinsen(client, headers, giro):
    loan = _private(client, headers, giro, annual_interest_rate="2")
    client.post(f"/loans/{loan['id']}/charges", json={"booking_date": "2026-12-31", "amount": "20.00",
                                                      "charge_type": "interest"}, headers=headers)
    report = client.get("/reports/loans", params={"until": "2027-01-15", "months": 1}, headers=headers).json()
    assert report["loans"][0]["interest_paid_by_year"] == [
        {"year": 2026, "interest": "20.00", "paid": "0.00", "charged": "20.00"}
    ]


# --- S7: Filter für noch nicht bestätigte Buchungen -------------------------------------------


def test_s7_filter_unbestaetigt_enthaelt_automatische_vorschlaege(client, headers, giro):
    tanken = _cat(client, headers, "Tanken-Test")
    rule = client.post("/mapping-rules", json={"name": "Aral", "pattern": "ARAL", "target_category_id": tanken["id"]},
                       headers=headers)
    assert rule.status_code == 201, rule.text
    auto = _tx(client, headers, giro, "2026-11-02", "-54.23", description="Kartenzahlung", counterparty="ARAL")
    client.post("/mapping-rules/apply", params={"dry_run": False}, headers=headers)
    assert client.get(f"/transactions/{auto['id']}", headers=headers).json()["review_status"] == "auto_categorized"
    confirmed = _tx(client, headers, giro, "2026-11-03", "-5.00", tanken)
    ids = [t["id"] for t in client.get("/transactions", params={"unconfirmed": True}, headers=headers).json()["items"]]
    assert auto["id"] in ids and confirmed["id"] not in ids
