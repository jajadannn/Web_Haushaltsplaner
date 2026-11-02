"""Berichte und Export: Szenario-Tests mit von Hand durchgerechneten Beträgen.

Ergänzt `test_reports.py` (Kernfälle). Jeder Test baut sein kleines Szenario selbst auf; die
erwarteten Beträge stehen als exakte Dezimalstrings im Test, die Rechnung als Kommentar daneben.

Regeln (Docstring von `app/services/reports.py`):
- Umbuchungen (auch Kredit-Tilgungen) sind weder Einnahme noch Ausgabe; Kreditzinsen schon.
- Erstattungen werden in ihrer Kategorie verrechnet (−100 und +30 → 70 Nettoausgabe).
- Unkategorisierte Beträge erscheinen gesondert, ausgeschlossene Buchungen zählen nicht,
  archivierte Konten bleiben enthalten.
- Salden gelten am Ende des Stichtags; vor dem Anfangssaldo-Stichtag gibt es keinen Saldo (null).

Das Standardkonto aus `make_account` ist ein Girokonto mit 1000.00 zu Beginn von 2026-01-01.
Kategorien legt jeder Test selbst an (Namen mit Suffix `-T`); auf die Standardkategorien
verlässt sich kein Test, fest sind nur die System-Schlüssel `loan_interest`/`loan_fees`.
"""

import base64
import csv
import io
import re
import zlib
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.models import Transaction
from app.services.export import BATCH_SIZE

# --- Hilfen ---------------------------------------------------------------------------


