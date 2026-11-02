"""Berichte und Export: Kernfälle (Erstattung, Umbuchung, Kreditzinsen, Unkategorisiert, Hierarchie)."""

import csv
import io

import pytest


@pytest.fixture
def setup(client, headers, make_institution, make_account):
    bank = make_institution("Sparkasse")
    giro = make_account("Giro", institution_id=bank["id"], opening_balance="1000.00", opening_balance_date="2026-01-01")
    karte = make_account("Karte", type="credit_card", opening_balance="0.00", opening_balance_date="2026-01-01")

    def cat(name, type_="expense", parent=None):
        payload = {"name": name, "type": type_, **({"parent_id": parent["id"]} if parent else {})}
        return client.post("/categories", json=payload, headers=headers).json()

    def tx(account, day, amount, category=None, **extra):
        payload = {"account_id": account["id"], "booking_date": day, "amount": amount, "description": extra.pop("description", "Test"),
                   **({"category_id": category["id"]} if category else {}), **extra}
        response = client.post("/transactions", json=payload, headers=headers)
        assert response.status_code == 201, response.text
        return response.json()

    einkauf = cat("Einkauf-Test")
    kleidung = cat("Kleidung-Test", parent=einkauf)
    lohn = cat("Lohn-Test", "income")
    return {"giro": giro, "karte": karte, "bank": bank, "einkauf": einkauf, "kleidung": kleidung,
            "lohn": lohn, "tx": tx, "cat": cat}


def test_zusammenfassung(client, headers, setup):
    s = setup
    s["tx"](s["giro"], "2026-01-05", "2000.00", s["lohn"])
    s["tx"](s["karte"], "2026-01-10", "-100.00", s["kleidung"])
    s["tx"](s["karte"], "2026-01-20", "30.00", s["kleidung"])  # Erstattung
    s["tx"](s["giro"], "2026-01-25", "-15.00")  # unkategorisiert
    client.post("/transfers", json={"from_account_id": s["giro"]["id"], "to_account_id": s["karte"]["id"],
                                    "booking_date": "2026-01-28", "amount": "70.00"}, headers=headers)
    s["tx"](s["giro"], "2026-02-03", "-50.00", s["einkauf"])

    r = client.get("/reports/summary", params={"date_from": "2026-01-01", "date_to": "2026-01-31"},
                   headers=headers).json()
    m = r["movements"]
    # Einnahmen 2000; Ausgaben 100 − 30 = 70; unkategorisiert 15; Umbuchung zählt nicht
    assert (m["income"], m["expenses"], m["uncategorized_out"], m["net"]) == ("2000.00", "70.00", "15.00", "1915.00")
    assert (m["cash_in"], m["cash_out"]) == ("2030.00", "115.00")
    balances = {a["name"]: a["balance"] for a in r["accounts"]}
    assert balances == {"Giro": "2915.00", "Karte": "0.00"}  # 1000 + 2000 − 15 − 70; −100 + 30 + 70
    assert r["net_worth"] == "2915.00"
    assert [x["month"] for x in r["months"]] == ["2026-01-01"]
    # Spätere Buchung (Februar) nicht im Januar-Saldo
    feb = client.get("/reports/summary", params={"date_from": "2026-02-01", "date_to": "2026-02-28"},
                     headers=headers).json()
    assert feb["movements"]["expenses"] == "50.00"


def test_kategorien_mit_hierarchie_und_anteilen(client, headers, setup):
    s = setup
    s["tx"](s["giro"], "2026-01-10", "-100.00", s["kleidung"])
    s["tx"](s["giro"], "2026-01-11", "30.00", s["kleidung"])
    s["tx"](s["giro"], "2026-01-12", "-50.00", s["einkauf"])
    sonst = s["cat"]("Rückerstattung-Test")
    s["tx"](s["giro"], "2026-01-13", "20.00", sonst)  # nur Erstattung -> Netto negativ
    s["tx"](s["giro"], "2026-01-14", "-5.00")
    r = client.get("/reports/categories", params={"date_from": "2026-01-01", "date_to": "2026-01-31"},
                   headers=headers).json()
    items = {i["name"]: i for i in r["items"]}
    einkauf, kleidung, erst = items["Einkauf-Test"], items["Kleidung-Test"], items["Rückerstattung-Test"]
    assert (einkauf["gross"], einkauf["refunds"], einkauf["net"], einkauf["own_net"]) == ("150.00", "30.00", "120.00", "50.00")
    assert (kleidung["net"], kleidung["parent_id"]) == ("70.00", s["einkauf"]["id"])
    assert erst["net"] == "-20.00" and erst["share"] is None
    assert einkauf["share"] == "1.0000"  # einzige positive Hauptkategorie
    assert r["total_net"] == "100.00" and r["uncategorized"] == "5.00"


def test_kreditzinsen_sind_ausgabe_tilgung_nicht(client, headers, setup):
    s = setup
    loan = client.post("/loans", json={"name": "Kredit", "loan_type": "annuity", "lender_name": "Bank",
                                       "annual_interest_rate": "5", "current_balance": "10000.00",
                                       "balance_date": "2026-01-01", "first_due_date": "2026-01-31",
                                       "term_months": 48, "payment_account_id": s["giro"]["id"]},
                       headers=headers).json()
    client.post(f"/loans/{loan['id']}/payments", json={"booking_date": "2026-01-31", "amount": "230.30"},
                headers=headers)
    r = client.get("/reports/summary", params={"date_from": "2026-01-01", "date_to": "2026-01-31"},
                   headers=headers).json()
    assert r["movements"]["expenses"] == "41.67"  # nur der Zinsanteil
    assert r["liabilities"] == "-9811.37"
    assert r["net_worth"] == "-9041.67"  # Giro 769,70 + Karte 0 − Restschuld 9811,37
    loans = client.get("/reports/loans", params={"until": "2026-02-15", "months": 2}, headers=headers).json()
    item = loans["loans"][0]
    assert [x["remaining_debt"] for x in item["remaining_by_month"]] == ["9811.37", "9811.37"]
    assert item["interest_paid_by_year"] == [{"year": 2026, "interest": "41.67"}]
    assert loans["monthly_burden"] == "230.30"


def test_trends_lueckenlos(client, headers, setup):
    s = setup
    s["tx"](s["giro"], "2026-01-31", "-10.00", s["einkauf"])
    s["tx"](s["giro"], "2026-03-01", "-20.00", s["kleidung"])
    r = client.get("/reports/trends", params={"months": 4, "until": "2026-04-10"}, headers=headers).json()
    assert [(m["month"], m["expenses"], m["coverage"]) for m in r["months"]] == [
        ("2026-01-01", "10.00", "unknown"), ("2026-02-01", "0.00", "unknown"),
        ("2026-03-01", "20.00", "unknown"), ("2026-04-01", "0.00", "unknown"),
    ]
    nur_kleidung = client.get("/reports/trends", params={"months": 4, "until": "2026-04-10",
                                                         "category_id": s["einkauf"]["id"]}, headers=headers).json()
    assert [m["expenses"] for m in nur_kleidung["months"]] == ["10.00", "0.00", "20.00", "0.00"]


def test_csv_export_alle_treffer_splits_und_formelschutz(client, headers, setup):
    s = setup
    for i in range(3):
        s["tx"](s["giro"], f"2026-01-0{i + 1}", "-1.00", description=f"Posten {i}")
    s["tx"](s["giro"], "2026-01-09", "-1234.50", description="=HYPERLINK(\"http://x\")", counterparty="@böse")
    s["tx"](s["giro"], "2026-01-10", "-100.00",
            splits=[{"amount": "-60.00", "category_id": s["einkauf"]["id"]}, {"amount": "-40.00"}])
    response = client.get("/export/transactions.csv", params={"account_ids": [s["giro"]["id"]]}, headers=headers)
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    text = response.content.decode("utf-8")
    assert text.startswith("﻿")
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=";"))
    header, body = rows[0], rows[1:]
    assert header[0] == "Buchungsdatum" and len(body) == 3 + 1 + 2  # Splits als eigene Zeilen
    split_rows = [r for r in body if r[header.index("Teilzeile")]]
    assert [r[header.index("Betrag")] for r in split_rows] == ["-60,00", "-40,00"]
    evil = next(r for r in body if "HYPERLINK" in r[header.index("Verwendungszweck")])
    assert evil[header.index("Verwendungszweck")].startswith("'=")
    assert evil[header.index("Gegenpartei")] == "'@böse"
    assert evil[header.index("Betrag")] == "-1234,50"  # Zahl bleibt Zahl
    assert evil[header.index("Buchungsdatum")] == "09.01.2026"