def _kategorie(client, headers, name, type_="expense", parent=None):
    payload = {"name": name, "type": type_, **({"parent_id": parent["id"]} if parent else {})}
    response = client.post("/categories", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _buche(client, headers, konto, tag, betrag, kategorie=None, **extra):
    """Legt eine Buchung an, die gelingen muss, und gibt sie als JSON zurück."""
    payload = {
        "account_id": konto["id"],
        "booking_date": tag,
        "amount": betrag,
        "description": extra.pop("description", "Test"),
        **({"category_id": kategorie["id"]} if kategorie else {}),
        **extra,
    }
    response = client.post("/transactions", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _umbuche(client, headers, von, nach, betrag, tag):
    response = client.post(
        "/transfers",
        json={"from_account_id": von["id"], "to_account_id": nach["id"], "booking_date": tag, "amount": betrag},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _als_import_ausschliessen(client, headers, session, *buchungen, grund="Dublette"):
    """Macht Buchungen zu importierten (nur diese lassen sich ausschließen) und schließt sie aus."""
    for buchung in buchungen:
        session.get(Transaction, buchung["id"]).source = "import"
    session.commit()
    for buchung in buchungen:
        response = client.post(f"/transactions/{buchung['id']}/exclude", json={"reason": grund}, headers=headers)
        assert response.status_code == 200, response.text


def _bericht(client, headers, pfad, **params):
    response = client.get(pfad, params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _summary(client, headers, date_from, date_to):
    return _bericht(client, headers, "/reports/summary", date_from=date_from, date_to=date_to)


def _kategorien(client, headers, date_from, date_to, type_="expense"):
    return _bericht(client, headers, "/reports/categories", date_from=date_from, date_to=date_to, type=type_)


def _trends(client, headers, **params):
    return _bericht(client, headers, "/reports/trends", **params)["months"]


def _kreditbericht(client, headers, **params):
    return _bericht(client, headers, "/reports/loans", **params)


def _nach_name(bericht):
    """Kategorienbericht als {Name: Zeile}; Namen sind in den Szenarien eindeutig."""
    items = {i["name"]: i for i in bericht["items"]}
    assert len(items) == len(bericht["items"])
    return items


def _salden(bericht):
    return {a["name"]: a["balance"] for a in bericht["accounts"]}


def _fluesse(
    income="0.00", expenses="0.00", unc_in="0.00", unc_out="0.00", net="0.00", cash_in="0.00", cash_out="0.00"
):
    """Erwartete Einnahmen/Ausgaben-Zeile (`movements` bzw. Monat ohne `month`); Standard überall 0.00."""
    return {
        "income": income,
        "expenses": expenses,
        "uncategorized_in": unc_in,
        "uncategorized_out": unc_out,
        "net": net,
        "cash_in": cash_in,
        "cash_out": cash_out,
    }


def _monat(monat, income="0.00", expenses="0.00", unc_in="0.00", unc_out="0.00", net="0.00"):
    """Erwartete Zeile von `/reports/trends`."""
    return {
        "month": monat,
        "income": income,
        "expenses": expenses,
        "uncategorized_in": unc_in,
        "uncategorized_out": unc_out,
        "net": net,
        "coverage": "unknown",
    }


def _kredit(client, headers, **extra):
    """Annuitätendarlehen 10000.00 zu 5 % über 48 Monate (Rate 230.30), ab 2026-01-01."""
    payload = {
        "name": "Autokredit-T",
        "loan_type": "annuity",
        "lender_name": "Autobank",
        "annual_interest_rate": "5",
        "current_balance": "10000.00",
        "balance_date": "2026-01-01",
        "first_due_date": "2026-01-31",
        "term_months": 48,
        **extra,
    }
    response = client.post("/loans", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _privatkredit(client, headers, betrag, **extra):
    """Privatkredit ohne Zins und ohne Plan (nur freie Zahlungen)."""
    return _kredit(
        client, headers, loan_type="private", annual_interest_rate="0", current_balance=betrag,
        term_months=None, first_due_date=None, **extra,
    )


def _rate(client, headers, kredit_id, **payload):
    response = client.post(f"/loans/{kredit_id}/payments", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _csv(response):
    """(Kopfzeile, Zeilen als {Spalte: Wert}) – prüft BOM und gleiche Spaltenzahl in jeder Zeile."""
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"\xef\xbb\xbf")  # UTF-8 mit BOM
    text = response.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))
    header, body = rows[0], rows[1:]
    assert all(len(row) == len(header) for row in body), "Spaltenzahl weicht von der Kopfzeile ab"
    return header, [dict(zip(header, row, strict=True)) for row in body]


def _csv_zwecke(client, headers, **params):
    """Verwendungszwecke der exportierten Buchungen (Menge) bei den gegebenen Filtern."""
    _, rows = _csv(client.get("/export/transactions.csv", params=params, headers=headers))
    return {row["Verwendungszweck"] for row in rows}


def _dezimal(text):
    """CSV-Betrag mit Dezimalkomma als Decimal."""
    return Decimal(text.replace(",", "."))


def _pdf_entschuetzt(roh):
    """Löst PDF-Escapes (`\\(`, `\\)`, `\\\\` und Oktalcodes wie `\\344`) auf; Standardschrift = Windows-1252."""

    def ersetze(treffer):
        code = treffer.group(1)
        return bytes([int(code, 8)]) if code[:1].isdigit() else code

    return re.sub(rb"\\([0-7]{1,3}|.)", ersetze, roh).decode("cp1252", errors="replace")


def _pdf_seiten(daten):
    """Textstücke je Seite eines ReportLab-PDFs.

    ReportLab schreibt je Seite einen ASCII85+Flate-Inhaltsstrom; der Text steht darin als `(…) Tj`.
    """
    seiten = []
    for strom in re.finditer(rb"stream\r?\n(.*?)endstream", daten, re.S):
        roh = strom.group(1).strip()
        if roh.endswith(b"~>"):
            roh = base64.a85decode(roh[:-2])
        inhalt = zlib.decompress(roh)
        seiten.append([_pdf_entschuetzt(s) for s in re.findall(rb"\(((?:[^()\\]|\\.)*)\) Tj", inhalt)])
    assert len(seiten) == len(re.findall(rb"/Type\s*/Page(?![A-Za-z])", daten)), "ein Inhaltsstrom je Seite erwartet"
    return seiten


def _nach(texte, beschriftung):
    """Das Textstück, das im PDF direkt hinter der Beschriftung steht (z. B. der Betrag einer Zeile)."""
    return texte[texte.index(beschriftung) + 1]


# --- /reports/summary: Banken, Verbindlichkeiten, Stichtage ---------------------------------


def test_summary_summiert_je_bank_und_fuehrt_das_konto_ohne_bank_gesondert(
    client, headers, make_institution, make_account
):
    sparkasse = make_institution("Sparkasse-T")
    zweitbank = make_institution("Zweitbank-T")
    giro_a = make_account("Giro A", institution_id=sparkasse["id"])  # 1000.00 zu Beginn von 2026-01-01
    tagesgeld = make_account("Tagesgeld A", type="savings", institution_id=sparkasse["id"], opening_balance="2500.00")
    giro_b = make_account("Giro B", institution_id=zweitbank["id"], opening_balance="300.00")
    bargeld = make_account("Bargeld", type="cash", opening_balance="50.00")  # ohne Bank
    lohn = _kategorie(client, headers, "Lohn-T", "income")
    zinsen = _kategorie(client, headers, "Zinsen-T", "income")
    einkauf = _kategorie(client, headers, "Einkauf-T")
    _buche(client, headers, giro_a, "2026-01-10", "2000.00", lohn)
    _buche(client, headers, giro_a, "2026-01-12", "-120.00", einkauf)
    _buche(client, headers, tagesgeld, "2026-01-15", "30.00", zinsen)
    _buche(client, headers, giro_b, "2026-01-20", "-80.00", einkauf)
    _buche(client, headers, bargeld, "2026-01-25", "-20.00", einkauf)
    _umbuche(client, headers, giro_a, giro_b, "200.00", "2026-01-28")  # Umbuchung zwischen den Banken

    r = _summary(client, headers, "2026-01-01", "2026-01-31")
    assert _salden(r) == {
        "Giro A": "2680.00",  # 1000 + 2000 − 120 − 200
        "Tagesgeld A": "2530.00",  # 2500 + 30
        "Giro B": "420.00",  # 300 − 80 + 200
        "Bargeld": "30.00",  # 50 − 20
    }
    assert r["institutions"] == [
        {"institution_id": sparkasse["id"], "name": "Sparkasse-T", "balance": "5210.00"},  # 2680 + 2530
        {"institution_id": zweitbank["id"], "name": "Zweitbank-T", "balance": "420.00"},
        {"institution_id": None, "name": "Ohne Bank", "balance": "30.00"},  # nur das Bargeld
    ]
    assert next(a for a in r["accounts"] if a["name"] == "Bargeld")["institution_id"] is None
    assert (r["assets"], r["liabilities"], r["net_worth"]) == ("5660.00", "0.00", "5660.00")  # 5210 + 420 + 30
    # Einnahmen 2000 + 30; Ausgaben 120 + 80 + 20; die Umbuchung zählt nicht
    assert r["movements"] == _fluesse(
        income="2030.00", expenses="220.00", net="1810.00", cash_in="2030.00", cash_out="220.00"
    )
    # Probe: Anfangssalden 1000 + 2500 + 300 + 50 = 3850, dazu Netto 1810 = 5660


def test_summary_ueberzogenes_konto_und_kreditkarte_zaehlen_als_verbindlichkeit(
    client, headers, make_institution, make_account
):
    bank = make_institution("Sparkasse-T")
    giro = make_account("Giro", institution_id=bank["id"], opening_balance="200.00")
    make_account("Tagesgeld", type="savings", institution_id=bank["id"], opening_balance="1000.00")
    karte = make_account("Karte", type="credit_card", opening_balance="0.00")  # ohne Bank
    einkauf = _kategorie(client, headers, "Einkauf-T")
    _buche(client, headers, giro, "2026-01-10", "-500.00", einkauf)  # 200 − 500: überzogen
    _buche(client, headers, karte, "2026-01-15", "-150.00", einkauf)  # 0 − 150

    r = _summary(client, headers, "2026-01-01", "2026-01-31")
    assert _salden(r) == {"Giro": "-300.00", "Tagesgeld": "1000.00", "Karte": "-150.00"}
    assert r["assets"] == "1000.00"  # nur das Tagesgeld
    assert r["liabilities"] == "-450.00"  # −300 (überzogenes Giro) − 150 (Karte)
    assert r["net_worth"] == "550.00"  # 1000 − 450
    assert r["institutions"] == [
        {"institution_id": bank["id"], "name": "Sparkasse-T", "balance": "700.00"},  # −300 + 1000
        {"institution_id": None, "name": "Ohne Bank", "balance": "-150.00"},
    ]


def test_summary_kartenausgleich_verschiebt_zwischen_vermoegen_und_verbindlichkeiten(client, headers, make_account):
    giro = make_account("Giro")  # 1000.00
    karte = make_account("Karte", type="credit_card", opening_balance="0.00")
    einkauf = _kategorie(client, headers, "Einkauf-T")
    _buche(client, headers, karte, "2026-01-10", "-300.00", einkauf)  # Kartenkauf = Ausgabe
    _umbuche(client, headers, giro, karte, "300.00", "2026-01-20")  # Kartenausgleich = Umbuchung

    vorher = _summary(client, headers, "2026-01-01", "2026-01-15")
    assert _salden(vorher) == {"Giro": "1000.00", "Karte": "-300.00"}
    assert (vorher["assets"], vorher["liabilities"], vorher["net_worth"]) == ("1000.00", "-300.00", "700.00")

    nachher = _summary(client, headers, "2026-01-01", "2026-01-31")
    assert _salden(nachher) == {"Giro": "700.00", "Karte": "0.00"}  # 1000 − 300; −300 + 300
    assert (nachher["assets"], nachher["liabilities"], nachher["net_worth"]) == ("700.00", "0.00", "700.00")
    assert nachher["movements"]["expenses"] == "300.00"  # der Ausgleich ist keine zweite Ausgabe


def test_summary_kreditauszahlung_ist_keine_einnahme_und_aendert_das_nettovermoegen_nicht(
    client, headers, make_account
):
    giro = make_account("Giro")  # 1000.00
    # Neuer Kredit mit Auszahlung aufs Giro am 2026-01-01 (Umbuchung Kreditkonto → Giro)
    _kredit(client, headers, disbursement_account_id=giro["id"], payment_account_id=giro["id"])

    r = _summary(client, headers, "2026-01-01", "2026-01-31")
    assert _salden(r) == {"Giro": "11000.00", "Autokredit-T": "-10000.00"}  # 1000 + 10000; 0 − 10000
    assert r["assets"] == "11000.00"
    assert r["liabilities"] == "-10000.00"  # die Restschuld
    assert r["net_worth"] == "1000.00"  # 11000 − 10000: das Geld ist geliehen, nicht verdient
    assert r["movements"] == _fluesse()  # die Auszahlung ist weder Einnahme noch Zufluss


def test_summary_archiviertes_konto_bleibt_mit_saldo_und_bewegungen_enthalten(client, headers, make_account):
    make_account("Giro")  # 1000.00, bleibt aktiv
    alt = make_account("Altkonto", opening_balance="400.00")
    einkauf = _kategorie(client, headers, "Einkauf-T")
    _buche(client, headers, alt, "2026-01-20", "-150.00", einkauf)  # 400 − 150 = 250
    assert client.post(f"/accounts/{alt['id']}/archive", headers=headers).status_code == 200

    r = _summary(client, headers, "2026-01-01", "2026-01-31")
    konten = {a["name"]: a for a in r["accounts"]}
    assert (konten["Altkonto"]["archived"], konten["Altkonto"]["balance"]) == (True, "250.00")
    assert (konten["Giro"]["archived"], konten["Giro"]["balance"]) == (False, "1000.00")
    assert (r["assets"], r["net_worth"]) == ("1250.00", "1250.00")  # 1000 + 250
    assert r["movements"]["expenses"] == "150.00"  # auch die Buchung des archivierten Kontos zählt


def test_summary_history_incomplete_und_saldo_null_vor_dem_stichtag(client, headers, make_account):
    alt = make_account("Alt", opening_balance="100.00", opening_balance_date="2026-01-01")
    genau = make_account("Genau", opening_balance="200.00", opening_balance_date="2026-02-01")
    spaeter = make_account("Spaeter", opening_balance="500.00", opening_balance_date="2026-03-01")
    einkauf = _kategorie(client, headers, "Einkauf-T")
    _buche(client, headers, alt, "2026-02-10", "-10.00", einkauf)
    _buche(client, headers, genau, "2026-02-01", "-20.00", einkauf)  # am Stichtag selbst
    _buche(client, headers, spaeter, "2026-03-01", "-40.00", einkauf)  # am Stichtag selbst

    r = _summary(client, headers, "2026-02-01", "2026-03-31")
    assert {a["name"]: (a["balance"], a["history_incomplete"]) for a in r["accounts"]} == {
        "Alt": ("90.00", False),  # 100 − 10; Stichtag liegt vor date_from
        "Genau": ("180.00", False),  # 200 − 20; Stichtag == date_from zählt noch als vollständig
        "Spaeter": ("460.00", True),  # 500 − 40; Stichtag 2026-03-01 liegt nach date_from
    }
    assert r["assets"] == "730.00"  # 90 + 180 + 460
    assert r["movements"]["expenses"] == "70.00"  # 10 + 20 + 40: auch die Buchungen am Stichtag zählen

    # date_to einen Tag vor dem Stichtag: kein Saldo, das Konto fehlt in Vermögen und Bank-Summen
    r = _summary(client, headers, "2026-02-01", "2026-02-28")
    spaeter_zeile = next(a for a in r["accounts"] if a["name"] == "Spaeter")
    assert (spaeter_zeile["balance"], spaeter_zeile["history_incomplete"]) == (None, True)
    assert (r["assets"], r["liabilities"], r["net_worth"]) == ("270.00", "0.00", "270.00")  # 90 + 180
    assert r["institutions"] == [{"institution_id": None, "name": "Ohne Bank", "balance": "270.00"}]
    assert r["movements"]["expenses"] == "30.00"  # 10 + 20; die Buchung vom 2026-03-01 liegt außerhalb

    # date_to genau am Stichtag: der Saldo ist da und enthält die Buchung dieses Tages
    r = _summary(client, headers, "2026-02-01", "2026-03-01")
    assert _salden(r)["Spaeter"] == "460.00"  # 500 − 40
    assert r["assets"] == "730.00"  # 90 + 180 + 460


def test_summary_ausgeschlossene_buchungen_zaehlen_weder_im_saldo_noch_in_den_bewegungen(
    client, headers, session, make_account
):
    giro = make_account("Giro")  # 1000.00
    einkauf = _kategorie(client, headers, "Einkauf-T")
    lohn = _kategorie(client, headers, "Lohn-T", "income")
    doppelt = _buche(client, headers, giro, "2026-01-10", "-210.00", einkauf)
    _buche(client, headers, giro, "2026-01-11", "-50.00", einkauf)  # bleibt gültig
    gutschrift = _buche(client, headers, giro, "2026-01-12", "320.00", lohn)
    geteilt = _buche(
        client, headers, giro, "2026-01-13", "-100.00",
        splits=[{"amount": "-70.00", "category_id": einkauf["id"]}, {"amount": "-30.00"}],
    )

    vorher = _summary(client, headers, "2026-01-01", "2026-01-31")
    assert _salden(vorher) == {"Giro": "960.00"}  # 1000 − 210 − 50 + 320 − 100
    # Einnahmen 320; Ausgaben 210 + 50 + 70; unkategorisiert 30; Netto 320 − 330 − 30; ausgehend 210 + 50 + 100
    assert vorher["movements"] == _fluesse(
        income="320.00", expenses="330.00", unc_out="30.00", net="-40.00", cash_in="320.00", cash_out="360.00"
    )

    ausgeschlossen = (doppelt, gutschrift, geteilt)
    _als_import_ausschliessen(client, headers, session, *ausgeschlossen)
    nachher = _summary(client, headers, "2026-01-01", "2026-01-31")
    assert _salden(nachher) == {"Giro": "950.00"}  # 1000 − 50: nur die gültige Buchung bleibt
    nur_eine = _fluesse(expenses="50.00", net="-50.00", cash_out="50.00")
    assert nachher["movements"] == nur_eine
    assert nachher["months"] == [{"month": "2026-01-01", **nur_eine}]
    # Auch die Kategorienauswertung sieht nur die verbleibende Buchung
    kategorien = _kategorien(client, headers, "2026-01-01", "2026-01-31")
    assert [(i["name"], i["net"]) for i in kategorien["items"]] == [("Einkauf-T", "50.00")]
    assert (kategorien["total_net"], kategorien["uncategorized"]) == ("50.00", "0.00")  # auch die 30.00 sind weg
    assert _kategorien(client, headers, "2026-01-01", "2026-01-31", "income")["items"] == []

    # Wieder eingeschlossen gelten die Ausgangszahlen erneut
    for buchung in ausgeschlossen:
        assert client.post(f"/transactions/{buchung['id']}/include", headers=headers).status_code == 200
    assert _summary(client, headers, "2026-01-01", "2026-01-31") == vorher


def test_summary_monate_ueber_drei_monate_mit_monatsletztem_und_monatserstem(client, headers, make_account):
    giro = make_account("Giro", opening_balance="1000.00", opening_balance_date="2025-12-01")
    einkauf = _kategorie(client, headers, "Einkauf-T")
    lohn = _kategorie(client, headers, "Lohn-T", "income")
    _buche(client, headers, giro, "2025-12-31", "-999.00", einkauf)  # vor dem Zeitraum
    _buche(client, headers, giro, "2026-01-01", "-10.00", einkauf)  # Monatserster Januar
    _buche(client, headers, giro, "2026-01-31", "-20.00", einkauf)  # Monatsletzter Januar
    _buche(client, headers, giro, "2026-02-01", "-30.00", einkauf)  # Monatserster Februar
    _buche(client, headers, giro, "2026-02-01", "-3.00")  # unkategorisiert
    _buche(client, headers, giro, "2026-02-28", "1000.00", lohn)  # Monatsletzter Februar
    _buche(client, headers, giro, "2026-03-01", "-40.00", einkauf)  # Monatserster März
    _buche(client, headers, giro, "2026-03-31", "-50.00", einkauf)  # Monatsletzter März
    _buche(client, headers, giro, "2026-03-31", "5.00")  # unkategorisiert
    _buche(client, headers, giro, "2026-04-01", "-888.00", einkauf)  # nach dem Zeitraum

    r = _summary(client, headers, "2026-01-01", "2026-03-31")
    assert r["months"] == [
        # Januar: 10 + 20 Ausgaben
        {"month": "2026-01-01", **_fluesse(expenses="30.00", net="-30.00", cash_out="30.00")},
        # Februar: Einnahmen 1000, Ausgaben 30, unkategorisiert 3 → Netto 1000 − 30 − 3
        {"month": "2026-02-01", **_fluesse(
            income="1000.00", expenses="30.00", unc_out="3.00", net="967.00", cash_in="1000.00", cash_out="33.00")},
        # März: Ausgaben 40 + 50, unkategorisierter Zufluss 5 → Netto −90 + 5
        {"month": "2026-03-01", **_fluesse(
            expenses="90.00", unc_in="5.00", net="-85.00", cash_in="5.00", cash_out="90.00")},
    ]
    # Gesamt: Einnahmen 1000; Ausgaben 30 + 30 + 90; Netto −30 + 967 − 85 = 852
    assert r["movements"] == _fluesse(
        income="1000.00", expenses="150.00", unc_in="5.00", unc_out="3.00", net="852.00",
        cash_in="1005.00", cash_out="153.00",
    )
    # Saldo Ende März: 1000 − 999 + 852 = 853; die Buchung vom 1.4. fehlt noch
    assert _salden(r) == {"Giro": "853.00"}


def test_summary_angeschnittene_monate_zaehlen_nur_buchungen_im_zeitraum(client, headers, make_account):
    giro = make_account("Giro")  # 1000.00
    einkauf = _kategorie(client, headers, "Einkauf-T")
    _buche(client, headers, giro, "2026-01-14", "-1.00", einkauf)  # einen Tag vor dem Zeitraum
    _buche(client, headers, giro, "2026-01-15", "-2.00", einkauf)  # erster Tag (inklusive)
    _buche(client, headers, giro, "2026-01-31", "-4.00", einkauf)
    _buche(client, headers, giro, "2026-03-10", "-8.00", einkauf)  # letzter Tag (inklusive)
    _buche(client, headers, giro, "2026-03-11", "-16.00", einkauf)  # einen Tag nach dem Zeitraum

    r = _summary(client, headers, "2026-01-15", "2026-03-10")
    assert r["months"] == [
        {"month": "2026-01-01", **_fluesse(expenses="6.00", net="-6.00", cash_out="6.00")},  # 2 + 4
        {"month": "2026-02-01", **_fluesse()},  # keine Buchung, der Monat fehlt trotzdem nicht
        {"month": "2026-03-01", **_fluesse(expenses="8.00", net="-8.00", cash_out="8.00")},
    ]
    assert r["movements"] == _fluesse(expenses="14.00", net="-14.00", cash_out="14.00")  # 2 + 4 + 8
    # Der Saldo zählt ab dem Stichtag, nicht ab date_from: 1000 − 1 − 2 − 4 − 8 = 985
    assert _salden(r) == {"Giro": "985.00"}


def test_summary_monate_ueber_den_jahreswechsel(client, headers, make_account):
    giro = make_account("Giro", opening_balance="1000.00", opening_balance_date="2025-10-01")
    einkauf = _kategorie(client, headers, "Einkauf-T")
    _buche(client, headers, giro, "2025-11-14", "-100.00", einkauf)  # einen Tag vor dem Zeitraum
    _buche(client, headers, giro, "2025-11-30", "-1.00", einkauf)
    _buche(client, headers, giro, "2025-12-01", "-2.00", einkauf)
    _buche(client, headers, giro, "2025-12-31", "-4.00", einkauf)
    _buche(client, headers, giro, "2026-01-01", "-8.00", einkauf)
    _buche(client, headers, giro, "2026-01-10", "-16.00", einkauf)
    _buche(client, headers, giro, "2026-01-11", "-32.00", einkauf)  # einen Tag nach dem Zeitraum

    r = _summary(client, headers, "2025-11-15", "2026-01-10")
    assert [m["month"] for m in r["months"]] == ["2025-11-01", "2025-12-01", "2026-01-01"]
    assert [m["expenses"] for m in r["months"]] == ["1.00", "6.00", "24.00"]  # 1; 2 + 4; 8 + 16
    assert r["movements"]["expenses"] == "31.00"  # 1 + 6 + 24
    assert _salden(r) == {"Giro": "869.00"}  # 1000 − 100 − 31; die Buchung vom 11.1. fehlt noch


# --- Splits im Bericht ----------------------------------------------------------------------


def test_split_mit_umbuchungszeile_zaehlt_nur_die_regulaeren_zeilen_als_ausgabe(client, headers, make_account):
    giro = make_account("Giro")  # 1000.00
    sparkonto = make_account("Sparkonto", type="savings", opening_balance="0.00")
    a = _kategorie(client, headers, "Split-A")
    b = _kategorie(client, headers, "Split-B")
    _buche(
        client, headers, giro, "2026-01-15", "-100.00",
        splits=[
            {"amount": "-60.00", "category_id": a["id"]},
            {"amount": "-25.00", "category_id": b["id"]},
            {"amount": "-15.00", "kind": "transfer"},  # wandert aufs Sparkonto
        ],
    )
    _buche(client, headers, sparkonto, "2026-01-15", "15.00", kind="transfer")  # Gegenbuchung

    r = _summary(client, headers, "2026-01-01", "2026-01-31")
    assert _salden(r) == {"Giro": "900.00", "Sparkonto": "15.00"}  # 1000 − 100; 0 + 15
    assert r["net_worth"] == "915.00"  # die Umbuchungszeile verschiebt nur Geld zwischen den Konten
    # Ausgaben nur 60 + 25 = 85; die Transfer-Zeile zählt weder als Ausgabe noch als Abfluss
    assert r["movements"] == _fluesse(expenses="85.00", net="-85.00", cash_out="85.00")

    bericht = _kategorien(client, headers, "2026-01-01", "2026-01-31")
    items = _nach_name(bericht)
    assert set(items) == {"Split-A", "Split-B"}  # keine Zeile für die Transfer-Zeile
    assert (items["Split-A"]["net"], items["Split-A"]["share"]) == ("60.00", "0.7059")  # 60 / 85
    assert (items["Split-B"]["net"], items["Split-B"]["share"]) == ("25.00", "0.2941")  # 25 / 85
    assert (bericht["total_net"], bericht["uncategorized"]) == ("85.00", "0.00")

    assert _trends(client, headers, months=1, until="2026-01-31") == [
        _monat("2026-01-01", expenses="85.00", net="-85.00")
    ]


def test_split_mit_zeile_ohne_kategorie_erscheint_als_unkategorisiert(client, headers, make_account):
    giro = make_account("Giro")  # 1000.00
    a = _kategorie(client, headers, "Split-A")
    _buche(
        client, headers, giro, "2026-01-15", "-100.00",
        splits=[{"amount": "-60.00", "category_id": a["id"]}, {"amount": "-40.00"}],
    )

    r = _summary(client, headers, "2026-01-01", "2026-01-31")
    assert _salden(r) == {"Giro": "900.00"}  # 1000 − 100
    # 60 Ausgabe in Kategorie A, 40 unkategorisiert: Netto −100
    assert r["movements"] == _fluesse(expenses="60.00", unc_out="40.00", net="-100.00", cash_out="100.00")
    bericht = _kategorien(client, headers, "2026-01-01", "2026-01-31")
    assert [(i["name"], i["net"], i["share"]) for i in bericht["items"]] == [("Split-A", "60.00", "1.0000")]
    assert (bericht["total_net"], bericht["uncategorized"]) == ("60.00", "40.00")
    assert _trends(client, headers, months=1, until="2026-01-31") == [
        _monat("2026-01-01", expenses="60.00", unc_out="40.00", net="-100.00")
    ]


def test_split_mit_erstattungszeile_wird_in_der_kategorie_verrechnet(client, headers, make_account):
    giro = make_account("Giro")  # 1000.00
    haushalt = _kategorie(client, headers, "Haushalt-T")
    # Eine Bankbuchung −100: Kassenzettel mit 130 Einkauf und 30 Pfand-Erstattung
    _buche(
        client, headers, giro, "2026-01-15", "-100.00",
        splits=[
            {"amount": "-130.00", "category_id": haushalt["id"]},
            {"amount": "30.00", "category_id": haushalt["id"]},
        ],
    )
    bericht = _kategorien(client, headers, "2026-01-01", "2026-01-31")
    zeile = _nach_name(bericht)["Haushalt-T"]
    assert (zeile["gross"], zeile["refunds"], zeile["net"]) == ("130.00", "30.00", "100.00")  # 130 − 30
    assert (zeile["own_net"], zeile["share"]) == ("100.00", "1.0000")
    assert bericht["total_net"] == "100.00"


# --- /reports/categories --------------------------------------------------------------------


def test_kategorien_drei_ebenen_zaehlen_jede_buchung_je_ebene_genau_einmal(client, headers, make_account):
    giro = make_account("Giro")  # 1000.00
    mobil = _kategorie(client, headers, "Mobilität-T")
    auto = _kategorie(client, headers, "Auto-T", parent=mobil)
    tanken = _kategorie(client, headers, "Tanken-T", parent=auto)
    werkstatt = _kategorie(client, headers, "Werkstatt-T", parent=auto)
    wohnen = _kategorie(client, headers, "Wohnen-T")
    _buche(client, headers, giro, "2026-01-05", "-40.00", mobil)  # Oberkategorie direkt
    _buche(client, headers, giro, "2026-01-06", "-100.00", auto)  # Mittelkategorie direkt
    _buche(client, headers, giro, "2026-01-07", "-60.00", tanken)
    _buche(client, headers, giro, "2026-01-08", "-30.00", tanken)
    _buche(client, headers, giro, "2026-01-09", "10.00", tanken)  # Erstattung
    _buche(client, headers, giro, "2026-01-10", "-200.00", werkstatt)
    _buche(client, headers, giro, "2026-01-11", "-300.00", wohnen)

    bericht = _kategorien(client, headers, "2026-01-01", "2026-01-31")
    items = _nach_name(bericht)
    # (brutto, erstattet, netto, eigenes Netto, Anteil); Anteil = Netto / 720 (Summe der Hauptkategorien)
    assert {n: (i["gross"], i["refunds"], i["net"], i["own_net"], i["share"]) for n, i in items.items()} == {
        "Tanken-T": ("90.00", "10.00", "80.00", "80.00", "0.1111"),  # 60 + 30 brutto, 10 erstattet; 80 / 720
        "Werkstatt-T": ("200.00", "0.00", "200.00", "200.00", "0.2778"),  # 200 / 720
        "Auto-T": ("390.00", "10.00", "380.00", "100.00", "0.5278"),  # eigene 100 + 90 + 200; Netto 380 / 720
        "Mobilität-T": ("430.00", "10.00", "420.00", "40.00", "0.5833"),  # eigene 40 + 390; Netto 420 / 720
        "Wohnen-T": ("300.00", "0.00", "300.00", "300.00", "0.4167"),  # 300 / 720
    }
    assert (items["Mobilität-T"]["parent_id"], items["Mobilität-T"]["root_id"]) == (None, mobil["id"])
    assert (items["Auto-T"]["parent_id"], items["Auto-T"]["root_id"]) == (mobil["id"], mobil["id"])
    assert (items["Tanken-T"]["parent_id"], items["Tanken-T"]["root_id"]) == (auto["id"], mobil["id"])
    assert (items["Werkstatt-T"]["parent_id"], items["Werkstatt-T"]["root_id"]) == (auto["id"], mobil["id"])
    # Jede Buchung zählt je Ebene genau einmal: Gesamt nur über die Hauptkategorien (420 + 300) ...
    assert bericht["total_net"] == "720.00"
    # ... und die eigenen Anteile aller Ebenen ergeben dieselbe Summe (40 + 100 + 80 + 200 + 300)
    assert sum(Decimal(i["own_net"]) for i in items.values()) == Decimal("720.00")
    assert _summary(client, headers, "2026-01-01", "2026-01-31")["movements"]["expenses"] == "720.00"


def test_kategorien_erstattungen_ueber_den_ausgaben_ergeben_negatives_netto_ohne_anteil(client, headers, make_account):
    giro = make_account("Giro")  # 1000.00
    elektronik = _kategorie(client, headers, "Elektronik-T")
    lebensmittel = _kategorie(client, headers, "Lebensmittel-T")
    _buche(client, headers, giro, "2026-01-05", "-80.00", elektronik)
    _buche(client, headers, giro, "2026-01-20", "120.00", elektronik)  # Rückgabe eines früheren, teureren Kaufs
    _buche(client, headers, giro, "2026-01-12", "-200.00", lebensmittel)

    bericht = _kategorien(client, headers, "2026-01-01", "2026-01-31")
    items = _nach_name(bericht)
    assert (items["Elektronik-T"]["gross"], items["Elektronik-T"]["refunds"]) == ("80.00", "120.00")
    assert items["Elektronik-T"]["net"] == "-40.00"  # 80 − 120
    assert items["Elektronik-T"]["share"] is None
    # Die negative Hauptkategorie zählt im Nenner nicht mit: 200 / 200
    assert (items["Lebensmittel-T"]["net"], items["Lebensmittel-T"]["share"]) == ("200.00", "1.0000")
    assert bericht["total_net"] == "160.00"  # 200 − 40 = die tatsächlichen Nettoausgaben
    assert _summary(client, headers, "2026-01-01", "2026-01-31")["movements"]["expenses"] == "160.00"


def test_kategorien_nur_negative_hauptkategorien_haben_keine_anteile(client, headers, make_account):
    giro = make_account("Giro")  # 1000.00
    rueckbuchungen = _kategorie(client, headers, "Rückbuchungen-T")
    reparatur = _kategorie(client, headers, "Reparatur-T", parent=rueckbuchungen)
    garten = _kategorie(client, headers, "Garten-T")
    _buche(client, headers, giro, "2026-01-05", "100.00", rueckbuchungen)  # nur Erstattung
    _buche(client, headers, giro, "2026-01-06", "-60.00", reparatur)
    _buche(client, headers, giro, "2026-01-07", "30.00", garten)  # nur Erstattung

    bericht = _kategorien(client, headers, "2026-01-01", "2026-01-31")
    items = _nach_name(bericht)
    assert (items["Rückbuchungen-T"]["gross"], items["Rückbuchungen-T"]["refunds"]) == ("60.00", "100.00")
    assert items["Rückbuchungen-T"]["net"] == "-40.00"  # 60 − 100
    assert items["Rückbuchungen-T"]["own_net"] == "-100.00"
    assert items["Reparatur-T"]["net"] == "60.00"  # positiv, aber die Hauptkategorie darüber ist negativ
    assert (items["Garten-T"]["gross"], items["Garten-T"]["refunds"], items["Garten-T"]["net"]) == (
        "0.00", "30.00", "-30.00",
    )
    # Es gibt keine positive Hauptkategorie, also keine Bezugsgröße: überall null
    assert all(i["share"] is None for i in bericht["items"])
    assert bericht["total_net"] == "-70.00"  # −40 − 30


def test_kategorien_einnahmen_mit_rueckzahlung_ergeben_erstattungen(client, headers, make_account):
    giro = make_account("Giro")  # 1000.00
    gehalt = _kategorie(client, headers, "Gehalt-T", "income")
    bonus = _kategorie(client, headers, "Bonus-T", "income", parent=gehalt)
    einkauf = _kategorie(client, headers, "Einkauf-T")
    _buche(client, headers, giro, "2026-01-05", "3000.00", gehalt)
    _buche(client, headers, giro, "2026-01-20", "-200.00", gehalt)  # Rückzahlung zu viel gezahlten Gehalts
    _buche(client, headers, giro, "2026-01-25", "500.00", bonus)
    _buche(client, headers, giro, "2026-01-10", "-80.00", einkauf)  # Ausgabe: gehört nicht in den Einnahmenbericht

    bericht = _kategorien(client, headers, "2026-01-01", "2026-01-31", "income")
    assert bericht["type"] == "income"
    items = _nach_name(bericht)
    assert set(items) == {"Gehalt-T", "Bonus-T"}
    # Gehalt: brutto 3000 + 500 (Bonus), erstattet 200 → netto 3300; eigenes Netto 3000 − 200
    assert (items["Gehalt-T"]["gross"], items["Gehalt-T"]["refunds"], items["Gehalt-T"]["net"]) == (
        "3500.00", "200.00", "3300.00",
    )
    assert (items["Gehalt-T"]["own_net"], items["Gehalt-T"]["share"]) == ("2800.00", "1.0000")
    assert (items["Bonus-T"]["gross"], items["Bonus-T"]["refunds"], items["Bonus-T"]["net"]) == (
        "500.00", "0.00", "500.00",
    )
    assert items["Bonus-T"]["share"] == "0.1515"  # 500 / 3300
    assert (bericht["total_net"], bericht["uncategorized"]) == ("3300.00", "0.00")
    # In der Zusammenfassung: Einnahmen 3000 − 200 + 500; die Rückzahlung bleibt ein Abfluss
    assert _summary(client, headers, "2026-01-01", "2026-01-31")["movements"] == _fluesse(
        income="3300.00", expenses="80.00", net="3220.00", cash_in="3500.00", cash_out="280.00"
    )


def test_unkategorisiert_wird_fuer_einnahmen_und_ausgaben_getrennt_ausgewiesen(client, headers, make_account):
    giro = make_account("Giro")  # 1000.00
    sparkonto = make_account("Sparkonto", type="savings", opening_balance="0.00")
    lohn = _kategorie(client, headers, "Lohn-T", "income")
    einkauf = _kategorie(client, headers, "Einkauf-T")
    _buche(client, headers, giro, "2026-01-03", "1000.00", lohn)
    _buche(client, headers, giro, "2026-01-04", "-100.00", einkauf)
    _buche(client, headers, giro, "2026-01-05", "40.00")  # unkategorisierte Zuflüsse
    _buche(client, headers, giro, "2026-01-06", "10.00")
    _buche(client, headers, giro, "2026-01-07", "-15.00")  # unkategorisierte Abflüsse
    _buche(client, headers, giro, "2026-01-08", "-5.00")
    _umbuche(client, headers, giro, sparkonto, "70.00", "2026-01-09")  # Umbuchung: ohne Kategorie, aber kein Posten

    ausgaben = _kategorien(client, headers, "2026-01-01", "2026-01-31", "expense")
    assert ausgaben["uncategorized"] == "20.00"  # nur die Abflüsse: 15 + 5
    assert ausgaben["total_net"] == "100.00"  # die unkategorisierten Beträge stecken nicht in der Summe
    einnahmen = _kategorien(client, headers, "2026-01-01", "2026-01-31", "income")
    assert einnahmen["uncategorized"] == "50.00"  # nur die Zuflüsse: 40 + 10
    assert einnahmen["total_net"] == "1000.00"

    # Zusammenfassung: Netto 1000 − 100 + 50 − 20; die Umbuchung zählt nirgends
    assert _summary(client, headers, "2026-01-01", "2026-01-31")["movements"] == _fluesse(
        income="1000.00", expenses="100.00", unc_in="50.00", unc_out="20.00", net="930.00",
        cash_in="1050.00", cash_out="120.00",
    )


def test_kategorien_datumsgrenzen_sind_inklusive(client, headers, make_account):
    giro = make_account("Giro")  # 1000.00
    einkauf = _kategorie(client, headers, "Einkauf-T")
    for tag, betrag in [("2026-01-31", "-1.00"), ("2026-02-01", "-10.00"), ("2026-02-15", "-20.00"),
                        ("2026-02-28", "-30.00"), ("2026-03-01", "-40.00")]:
        _buche(client, headers, giro, tag, betrag, einkauf)

    def netto(von, bis):
        return _kategorien(client, headers, von, bis)["total_net"]

    assert netto("2026-02-01", "2026-02-28") == "60.00"  # 10 + 20 + 30: erster und letzter Tag zählen mit
    assert netto("2026-02-28", "2026-02-28") == "30.00"  # ein einzelner Tag ist ein gültiger Zeitraum
    assert netto("2026-02-01", "2026-02-01") == "10.00"
    assert netto("2026-01-31", "2026-03-01") == "101.00"  # 1 + 10 + 20 + 30 + 40
    # Die Zusammenfassung zieht dieselben Grenzen
    assert _summary(client, headers, "2026-02-01", "2026-02-28")["movements"]["expenses"] == "60.00"


def test_zeitraum_von_nach_bis_wird_bei_kategorien_und_pdf_abgelehnt(client, headers):
    for pfad in ("/reports/categories", "/export/report.pdf"):
        response = client.get(pfad, params={"date_from": "2026-02-01", "date_to": "2026-01-31"}, headers=headers)
        assert response.status_code == 422, pfad
        assert response.json()["error"]["code"] == "invalid_period"


# --- /reports/trends ------------------------------------------------------------------------


def test_trends_luecken_ergeben_null_und_monatsgrenzen_gehoeren_zum_richtigen_monat(client, headers, make_account):
    giro = make_account("Giro")  # 1000.00
    einkauf = _kategorie(client, headers, "Einkauf-T")
    lohn = _kategorie(client, headers, "Lohn-T", "income")
    _buche(client, headers, giro, "2026-01-31", "-10.00", einkauf)  # Monatsletzter → Januar
    _buche(client, headers, giro, "2026-02-01", "-20.00", einkauf)  # Monatserster → Februar
    _buche(client, headers, giro, "2026-04-01", "100.00", lohn)  # Monatserster → April
    _buche(client, headers, giro, "2026-04-30", "-7.00")  # Monatsletzter, unkategorisiert → April

    assert _trends(client, headers, months=4, until="2026-04-30") == [
        _monat("2026-01-01", expenses="10.00", net="-10.00"),
        _monat("2026-02-01", expenses="20.00", net="-20.00"),
        _monat("2026-03-01"),  # Lücke: überall 0.00
        _monat("2026-04-01", income="100.00", unc_out="7.00", net="93.00"),  # 100 − 7
    ]


def test_trends_mit_einem_monat(client, headers, make_account):
    giro = make_account("Giro")  # 1000.00
    einkauf = _kategorie(client, headers, "Einkauf-T")
    _buche(client, headers, giro, "2026-02-28", "-5.00", einkauf)  # Vormonat
    _buche(client, headers, giro, "2026-03-01", "-7.00", einkauf)
    _buche(client, headers, giro, "2026-03-15", "-11.00", einkauf)
    _buche(client, headers, giro, "2026-04-01", "-13.00", einkauf)  # Folgemonat

    # Nur der März: 7 + 11
    assert _trends(client, headers, months=1, until="2026-03-15") == [
        _monat("2026-03-01", expenses="18.00", net="-18.00")
    ]


def test_trends_ueber_den_jahreswechsel(client, headers, make_account):
    giro = make_account("Giro", opening_balance="1000.00", opening_balance_date="2026-10-01")
    einkauf = _kategorie(client, headers, "Einkauf-T")
    lohn = _kategorie(client, headers, "Lohn-T", "income")
    _buche(client, headers, giro, "2026-10-31", "-1.00", einkauf)  # vor dem Zeitraum
    _buche(client, headers, giro, "2026-11-30", "-11.00", einkauf)
    _buche(client, headers, giro, "2026-12-01", "-12.00", einkauf)
    _buche(client, headers, giro, "2026-12-31", "200.00", lohn)
    _buche(client, headers, giro, "2027-01-01", "-13.00", einkauf)
    _buche(client, headers, giro, "2027-01-20", "-14.00", einkauf)

    assert _trends(client, headers, months=3, until="2027-01-20") == [
        _monat("2026-11-01", expenses="11.00", net="-11.00"),
        _monat("2026-12-01", income="200.00", expenses="12.00", net="188.00"),  # 200 − 12
        _monat("2027-01-01", expenses="27.00", net="-27.00"),  # 13 + 14
    ]
    # Auch über mehr als ein Jahr bleibt die Monatsreihe lückenlos: 13 Monate bis Januar 2027
    monate = [m["month"] for m in _trends(client, headers, months=13, until="2027-01-20")]
    assert monate == [f"2026-{n:02d}-01" for n in range(1, 13)] + ["2027-01-01"]


def test_trends_lueckenlos_ueber_120_monate(client, headers):
    reihe = _trends(client, headers, months=120, until="2026-01-31")
    monate = [m["month"] for m in reihe]
    assert len(monate) == 120  # die größte erlaubte Reihe
    assert (monate[0], monate[-1]) == ("2016-02-01", "2026-01-01")  # 120 Monate = Februar 2016 … Januar 2026
    assert len(set(monate)) == 120  # keine Lücke, keine Dublette
    assert all(m == _monat(m["month"]) for m in reihe)  # ohne Buchungen sind alle Monate leer


@pytest.mark.parametrize("pfad", ["/reports/trends", "/reports/loans"])
@pytest.mark.parametrize("months", [0, 121])
def test_months_ausserhalb_von_1_bis_120_wird_abgelehnt(client, headers, pfad, months):
    response = client.get(pfad, params={"months": months, "until": "2026-01-31"}, headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_trends_category_id_filtert_inklusive_unterkategorien(client, headers, make_account):
    giro = make_account("Giro")  # 1000.00
    auto = _kategorie(client, headers, "Auto-T")
    tanken = _kategorie(client, headers, "Tanken-T", parent=auto)
    wohnen = _kategorie(client, headers, "Wohnen-T")
    lohn = _kategorie(client, headers, "Lohn-T", "income")
    _buche(client, headers, giro, "2026-01-05", "-100.00", auto)
    _buche(client, headers, giro, "2026-01-06", "-40.00", tanken)
    _buche(client, headers, giro, "2026-01-07", "-500.00", wohnen)
    _buche(client, headers, giro, "2026-01-08", "-9.00")  # unkategorisiert
    _buche(client, headers, giro, "2026-01-09", "2000.00", lohn)
    _buche(client, headers, giro, "2026-02-03", "-25.00", tanken)

    def reihe(**filter_):
        return _trends(client, headers, months=2, until="2026-02-28", **filter_)

    # Ohne Filter: Januar Ausgaben 100 + 40 + 500, unkategorisiert 9, Netto 2000 − 640 − 9
    assert reihe() == [
        _monat("2026-01-01", income="2000.00", expenses="640.00", unc_out="9.00", net="1351.00"),
        _monat("2026-02-01", expenses="25.00", net="-25.00"),
    ]
    # Oberkategorie: eigene Buchungen plus Unterkategorie (100 + 40); Unkategorisiertes fällt heraus
    assert reihe(category_id=auto["id"]) == [
        _monat("2026-01-01", expenses="140.00", net="-140.00"),
        _monat("2026-02-01", expenses="25.00", net="-25.00"),
    ]
    # Unterkategorie allein
    assert reihe(category_id=tanken["id"]) == [
        _monat("2026-01-01", expenses="40.00", net="-40.00"),
        _monat("2026-02-01", expenses="25.00", net="-25.00"),
    ]
    assert reihe(category_id=wohnen["id"]) == [
        _monat("2026-01-01", expenses="500.00", net="-500.00"),
        _monat("2026-02-01"),
    ]
    # Einnahmekategorie: erscheint unter income
    assert reihe(category_id=lohn["id"]) == [
        _monat("2026-01-01", income="2000.00", net="2000.00"),
        _monat("2026-02-01"),
    ]
    assert _bericht(client, headers, "/reports/trends", months=2, until="2026-02-28",
                    category_id=auto["id"])["category_id"] == auto["id"]


def test_trends_trennen_unkategorisierte_ein_und_ausgaenge(client, headers, make_account):
    giro = make_account("Giro")  # 1000.00
    sparkonto = make_account("Sparkonto", type="savings", opening_balance="0.00")
    einkauf = _kategorie(client, headers, "Einkauf-T")
    lohn = _kategorie(client, headers, "Lohn-T", "income")
    _buche(client, headers, giro, "2026-01-03", "1000.00", lohn)
    _buche(client, headers, giro, "2026-01-04", "-100.00", einkauf)
    _buche(client, headers, giro, "2026-01-05", "40.00")  # unkategorisierter Zufluss
    _buche(client, headers, giro, "2026-01-06", "-15.00")  # unkategorisierter Abfluss
    _umbuche(client, headers, giro, sparkonto, "250.00", "2026-01-20")  # zählt nirgends
    _buche(client, headers, giro, "2026-02-02", "-5.00")

    assert _trends(client, headers, months=2, until="2026-02-28") == [
        # Netto 1000 − 100 + 40 − 15
        _monat("2026-01-01", income="1000.00", expenses="100.00", unc_in="40.00", unc_out="15.00", net="925.00"),
        _monat("2026-02-01", unc_out="5.00", net="-5.00"),
    ]


# --- /reports/loans -------------------------------------------------------------------------


def test_kreditbericht_zwei_kredite_einer_vollstaendig_getilgt(client, headers, make_account):
    giro = make_account("Giro", opening_balance="5000.00")
    _kredit(client, headers, payment_account_id=giro["id"])  # 10000.00 zu 5 %, Rate 230.30
    privat = _privatkredit(client, headers, "300.00", name="Privatdarlehen-T", payment_account_id=giro["id"])
    zahlung = _rate(client, headers, privat["id"], booking_date="2026-02-10", amount="300.00")
    assert (zahlung["interest"], zahlung["principal"]) == ("0.00", "300.00")  # 0 %: alles Tilgung

    r = _kreditbericht(client, headers, until="2026-02-28", months=2)
    zeile_auto, zeile_privat = r["loans"]  # nach Anlage sortiert
    assert (zeile_auto["name"], zeile_auto["status"]) == ("Autokredit-T", "active")
    assert (zeile_auto["remaining_debt"], zeile_auto["next_installment"]) == ("10000.00", "230.30")
    assert zeile_auto["remaining_by_month"] == [
        {"month_end": "2026-01-31", "remaining_debt": "10000.00"},
        {"month_end": "2026-02-28", "remaining_debt": "10000.00"},
    ]
    assert zeile_auto["interest_paid_by_year"] == []  # noch keine Rate gebucht

    assert (zeile_privat["name"], zeile_privat["status"]) == ("Privatdarlehen-T", "paid_off")
    assert (zeile_privat["remaining_debt"], zeile_privat["next_installment"]) == ("0.00", None)
    assert zeile_privat["remaining_by_month"] == [
        {"month_end": "2026-01-31", "remaining_debt": "300.00"},
        {"month_end": "2026-02-28", "remaining_debt": "0.00"},  # 300 − 300 am 10.2.
    ]
    assert zeile_privat["interest_paid_by_year"] == [{"year": 2026, "interest": "0.00"}]
    # Nur der aktive Kredit belastet monatlich; der getilgte hat keine offene Rate mehr
    assert r["monthly_burden"] == "230.30"


def test_kreditbericht_monatliche_belastung_ist_die_naechste_offene_rate_je_aktivem_kredit(
    client, headers, make_account
):
    giro = make_account("Giro", opening_balance="5000.00")
    _kredit(client, headers, payment_account_id=giro["id"])  # Annuität: jede Rate 230.30
    # Tilgungsdarlehen: feste Tilgung 1200 / 12 = 100.00, Zinsen 0,5 % p. M., dazu 2.50 Gebühr je Rate
    moebel = _kredit(
        client, headers, name="Moebelkredit-T", loan_type="installment", annual_interest_rate="6",
        current_balance="1200.00", term_months=12, extra_amount="2.50", payment_account_id=giro["id"],
    )
    vorher = _kreditbericht(client, headers, until="2026-02-28", months=1)
    assert [z["next_installment"] for z in vorher["loans"]] == ["230.30", "108.50"]  # 6.00 + 100.00 + 2.50
    assert vorher["monthly_burden"] == "338.80"  # 230.30 + 108.50

    zahlung = _rate(client, headers, moebel["id"], booking_date="2026-01-31", amount="108.50")
    assert (zahlung["interest"], zahlung["principal"], zahlung["extra"]) == ("6.00", "100.00", "2.50")

    nachher = _kreditbericht(client, headers, until="2026-02-28", months=1)
    moebel_zeile = nachher["loans"][1]
    assert moebel_zeile["remaining_debt"] == "1100.00"  # 1200 − 100
    # Die bezahlte Rate zählt nicht mehr; die nächste ist kleiner: 1100 × 0,5 % = 5.50 Zinsen
    assert moebel_zeile["next_installment"] == "108.00"  # 5.50 + 100.00 + 2.50
    assert nachher["monthly_burden"] == "338.30"  # 230.30 + 108.00
    # Gebühren sind kein Zins: gezahlte Zinsen nur die 6.00; in den Ausgaben stehen Zinsen und Gebühren
    assert moebel_zeile["interest_paid_by_year"] == [{"year": 2026, "interest": "6.00"}]
    assert _summary(client, headers, "2026-01-01", "2026-01-31")["movements"]["expenses"] == "8.50"  # 6.00 + 2.50


def test_kreditbericht_restschuld_je_monatsende_ueber_den_monatswechsel(client, headers, make_account):
    giro = make_account("Giro", opening_balance="5000.00")
    kredit = _kredit(client, headers, payment_account_id=giro["id"])  # 10000.00 zu 5 %, Rate 230.30
    # Rate 1 am Monatsletzten: 10000 × 5 % / 12 = 41.67 Zinsen, 188.63 Tilgung
    _rate(client, headers, kredit["id"], booking_date="2026-01-31", amount="230.30")
    # Rate 2 erst am Monatsersten danach: 9811.37 × 5 % / 12 = 40.88 Zinsen, 189.42 Tilgung
    _rate(client, headers, kredit["id"], booking_date="2026-03-01", amount="230.30")

    zeile = _kreditbericht(client, headers, until="2026-03-31", months=3)["loans"][0]
    assert zeile["remaining_by_month"] == [
        {"month_end": "2026-01-31", "remaining_debt": "9811.37"},  # 10000 − 188.63: die Zahlung vom 31.1. zählt noch
        {"month_end": "2026-02-28", "remaining_debt": "9811.37"},  # im Februar wurde nichts gebucht
        {"month_end": "2026-03-31", "remaining_debt": "9621.95"},  # 9811.37 − 189.42 (Zahlung vom 1.3.)
    ]
    assert zeile["remaining_debt"] == "9621.95"
    assert zeile["next_installment"] == "230.30"  # die Annuität bleibt gleich


def test_kreditbericht_restschuld_vor_dem_stichtag_ist_null(client, headers):
    _privatkredit(client, headers, "500.00", name="Spaetkredit-T", balance_date="2026-02-15")

    zeile = _kreditbericht(client, headers, until="2026-03-31", months=3)["loans"][0]
    assert zeile["remaining_by_month"] == [
        {"month_end": "2026-01-31", "remaining_debt": None},  # Stichtag erst am 15.2.: noch kein Saldo
        {"month_end": "2026-02-28", "remaining_debt": "500.00"},
        {"month_end": "2026-03-31", "remaining_debt": "500.00"},
    ]


def test_kreditbericht_zinsen_je_jahr_ueber_den_jahreswechsel(client, headers, make_account):
    giro = make_account("Giro", opening_balance="5000.00")
    kredit = _kredit(
        client, headers, balance_date="2026-12-01", first_due_date="2026-12-31", payment_account_id=giro["id"]
    )
    # Rate 1 (Dezember): 10000 × 5 % / 12 = 41.67 Zinsen, 188.63 Tilgung → Restschuld 9811.37
    _rate(client, headers, kredit["id"], booking_date="2026-12-31", amount="230.30")
    # Rate 2 (Neujahr): 9811.37 × 5 % / 12 = 40.88 Zinsen, 189.42 Tilgung → 9621.95
    _rate(client, headers, kredit["id"], booking_date="2027-01-01", amount="230.30")
    # Rate 3 (Januar): 9621.95 × 5 % / 12 = 40.09 Zinsen, 190.21 Tilgung → 9431.74
    _rate(client, headers, kredit["id"], booking_date="2027-01-31", amount="230.30")

    zeile = _kreditbericht(client, headers, until="2027-01-31", months=2)["loans"][0]
    assert zeile["interest_paid_by_year"] == [
        {"year": 2026, "interest": "41.67"},
        {"year": 2027, "interest": "80.97"},  # 40.88 + 40.09
    ]
    assert zeile["remaining_by_month"] == [
        {"month_end": "2026-12-31", "remaining_debt": "9811.37"},
        {"month_end": "2027-01-31", "remaining_debt": "9431.74"},
    ]
    # Die Zinsen sind die Ausgaben des Jahres in der Zusammenfassung (die Tilgung ist eine Umbuchung)
    assert _summary(client, headers, "2026-01-01", "2026-12-31")["movements"]["expenses"] == "41.67"
    assert _summary(client, headers, "2027-01-01", "2027-12-31")["movements"]["expenses"] == "80.97"


def test_kreditbericht_monatsenden_ueber_jahreswechsel_und_schaltjahr(client, headers):
    _privatkredit(client, headers, "1000.00")  # ab 2026-01-01, ohne Buchungen

    def monatsenden(**params):
        zeile = _kreditbericht(client, headers, **params)["loans"][0]
        return [m["month_end"] for m in zeile["remaining_by_month"]]

    assert monatsenden(until="2027-01-31", months=3) == ["2026-11-30", "2026-12-31", "2027-01-31"]
    assert monatsenden(until="2028-03-31", months=3) == ["2028-01-31", "2028-02-29", "2028-03-31"]  # Schaltjahr
    assert monatsenden(until="2027-03-31", months=2) == ["2027-02-28", "2027-03-31"]
    assert monatsenden(until="2026-06-30", months=1) == ["2026-06-30"]


def test_kreditbericht_ohne_kredite_und_je_profil_getrennt(client, headers, other_user):
    leer = {"loans": [], "monthly_burden": "0.00"}
    assert _kreditbericht(client, headers, until="2026-03-31") == leer
    _kredit(client, headers)
    assert _kreditbericht(client, headers, until="2026-03-31")["monthly_burden"] == "230.30"
    # Der Kredit gehört dem ersten Profil
    assert _kreditbericht(client, other_user["headers"], until="2026-03-31") == leer


def test_kategorienbericht_zeigt_von_der_kreditrate_nur_zinsen_und_gebuehren(client, headers, make_account):
    giro = make_account("Giro", opening_balance="5000.00")
    kredit = _kredit(
        client, headers, name="Moebelkredit-T", loan_type="installment", annual_interest_rate="6",
        current_balance="1200.00", term_months=12, extra_amount="2.50", payment_account_id=giro["id"],
    )
    # Rate 108.50 = 6.00 Zinsen + 100.00 Tilgung (Umbuchung) + 2.50 Gebühr
    _rate(client, headers, kredit["id"], booking_date="2026-01-31", amount="108.50")

    kategorien = client.get("/categories", headers=headers).json()
    schluessel = {c["system_key"]: c["id"] for c in kategorien if c["system_key"]}
    bericht = _kategorien(client, headers, "2026-01-01", "2026-01-31")
    nach_id = {i["category_id"]: i for i in bericht["items"]}
    assert nach_id[schluessel["loan_interest"]]["net"] == "6.00"
    assert nach_id[schluessel["loan_fees"]]["net"] == "2.50"
    # Die Tilgung taucht nirgends auf, auch nicht als „unkategorisiert“
    assert (bericht["total_net"], bericht["uncategorized"]) == ("8.50", "0.00")  # 6.00 + 2.50
    assert sum(Decimal(i["own_net"]) for i in bericht["items"]) == Decimal("8.50")


# --- CSV-Export -----------------------------------------------------------------------------


def test_csv_export_liefert_alle_230_buchungen_obwohl_die_liste_bei_200_endet(client, headers, make_account):
    giro = make_account("Giro")
    ids = []
    for i in range(1, 231):
        tag = (date(2026, 1, 1) + timedelta(days=i % 60)).isoformat()
        ids.append(_buche(client, headers, giro, tag, f"-{i}.00", description=f"Posten {i:03d}")["id"])

    seite = client.get("/transactions", params={"limit": 200}, headers=headers).json()
    assert (seite["total"], len(seite["items"])) == (230, 200)  # die Liste liefert höchstens 200 je Seite
    assert client.get("/transactions", params={"limit": 201}, headers=headers).status_code == 422

    response = client.get("/export/transactions.csv", headers=headers)
    _, rows = _csv(response)
    assert len(rows) == 230  # der Export kennt kein Seitenlimit
    assert sorted(int(r["Buchungs-ID"]) for r in rows) == sorted(ids)
    # Summe der Beträge: −(1 + 2 + … + 230) = −230 × 231 / 2
    assert sum(_dezimal(r["Betrag"]) for r in rows) == Decimal("-26565.00")
    # Dieselbe Reihenfolge wie die Liste (neueste zuerst)
    assert [int(r["Buchungs-ID"]) for r in rows[:200]] == [t["id"] for t in seite["items"]]


def test_csv_export_ueber_mehrere_interne_stapel_vollstaendig_und_stabil_sortiert(
    client, headers, session, user, make_account
):
    giro = make_account("Giro")
    anzahl = 2 * BATCH_SIZE + 3  # der Export liest in Stapeln: hier drei, der letzte fast leer
    buchungen = [
        Transaction(
            user_id=user["id"], account_id=giro["id"], booking_date=date(2026, 1, 1) + timedelta(days=i % 7),
            amount=Decimal("-1.00"), description=f"Masse {i:04d}", review_status="confirmed",
            category_source="none", source="manual",
        )
        for i in range(anzahl)  # nur sieben verschiedene Tage: viele Buchungen mit gleichem Datum
    ]
    session.add_all(buchungen)
    session.flush()
    ids = [b.id for b in buchungen]
    session.commit()

    _, rows = _csv(client.get("/export/transactions.csv", headers=headers))
    export_ids = [int(r["Buchungs-ID"]) for r in rows]
    assert len(export_ids) == anzahl and set(export_ids) == set(ids)  # alle, keine doppelt
    # Datum absteigend, bei gleichem Datum die höhere ID zuerst – über die Stapelgrenzen hinweg
    schluessel = [(datetime.strptime(r["Buchungsdatum"], "%d.%m.%Y").date(), int(r["Buchungs-ID"])) for r in rows]
    assert schluessel == sorted(schluessel, reverse=True)


def test_csv_filter_datumsbereich_ist_inklusive(client, headers, make_account):
    giro = make_account("Giro")
    for tag in ("2026-01-31", "2026-02-01", "2026-02-15", "2026-02-28", "2026-03-01"):
        _buche(client, headers, giro, tag, "-1.00", description=f"Tag {tag}")

    def tage(*tage_):
        return {f"Tag {tag}" for tag in tage_}

    # Beide Grenzen zählen mit
    assert _csv_zwecke(client, headers, date_from="2026-02-01", date_to="2026-02-28") == tage(
        "2026-02-01", "2026-02-15", "2026-02-28"
    )
    assert _csv_zwecke(client, headers, date_from="2026-02-15") == tage("2026-02-15", "2026-02-28", "2026-03-01")
    assert _csv_zwecke(client, headers, date_to="2026-02-01") == tage("2026-01-31", "2026-02-01")
    # Ein einzelner Tag ist ein gültiger Zeitraum
    assert _csv_zwecke(client, headers, date_from="2026-02-28", date_to="2026-02-28") == tage("2026-02-28")


def test_csv_filter_konten_und_kategorien(client, headers, make_account):
    giro = make_account("Giro")
    karte = make_account("Karte", type="credit_card", opening_balance="0.00")
    bargeld = make_account("Bargeld", type="cash", opening_balance="0.00")
    auto = _kategorie(client, headers, "Auto-T")
    tanken = _kategorie(client, headers, "Tanken-T", parent=auto)
    wohnen = _kategorie(client, headers, "Wohnen-T")
    _buche(client, headers, giro, "2026-01-10", "-100.00", auto, description="giro-auto")
    _buche(client, headers, giro, "2026-01-11", "-40.00", tanken, description="giro-tanken")
    _buche(client, headers, giro, "2026-01-12", "-500.00", wohnen, description="giro-wohnen")
    _buche(client, headers, giro, "2026-01-13", "-9.00", description="giro-ohne")
    _buche(client, headers, karte, "2026-01-14", "-30.00", tanken, description="karte-tanken")
    _buche(client, headers, karte, "2026-01-15", "-20.00", wohnen, description="karte-wohnen")
    _buche(client, headers, bargeld, "2026-01-16", "-5.00", auto, description="bar-auto")

    assert _csv_zwecke(client, headers, account_ids=[giro["id"], karte["id"]]) == {
        "giro-auto", "giro-tanken", "giro-wohnen", "giro-ohne", "karte-tanken", "karte-wohnen",
    }
    assert _csv_zwecke(client, headers, account_ids=[bargeld["id"]]) == {"bar-auto"}
    # Oberkategorie schließt ihre Unterkategorien ein, wenn nicht ausdrücklich ausgeschaltet
    assert _csv_zwecke(client, headers, category_id=auto["id"]) == {
        "giro-auto", "giro-tanken", "karte-tanken", "bar-auto",
    }
    assert _csv_zwecke(client, headers, category_id=auto["id"], include_subcategories=False) == {
        "giro-auto", "bar-auto",
    }
    assert _csv_zwecke(client, headers, category_id=tanken["id"]) == {"giro-tanken", "karte-tanken"}
    # Filter wirken gemeinsam
    assert _csv_zwecke(client, headers, account_ids=[karte["id"]], category_id=auto["id"]) == {"karte-tanken"}


def test_csv_ausgeschlossene_buchungen_nur_mit_include_excluded(client, headers, session, make_account):
    giro = make_account("Giro")
    _buche(client, headers, giro, "2026-01-10", "-1.00", description="normal-1")
    doppelt = _buche(client, headers, giro, "2026-01-11", "-2.00", description="importiert-doppelt")
    _buche(client, headers, giro, "2026-01-12", "-3.00", description="normal-2")
    _als_import_ausschliessen(client, headers, session, doppelt)

    assert _csv_zwecke(client, headers) == {"normal-1", "normal-2"}  # Standard: ausgeschlossene fehlen
    _, rows = _csv(client.get("/export/transactions.csv", params={"include_excluded": True}, headers=headers))
    nach_zweck = {r["Verwendungszweck"]: r for r in rows}
    assert set(nach_zweck) == {"normal-1", "importiert-doppelt", "normal-2"}
    # Die Spalte „Ausgeschlossen“ kennzeichnet nur die ausgeschlossene Buchung
    assert nach_zweck["importiert-doppelt"]["Ausgeschlossen"] != ""
    assert nach_zweck["normal-1"]["Ausgeschlossen"] == "" and nach_zweck["normal-2"]["Ausgeschlossen"] == ""


FORMELZEICHEN = [
    pytest.param("=", id="gleich"),
    pytest.param("+", id="plus"),
    pytest.param("-", id="minus"),
    pytest.param("@", id="at"),
    pytest.param("\t", id="tab"),
    pytest.param("\r", id="cr"),
]


@pytest.mark.parametrize("zeichen", FORMELZEICHEN)
def test_csv_formelschutz_in_jeder_textspalte(client, headers, session, make_account, zeichen):
    konto = make_account(f"{zeichen}Konto")
    kategorie = _kategorie(client, headers, f"{zeichen}Kategorie")
    buchung = _buche(
        client, headers, konto, "2026-01-10", "-12.50", kategorie,
        description=f"{zeichen}Zweck", counterparty=f"{zeichen}Partner",
    )
    # Die API lässt nur gültige IBANs zu; die Spalte wird trotzdem geschützt (z. B. für Altdaten)
    session.get(Transaction, buchung["id"]).counterparty_iban = f"{zeichen}DE00"
    session.commit()

    _, rows = _csv(client.get("/export/transactions.csv", params={"account_ids": [konto["id"]]}, headers=headers))
    assert len(rows) == 1
    zeile = rows[0]
    assert zeile["Konto"] == f"'{zeichen}Konto"
    assert zeile["Kategorie"] == f"'{zeichen}Kategorie"
    assert zeile["Gegenpartei"] == f"'{zeichen}Partner"
    assert zeile["IBAN Gegenpartei"] == f"'{zeichen}DE00"
    assert zeile["Verwendungszweck"] == f"'{zeichen}Zweck"
    assert zeile["Betrag"] == "-12,50"  # der Betrag bleibt eine Zahl, auch mit führendem Minus


def test_csv_texte_ohne_formelzeichen_am_anfang_bleiben_unveraendert(client, headers, make_account):
    giro = make_account("Giro")
    texte = ["Miete = 500", "Rechnung 5 - 3", "a@b.de", "123-456", "'schon geschützt", "Zahlung +5 Prozent"]
    for nr, text in enumerate(texte, start=1):
        _buche(client, headers, giro, f"2026-01-{nr:02d}", "-1.00", description=text)

    assert _csv_zwecke(client, headers) == set(texte)  # kein Apostroph zu viel


def test_csv_zeile_enthaelt_datum_und_betrag_im_deutschen_format(client, headers, make_account):
    konto = make_account("Giro")
    wohnen = _kategorie(client, headers, "Wohnen-T")
    _buche(
        client, headers, konto, "2026-01-10", "-1234.50", wohnen, value_date="2026-01-12",
        description="Miete Januar", counterparty="Vermieter GmbH", counterparty_iban="DE89 3704 0044 0532 0130 00",
    )

    _, rows = _csv(client.get("/export/transactions.csv", headers=headers))
    assert len(rows) == 1
    zeile = rows[0]
    assert (zeile["Buchungsdatum"], zeile["Wertstellung"]) == ("10.01.2026", "12.01.2026")  # TT.MM.JJJJ
    assert zeile["Betrag"] == "-1234,50"  # Dezimalkomma, kein Tausenderpunkt: bleibt eine Zahl
    assert (zeile["Konto"], zeile["Kategorie"], zeile["Gegenpartei"], zeile["Verwendungszweck"]) == (
        "Giro", "Wohnen-T", "Vermieter GmbH", "Miete Januar",
    )
    assert zeile["IBAN Gegenpartei"] == "DE89370400440532013000"  # ohne Leerzeichen
    assert (zeile["Art"], zeile["Teilzeile"], zeile["Ausgeschlossen"]) == ("", "", "")  # reguläre, ungeteilte Buchung


def test_csv_umlaute_und_sonderzeichen_bleiben_in_utf8_erhalten(client, headers, make_account):
    konto = make_account("Girokonto Zürich")
    kategorie = _kategorie(client, headers, "Café & Getränke")
    _buche(
        client, headers, konto, "2026-01-10", "-4.20", kategorie,
        description="Bäckerei – Größe ß, 5 € (naïve)", counterparty="Müller & Söhne GmbH",
    )

    response = client.get("/export/transactions.csv", headers=headers)
    assert response.headers["content-type"].replace(" ", "") == "text/csv;charset=utf-8"
    header, rows = _csv(response)  # prüft auch das BOM
    assert header[0] == "Buchungsdatum" and "Prüfstatus" in header  # BOM gehört nicht zum ersten Spaltennamen
    assert len(rows) == 1
    zeile = rows[0]
    assert zeile["Konto"] == "Girokonto Zürich"
    assert zeile["Kategorie"] == "Café & Getränke"
    assert zeile["Gegenpartei"] == "Müller & Söhne GmbH"
    assert zeile["Verwendungszweck"] == "Bäckerei – Größe ß, 5 € (naïve)"
    assert zeile["Betrag"] == "-4,20"
    assert b"Z\xc3\xbcrich" in response.content  # echte UTF-8-Bytes von „ü“ (nicht Latin-1)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("Miete; Nebenkosten", id="semikolon"),
        pytest.param("a;b;c;d", id="mehrere-semikolons"),
        pytest.param('Zahlung "Rate 3"; Referenz', id="anfuehrungszeichen"),
        pytest.param("Zeile 1\nZeile 2; Ende", id="zeilenumbruch"),
    ],
)
def test_csv_semikolon_im_verwendungszweck_wird_gequotet(client, headers, make_account, text):
    giro = make_account("Giro")
    _buche(client, headers, giro, "2026-01-10", "-1.00", description=text)

    response = client.get("/export/transactions.csv", headers=headers)
    header, rows = _csv(response)  # csv.reader liest in jeder Zeile genau die Spalten der Kopfzeile
    assert len(header) == 14 and len(rows) == 1
    assert rows[0]["Verwendungszweck"] == text
    assert '"' + text.replace('"', '""') + '"' in response.content.decode("utf-8")  # Feld in Anführungszeichen


def test_csv_splits_als_eigene_zeilen_mit_art_kategorie_und_teilzeile(client, headers, make_account):
    giro = make_account("Giro")
    sparkonto = make_account("Sparkonto", type="savings", opening_balance="0.00")
    a = _kategorie(client, headers, "Split-A")
    b = _kategorie(client, headers, "Split-B")
    geteilt = _buche(
        client, headers, giro, "2026-01-15", "-100.00", description="Wocheneinkauf",
        splits=[
            {"amount": "-60.00", "category_id": a["id"]},
            {"amount": "-25.00", "category_id": b["id"]},
            {"amount": "-15.00", "kind": "transfer"},
        ],
    )
    _umbuche(client, headers, giro, sparkonto, "70.00", "2026-01-20")

    _, rows = _csv(client.get("/export/transactions.csv", headers=headers))
    assert len(rows) == 3 + 2  # drei Teilzeilen und zwei Seiten der Umbuchung
    zeilen = [r for r in rows if r["Buchungs-ID"] == str(geteilt["id"])]
    assert [(r["Teilzeile"], r["Betrag"], r["Kategorie"]) for r in zeilen] == [
        ("1", "-60,00", "Split-A"),
        ("2", "-25,00", "Split-B"),
        ("3", "-15,00", ""),  # die Transfer-Zeile hat keine Kategorie
    ]
    # Die Spalte „Art“ unterscheidet die Transfer-Zeile von den regulären Zeilen
    assert zeilen[0]["Art"] == zeilen[1]["Art"] == "" and zeilen[2]["Art"] != ""
    assert sum(_dezimal(r["Betrag"]) for r in zeilen) == Decimal("-100.00")  # 60 + 25 + 15 = Buchungsbetrag
    # Die Umbuchung zwischen zwei Konten: je Seite eine Zeile, ohne Teilzeile und als Umbuchung gekennzeichnet
    umbuchung = [r for r in rows if r["Buchungs-ID"] != str(geteilt["id"])]
    assert sorted((r["Konto"], r["Betrag"], r["Teilzeile"]) for r in umbuchung) == [
        ("Giro", "-70,00", ""),
        ("Sparkonto", "70,00", ""),
    ]
    assert all(r["Art"] == zeilen[2]["Art"] for r in umbuchung)  # dieselbe Kennzeichnung wie die Transfer-Zeile


def test_csv_export_ist_je_profil_getrennt(client, headers, other_user, make_account):
    giro = make_account("Giro")
    _buche(client, headers, giro, "2026-01-10", "-1.00", description="nur meine")

    header, rows = _csv(client.get("/export/transactions.csv", headers=other_user["headers"]))
    assert header[0] == "Buchungsdatum" and rows == []  # nur die Kopfzeile
    # Auch mit der Konto-ID des fremden Profils kommt nichts heraus
    fremd = client.get("/export/transactions.csv", params={"account_ids": [giro["id"]]}, headers=other_user["headers"])
    assert _csv(fremd)[1] == []
    assert _csv_zwecke(client, headers) == {"nur meine"}


# --- PDF ------------------------------------------------------------------------------------


def test_pdf_bericht_fuer_zeitraum_ohne_buchungen(client, headers, user, make_account):
    giro = make_account("Giro")  # 1000.00
    einkauf = _kategorie(client, headers, "Einkauf-T")
    _buche(client, headers, giro, "2026-01-15", "-100.00", einkauf)

    response = client.get(
        "/export/report.pdf", params={"date_from": "2026-05-01", "date_to": "2026-05-31"}, headers=headers
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF") and response.content.rstrip().endswith(b"%%EOF")
    seiten = _pdf_seiten(response.content)
    assert len(seiten) == 1
    texte = seiten[0]
    assert f"Finanzbericht {user['name']}" in texte
    assert "Zeitraum 01.05.2026 – 31.05.2026" in texte
    assert _nach(texte, "Giro") == "900,00"  # 1000 − 100 (Januar); im Mai nichts gebucht
    assert _nach(texte, "Nettovermögen") == "900,00"
    assert _nach(texte, "Einnahmen (netto)") == "0,00"
    assert _nach(texte, "Ausgaben (netto)") == "0,00"


def test_pdf_bericht_vor_dem_stichtag_zeigt_keinen_saldo(client, headers, make_account):
    make_account("Giro")  # Stichtag 2026-01-01

    response = client.get(
        "/export/report.pdf", params={"date_from": "2025-01-01", "date_to": "2025-01-31"}, headers=headers
    )
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    texte = _pdf_seiten(response.content)[0]
    assert _nach(texte, "Giro *") == "–"  # kein Saldo; Stern = Historie unvollständig
    assert _nach(texte, "Nettovermögen") == "0,00"


def test_pdf_viele_kategorien_fuehren_zu_mehreren_seiten(client, headers, make_account):
    giro = make_account("Giro")
    namen = [f"Kat-{i:03d}" for i in range(80)]
    for name in namen:
        _buche(client, headers, giro, "2026-01-10", "-1.00", _kategorie(client, headers, name))

    response = client.get(
        "/export/report.pdf", params={"date_from": "2026-01-01", "date_to": "2026-01-31"}, headers=headers
    )
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    seiten = _pdf_seiten(response.content)
    assert len(seiten) >= 2  # 80 Zeilen passen nicht auf eine Seite
    for nr, texte in enumerate(seiten, start=1):
        assert f"Seite {nr}" in texte  # fortlaufende Fußzeile
    alle = [t for texte in seiten for t in texte]
    assert all(alle.count(name) == 1 for name in namen)  # beim Umbruch geht keine Kategorie verloren oder doppelt ein
    assert all("Kategorie" in texte for texte in seiten[1:])  # der Tabellenkopf wiederholt sich auf Folgeseiten


def test_pdf_bericht_mit_markup_und_sonderzeichen_in_namen(client, headers, make_account):
    giro = make_account("R&D <Team> & Co ☕")
    kategorie = _kategorie(client, headers, "<b>fett</b> & Pizza 🍕 > 5 € äöü")
    _buche(client, headers, giro, "2026-01-10", "-1.00", kategorie)

    response = client.get(
        "/export/report.pdf", params={"date_from": "2026-01-01", "date_to": "2026-01-31"}, headers=headers
    )
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    text = "".join(_pdf_seiten(response.content)[0])
    assert "<b>fett</b>" in text  # Markup in Namen wird nicht ausgewertet, sondern wörtlich gedruckt
    assert "R&D <Team>" in text


def test_pdf_tilgungsplan_eines_fremden_kredits_ist_404(client, headers, other_user):
    kredit = _kredit(client, headers)
    eigen = client.get(f"/export/loans/{kredit['id']}/schedule.pdf", headers=headers)
    assert eigen.status_code == 200 and eigen.content.startswith(b"%PDF")
    assert "Tilgungsplan Autokredit-T" in _pdf_seiten(eigen.content)[0]

    for pfad in (f"/export/loans/{kredit['id']}/schedule.pdf", f"/export/loans/{kredit['id']}/schedule.csv"):
        fremd = client.get(pfad, headers=other_user["headers"])
        assert fremd.status_code == 404, pfad
        assert fremd.json()["error"]["code"] == "not_found"
    assert client.get("/export/loans/999999/schedule.pdf", headers=headers).status_code == 404


def test_pdf_bericht_zeigt_nur_konten_des_eigenen_profils(client, headers, other_user, make_account):
    make_account("Geheimkonto-T")

    response = client.get(
        "/export/report.pdf", params={"date_from": "2026-01-01", "date_to": "2026-01-31"}, headers=other_user["headers"]
    )
    assert response.status_code == 200
    texte = _pdf_seiten(response.content)[0]
    assert f"Finanzbericht {other_user['name']}" in texte
    assert not any("Geheimkonto-T" in t for t in texte)
    assert _nach(texte, "Nettovermögen") == "0,00"