def test_pdf_bericht_und_tilgungsplan(client, headers, setup):
    s = setup
    lang = s["cat"](("Ein sehr langer Kategoriename mit Umlauten äöüß, der umbrechen muss " * 2)[:100])
    for day in range(1, 29):
        s["tx"](s["giro"], f"2026-01-{day:02d}", "-1.00", lang)
    response = client.get("/export/report.pdf", params={"date_from": "2026-01-01", "date_to": "2026-01-31"},
                          headers=headers)
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    loan = client.post("/loans", json={"name": "Kredit", "loan_type": "annuity", "lender_name": "Bank",
                                       "annual_interest_rate": "5", "current_balance": "10000.00",
                                       "balance_date": "2026-01-01", "term_months": 120}, headers=headers).json()
    pdf = client.get(f"/export/loans/{loan['id']}/schedule.pdf", headers=headers)
    assert pdf.content.startswith(b"%PDF") and pdf.content.count(b"/Type /Page") >= 3  # mehrseitig
    schedule = client.get(f"/export/loans/{loan['id']}/schedule.csv", headers=headers).content.decode()
    assert len(schedule.strip().splitlines()) == 121


def test_zeitraum_validierung_und_isolation(client, headers, setup, other_user):
    response = client.get("/reports/summary", params={"date_from": "2026-02-01", "date_to": "2026-01-01"},
                          headers=headers)
    assert response.json()["error"]["code"] == "invalid_period"
    setup["tx"](setup["giro"], "2026-01-05", "-10.00", setup["einkauf"])
    fremd = client.get("/reports/summary", params={"date_from": "2026-01-01", "date_to": "2026-01-31"},
                       headers=other_user["headers"]).json()
    assert fremd["accounts"] == [] and fremd["movements"]["expenses"] == "0.00"
    response = client.get("/reports/trends", params={"category_id": setup["einkauf"]["id"]},
                          headers=other_user["headers"])
    assert response.status_code == 404


def test_geldfluesse_je_buchung_und_anteilsbasis(client, headers, setup):
    s = setup
    andere = s["cat"]("Andere-Test")
    # Eine Kartenzahlung −100: −130 Einkauf und +30 Gutschrift in einer Buchung
    s["tx"](s["giro"], "2026-01-10", "-100.00",
            splits=[{"amount": "-130.00", "category_id": s["einkauf"]["id"]},
                    {"amount": "30.00", "category_id": s["einkauf"]["id"]}])
    s["tx"](s["giro"], "2026-01-11", "40.00", andere)  # nur Erstattung: Netto −40
    r = client.get("/reports/summary", params={"date_from": "2026-01-01", "date_to": "2026-01-31"},
                   headers=headers).json()
    assert (r["movements"]["cash_in"], r["movements"]["cash_out"]) == ("40.00", "100.00")
    c = client.get("/reports/categories", params={"date_from": "2026-01-01", "date_to": "2026-01-31"},
                   headers=headers).json()
    assert (c["total_net"], c["share_basis"]) == ("60.00", "100.00")  # 100 − 40; Basis nur positive


def test_until_mitten_im_monat(client, headers, setup):
    s = setup
    s["tx"](s["giro"], "2026-03-10", "-10.00", s["einkauf"])
    s["tx"](s["giro"], "2026-03-20", "-20.00", s["einkauf"])
    r = client.get("/reports/trends", params={"months": 1, "until": "2026-03-15"}, headers=headers).json()
    assert r["months"][0]["expenses"] == "10.00"  # Buchung vom 20.03. liegt nach `until`


def test_kreditbericht_zaehlt_belastete_zinsen(client, headers, setup):
    loan = client.post("/loans", json={"name": "Privat", "loan_type": "private", "lender_name": "Oma",
                                       "annual_interest_rate": "2", "current_balance": "1000.00",
                                       "balance_date": "2026-01-01"}, headers=headers).json()
    client.post(f"/loans/{loan['id']}/charges", json={"booking_date": "2026-12-31", "amount": "20.00",
                                                      "charge_type": "interest"}, headers=headers)
    r = client.get("/reports/loans", params={"until": "2027-01-15", "months": 1}, headers=headers).json()
    item = r["loans"][0]
    assert item["interest_paid_by_year"] == [{"year": 2026, "interest": "20.00"}]
    assert item["remaining_by_month"] == [{"month_end": "2027-01-15", "remaining_debt": "1020.00"}]


def test_csv_kategoriefilter_exportiert_nur_passende_splitzeilen(client, headers, setup):
    s = setup
    andere = s["cat"]("Andere-Test")
    s["tx"](s["giro"], "2026-01-10", "-100.00",
            splits=[{"amount": "-60.00", "category_id": s["einkauf"]["id"]},
                    {"amount": "-25.00", "category_id": andere["id"]},
                    {"amount": "-15.00", "kind": "transfer"}])
    text = client.get("/export/transactions.csv", params={"category_id": s["einkauf"]["id"]},
                      headers=headers).content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    header, body = rows[0], rows[1:]
    assert [r[header.index("Betrag")] for r in body] == ["-60,00"]
    assert body[0][header.index("Prüfstatus")] == "bestätigt"
    assert body[0][header.index("Quelle")] == "manuell"
