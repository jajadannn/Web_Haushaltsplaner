"""Kontostände: Szenario-Tests mit von Hand durchgerechneten Salden.

Jeder Test baut sein kleines Szenario selbst auf. Die erwarteten Salden stehen als exakte
Dezimalstrings im Test, die Rechnung als Kommentar daneben.

Regel: Saldo(Ende Tag D) = Anfangssaldo + Summe aller nicht ausgeschlossenen Buchungen mit
Stichtag <= Buchungsdatum <= D. Vor dem Stichtag gibt es keinen Saldo (null).
Das Standardkonto aus `make_account` ist ein Girokonto mit 1000.00 zu Beginn des 2026-01-01.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.models import Transaction


def _expense(client, headers, name="Testausgabe"):
    response = client.post("/categories", json={"name": name, "type": "expense"}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _tx(client, headers, account_id, amount, **extra):
    payload = {
        "account_id": account_id,
        "booking_date": "2026-02-01",
        "amount": amount,
        "description": "Test",
        **extra,
    }
    return client.post("/transactions", json=payload, headers=headers)


def _balance(client, headers, account_id, as_of=None):
    params = {"as_of": as_of} if as_of else {}
    return client.get(f"/accounts/{account_id}", params=params, headers=headers).json()["balance"]


def _as_imported(session, tx_id):
    session.get(Transaction, tx_id).source = "import"
    session.flush()


# --- Zusätzliche Hilfen für diese Datei ----------------------------------------


def _buche(client, headers, account_id, amount, booking_date="2026-02-01", **extra):
    """Legt eine Buchung an, die gelingen muss, und gibt sie als JSON zurück."""
    response = _tx(client, headers, account_id, amount, booking_date=booking_date, **extra)
    assert response.status_code == 201, response.text
    return response.json()


def _umbuche(client, headers, von, nach, amount, booking_date="2026-02-01"):
    """Legt eine Umbuchung an, die gelingen muss, und gibt {outgoing, incoming} zurück."""
    response = client.post(
        "/transfers",
        json={
            "from_account_id": von["id"],
            "to_account_id": nach["id"],
            "booking_date": booking_date,
            "amount": amount,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _salden(client, headers, as_of, **filters):
    """Salden aus `GET /accounts?as_of=...` als {Kontoname: Saldo}."""
    response = client.get("/accounts", params={"as_of": as_of, **filters}, headers=headers)
    assert response.status_code == 200, response.text
    return {account["name"]: account["balance"] for account in response.json()}


def _summe(*salden):
    """Exakte Summe von Saldo-Strings (Decimal, nie float)."""
    return sum((Decimal(s) for s in salden), Decimal("0"))


# --- Stichtag und Abfragedatum --------------------------------------------------


def test_ohne_buchungen_ist_der_saldo_der_anfangssaldo(client, headers, make_account):
    giro = make_account()  # 1000.00 zu Beginn von 2026-01-01
    assert _balance(client, headers, giro["id"], "2026-01-01") == "1000.00"
    assert _balance(client, headers, giro["id"], "2026-12-31") == "1000.00"


def test_buchung_am_stichtag_zaehlt_mit(client, headers, make_account):
    giro = make_account()  # 1000.00 zu Beginn von 2026-01-01
    _buche(client, headers, giro["id"], "-10.00", "2026-01-01")
    # Der Anfangssaldo gilt zu Beginn des Stichtags, die Buchung dieses Tages kommt dazu:
    # 1000.00 - 10.00 = 990.00
    assert _balance(client, headers, giro["id"], "2026-01-01") == "990.00"


def test_vor_dem_stichtag_gibt_es_keinen_saldo(client, headers, make_account):
    giro = make_account("Giro", opening_balance_date="2026-03-01")  # 1000.00 ab 2026-03-01
    response = client.get(
        f"/accounts/{giro['id']}", params={"as_of": "2026-02-28"}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["balance"] is None
    assert response.json()["balance_date"] == "2026-02-28"
    # Gleiches Bild in der Kontoliste
    assert _salden(client, headers, "2026-02-28") == {"Giro": None}
    # Am Stichtag selbst gilt der Anfangssaldo: 1000.00
    assert _balance(client, headers, giro["id"], "2026-03-01") == "1000.00"


def test_buchung_zaehlt_am_buchungstag_und_nicht_davor(client, headers, make_account):
    giro = make_account()  # 1000.00 zu Beginn von 2026-01-01
    _buche(client, headers, giro["id"], "-40.00", "2026-03-10")  # Tag D
    _buche(client, headers, giro["id"], "-25.00", "2026-03-11")  # Tag D+1
    # Ende 2026-03-09: noch keine der beiden Buchungen -> 1000.00
    assert _balance(client, headers, giro["id"], "2026-03-09") == "1000.00"
    # Ende von D (2026-03-10): nur die Buchung vom 10. -> 1000.00 - 40.00 = 960.00
    assert _balance(client, headers, giro["id"], "2026-03-10") == "960.00"
    # Ende von D+1 (2026-03-11): beide -> 1000.00 - 40.00 - 25.00 = 935.00
    assert _balance(client, headers, giro["id"], "2026-03-11") == "935.00"


def test_wertstellung_ist_fuer_den_saldo_unerheblich(client, headers, make_account):
    giro = make_account()  # 1000.00 zu Beginn von 2026-01-01
    _buche(client, headers, giro["id"], "-30.00", "2026-02-01", value_date="2026-02-05")
    # Es zählt das Buchungsdatum, nicht die Wertstellung
    assert _balance(client, headers, giro["id"], "2026-01-31") == "1000.00"
    assert _balance(client, headers, giro["id"], "2026-02-01") == "970.00"  # 1000.00 - 30.00


def test_ohne_as_of_gilt_heute_und_spaetere_buchungen_zaehlen_nicht(client, headers, make_account):
    # Stichtag und erste Buchung liegen sicher in der Vergangenheit, die zweite sicher in der
    # Zukunft. So hängt der Test nicht vom heutigen Datum ab.
    giro = make_account("Giro", opening_balance_date="2020-01-01")  # 1000.00 ab 2020-01-01
    _buche(client, headers, giro["id"], "-100.00", "2020-06-15")
    _buche(client, headers, giro["id"], "-50.00", "2099-01-01")

    vorher = date.today().isoformat()
    konto = client.get(f"/accounts/{giro['id']}", headers=headers).json()
    nachher = date.today().isoformat()
    # Nur die Buchung von 2020 zählt: 1000.00 - 100.00 = 900.00
    assert konto["balance"] == "900.00"
    assert vorher <= konto["balance_date"] <= nachher  # ohne as_of: heute
    # Die Kontoliste rechnet ebenfalls bis heute
    liste = client.get("/accounts", headers=headers).json()
    assert [(k["name"], k["balance"]) for k in liste] == [("Giro", "900.00")]

    # Erst ab dem Buchungstag zählt auch die Buchung von 2099: 1000.00 - 100.00 - 50.00 = 850.00
    assert _balance(client, headers, giro["id"], "2098-12-31") == "900.00"
    assert _balance(client, headers, giro["id"], "2099-01-01") == "850.00"


def test_konto_mit_stichtag_in_der_zukunft_hat_heute_noch_keinen_saldo(
    client, headers, make_account
):
    zukunft = make_account("Zukunft", opening_balance_date="2099-01-01")  # 1000.00 ab 2099-01-01
    # Ohne as_of gilt heute, und das liegt vor dem Stichtag: kein Saldo (auch beim Anlegen)
    assert zukunft["balance"] is None
    assert _balance(client, headers, zukunft["id"]) is None
    # Am Stichtag selbst gilt der Anfangssaldo: 1000.00
    assert _balance(client, headers, zukunft["id"], "2099-01-01") == "1000.00"


# --- Ausschluss importierter Buchungen ------------------------------------------


def test_ausgeschlossene_buchung_zaehlt_nicht_im_saldo(client, headers, session, make_account):
    giro = make_account()  # 1000.00 zu Beginn von 2026-01-01
    importiert = _buche(client, headers, giro["id"], "-200.00", "2026-02-01")
    _buche(client, headers, giro["id"], "-50.00", "2026-02-02")
    _as_imported(session, importiert["id"])  # nur importierte Buchungen lassen sich ausschließen
    # Beide Buchungen zählen: 1000.00 - 200.00 - 50.00 = 750.00
    assert _balance(client, headers, giro["id"], "2026-12-31") == "750.00"

    response = client.post(
        f"/transactions/{importiert['id']}/exclude",
        json={"reason": "Doppelt gebucht"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["excluded_at"] is not None
    # Nur noch die zweite Buchung: 1000.00 - 50.00 = 950.00
    assert _balance(client, headers, giro["id"], "2026-12-31") == "950.00"
    # Auch für frühere Stichtage: Ende 2026-02-01 war nur die ausgeschlossene Buchung gebucht
    assert _balance(client, headers, giro["id"], "2026-02-01") == "1000.00"

    response = client.post(f"/transactions/{importiert['id']}/include", headers=headers)
    assert response.status_code == 200
    assert response.json()["excluded_at"] is None
    # Wieder eingeschlossen: 1000.00 - 200.00 - 50.00 = 750.00
    assert _balance(client, headers, giro["id"], "2026-12-31") == "750.00"
    assert _balance(client, headers, giro["id"], "2026-02-01") == "800.00"  # 1000.00 - 200.00


def test_ausgeschlossene_aufgeteilte_buchung_faellt_komplett_aus_dem_saldo(
    client, headers, session, make_account
):
    giro = make_account()  # 1000.00 zu Beginn von 2026-01-01
    a = _expense(client, headers, "Split-A")
    b = _expense(client, headers, "Split-B")
    tx = _buche(
        client, headers, giro["id"], "-100.00",
        splits=[{"amount": "-70.00", "category_id": a["id"]},
                {"amount": "-30.00", "category_id": b["id"]}],
    )
    _as_imported(session, tx["id"])
    # 1000.00 - 100.00 = 900.00
    assert _balance(client, headers, giro["id"], "2026-12-31") == "900.00"

    response = client.post(
        f"/transactions/{tx['id']}/exclude", json={"reason": "Dublette"}, headers=headers
    )
    assert response.status_code == 200
    # Mit der Buchung entfallen alle Zeilen: 1000.00
    assert _balance(client, headers, giro["id"], "2026-12-31") == "1000.00"


# --- Erstattung -----------------------------------------------------------------


def test_erstattung_in_derselben_ausgabenkategorie_ergibt_den_nettoeffekt(
    client, headers, make_account
):
    giro = make_account()  # 1000.00 zu Beginn von 2026-01-01
    shopping = _expense(client, headers, "Shopping-Test")
    _buche(client, headers, giro["id"], "-100.00", "2026-02-01", category_id=shopping["id"])
    # Nach dem Kauf: 1000.00 - 100.00 = 900.00
    assert _balance(client, headers, giro["id"], "2026-02-04") == "900.00"

    _buche(client, headers, giro["id"], "30.00", "2026-02-05", category_id=shopping["id"])
    # Saldoeffekt gesamt: -100.00 + 30.00 = -70.00, also 1000.00 - 70.00 = 930.00
    assert _balance(client, headers, giro["id"], "2026-02-05") == "930.00"
    # Vor dem Erstattungstag bleibt es bei 900.00
    assert _balance(client, headers, giro["id"], "2026-02-04") == "900.00"


# --- Splits ---------------------------------------------------------------------


def test_aufgeteilte_buchung_veraendert_den_saldo_um_den_gesamtbetrag(
    client, headers, make_account
):
    giro = make_account()  # 1000.00 zu Beginn von 2026-01-01
    a = _expense(client, headers, "Split-A")
    b = _expense(client, headers, "Split-B")
    tx = _buche(
        client, headers, giro["id"], "-100.00",
        splits=[{"amount": "-70.00", "category_id": a["id"]},
                {"amount": "-30.00", "category_id": b["id"]}],
    )
    assert [s["amount"] for s in tx["splits"]] == ["-70.00", "-30.00"]
    # Die Zeilen kommen nicht zusätzlich zum Betrag dazu: 1000.00 - 100.00 = 900.00
    assert _balance(client, headers, giro["id"], "2026-12-31") == "900.00"


def test_split_mit_umbuchungszeile_verlaesst_das_konto_vollstaendig(client, headers, make_account):
    giro = make_account()  # 1000.00 zu Beginn von 2026-01-01
    zinsen = _expense(client, headers, "Zinsen-Test")
    # Kreditrate 500.00: 380.00 Tilgung (Umbuchungszeile) + 120.00 Zinsen (Ausgabe)
    _buche(
        client, headers, giro["id"], "-500.00",
        splits=[{"amount": "-380.00", "kind": "transfer"},
                {"amount": "-120.00", "category_id": zinsen["id"]}],
    )
    # Auch die Umbuchungszeile verändert den Kontostand: 1000.00 - 500.00 = 500.00
    assert _balance(client, headers, giro["id"], "2026-12-31") == "500.00"


def test_split_aendern_saldo_folgt_dem_neuen_gesamtbetrag(client, headers, make_account):
    giro = make_account()  # 1000.00 zu Beginn von 2026-01-01
    a = _expense(client, headers, "Split-A")
    b = _expense(client, headers, "Split-B")
    tx = _buche(
        client, headers, giro["id"], "-100.00",
        splits=[{"amount": "-60.00", "category_id": a["id"]},
                {"amount": "-40.00", "category_id": b["id"]}],
    )
    url = f"/transactions/{tx['id']}"
    assert _balance(client, headers, giro["id"], "2026-12-31") == "900.00"  # 1000.00 - 100.00

    # Neuer Gesamtbetrag -90.00 mit passenden Zeilen (-50.00 und -40.00)
    response = client.patch(
        url,
        json={"amount": "-90.00",
              "splits": [{"amount": "-50.00", "category_id": a["id"]},
                         {"amount": "-40.00", "category_id": b["id"]}]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert _balance(client, headers, giro["id"], "2026-12-31") == "910.00"  # 1000.00 - 90.00

    # Aufteilung entfernen: der Betrag bleibt -90.00
    response = client.patch(url, json={"splits": None, "category_id": a["id"]}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["splits"] == []
    assert _balance(client, headers, giro["id"], "2026-12-31") == "910.00"


def test_aufgeteilte_buchung_loeschen_stellt_den_saldo_wieder_her(client, headers, make_account):
    giro = make_account()  # 1000.00 zu Beginn von 2026-01-01
    tx = _buche(
        client, headers, giro["id"], "-100.00",
        splits=[{"amount": "-70.00"}, {"amount": "-30.00"}],
    )
    assert _balance(client, headers, giro["id"], "2026-12-31") == "900.00"  # 1000.00 - 100.00

    assert client.delete(f"/transactions/{tx['id']}", headers=headers).status_code == 204
    assert _balance(client, headers, giro["id"], "2026-12-31") == "1000.00"


# --- Umbuchungen ----------------------------------------------------------------


def test_umbuchung_zwischen_banken_bewegt_beide_salden_und_erhaelt_die_summe(
    client, headers, make_institution, make_account
):
    giro = make_account("Giro", institution_id=make_institution("Sparkasse")["id"])  # 1000.00
    tagesgeld = make_account(
        "Tagesgeld", type="savings", opening_balance="250.00",
        institution_id=make_institution("DKB")["id"],
    )  # 250.00 zu Beginn von 2026-01-01

    def salden(as_of):
        return (
            _balance(client, headers, giro["id"], as_of),
            _balance(client, headers, tagesgeld["id"], as_of),
        )

    # Vor der Umbuchung: 1000.00 + 250.00 = 1250.00
    assert salden("2026-02-10") == ("1000.00", "250.00")
    assert _summe(*salden("2026-02-10")) == Decimal("1250.00")

    umbuchung = _umbuche(client, headers, giro, tagesgeld, "400.00", booking_date="2026-02-10")
    assert umbuchung["outgoing"]["amount"] == "-400.00"
    assert umbuchung["incoming"]["amount"] == "400.00"

    # Quelle: 1000.00 - 400.00 = 600.00; Ziel: 250.00 + 400.00 = 650.00
    assert salden("2026-02-10") == ("600.00", "650.00")
    # Die Summe bleibt gleich: 600.00 + 650.00 = 1250.00
    assert _summe(*salden("2026-02-10")) == Decimal("1250.00")
    # Am Vortag der Umbuchung ist noch alles beim Alten
    assert salden("2026-02-09") == ("1000.00", "250.00")


def test_umbuchung_nicht_einseitig_aenderbar_summe_bleibt(client, headers, make_account):
    giro = make_account("Giro")  # 1000.00 zu Beginn von 2026-01-01
    sparen = make_account("Sparen", type="savings", opening_balance="0.00")
    umbuchung = _umbuche(client, headers, giro, sparen, "300.00")
    # Giro: 1000.00 - 300.00 = 700.00; Sparen: 0.00 + 300.00 = 300.00

    response = client.patch(
        f"/transactions/{umbuchung['outgoing']['id']}", json={"amount": "-1.00"}, headers=headers
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "transfer_pair_linked"
    # Nichts hat sich bewegt, die Summe ist weiter 700.00 + 300.00 = 1000.00
    giro_saldo = _balance(client, headers, giro["id"], "2026-12-31")
    sparen_saldo = _balance(client, headers, sparen["id"], "2026-12-31")
    assert (giro_saldo, sparen_saldo) == ("700.00", "300.00")
    assert _summe(giro_saldo, sparen_saldo) == Decimal("1000.00")


@pytest.mark.parametrize(
    ("archiviert", "datum", "status", "code"),
    [
        (False, "2026-02-15", 422, "before_opening"),  # vor dem Stichtag des Zielkontos
        (True, "2026-03-05", 409, "account_archived"),  # Zielkonto archiviert
    ],
)
def test_abgelehnte_umbuchung_aendert_keinen_saldo(
    client, headers, make_account, archiviert, datum, status, code
):
    giro = make_account("Giro")  # 1000.00 zu Beginn von 2026-01-01
    ziel = make_account("Ziel", opening_balance="200.00", opening_balance_date="2026-03-01")
    if archiviert:
        assert client.post(f"/accounts/{ziel['id']}/archive", headers=headers).status_code == 200

    response = client.post(
        "/transfers",
        json={"from_account_id": giro["id"], "to_account_id": ziel["id"],
              "booking_date": datum, "amount": "100.00"},
        headers=headers,
    )
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    # Keine der beiden Seiten wurde gebucht: beide Salden sind die Anfangssalden
    assert _balance(client, headers, giro["id"], "2026-12-31") == "1000.00"
    assert _balance(client, headers, ziel["id"], "2026-12-31") == "200.00"
    assert client.get("/transactions", headers=headers).json()["total"] == 0


# --- Kreditkarte ----------------------------------------------------------------


def test_kreditkarte_einkaeufe_ins_minus_und_ausgleich_vom_girokonto(
    client, headers, make_institution, make_account
):
    giro = make_account("Giro", institution_id=make_institution("Sparkasse")["id"])  # 1000.00
    karte = make_account(
        "Visa", type="credit_card", opening_balance="0.00",
        institution_id=make_institution("Kartenbank")["id"],
    )  # 0.00 zu Beginn von 2026-01-01
    _buche(client, headers, karte["id"], "-45.90", "2026-02-03")
    _buche(client, headers, karte["id"], "-120.00", "2026-02-10")

    # Vor dem ersten Einkauf: 0.00
    assert _balance(client, headers, karte["id"], "2026-02-02") == "0.00"
    # Nach dem ersten Einkauf: 0.00 - 45.90 = -45.90
    assert _balance(client, headers, karte["id"], "2026-02-09") == "-45.90"
    # Nach beiden Einkäufen: 0.00 - 45.90 - 120.00 = -165.90
    assert _balance(client, headers, karte["id"], "2026-02-27") == "-165.90"
    # Das Girokonto ist bis zum Ausgleich unberührt: 1000.00
    assert _balance(client, headers, giro["id"], "2026-02-27") == "1000.00"

    # Ausgleich am 2026-02-28 vom Girokonto: 165.90 (Umbuchung, keine Ausgabe)
    ausgleich = _umbuche(client, headers, giro, karte, "165.90", booking_date="2026-02-28")
    assert ausgleich["outgoing"]["kind"] == ausgleich["incoming"]["kind"] == "transfer"
    # Karte: -165.90 + 165.90 = 0.00; Girokonto: 1000.00 - 165.90 = 834.10
    assert _balance(client, headers, karte["id"], "2026-02-28") == "0.00"
    assert _balance(client, headers, giro["id"], "2026-02-28") == "834.10"
    # Der Zwischenstand vor dem Ausgleich bleibt abrufbar
    assert _balance(client, headers, karte["id"], "2026-02-27") == "-165.90"
    assert _balance(client, headers, giro["id"], "2026-02-27") == "1000.00"


# --- Ändern und Löschen ---------------------------------------------------------


def test_betrag_aendern_der_saldo_folgt(client, headers, make_account):
    giro = make_account()  # 1000.00 zu Beginn von 2026-01-01
    tx = _buche(client, headers, giro["id"], "-80.00", "2026-02-01")
    url = f"/transactions/{tx['id']}"
    assert _balance(client, headers, giro["id"], "2026-12-31") == "920.00"  # 1000.00 - 80.00

    response = client.patch(url, json={"amount": "-30.00"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["amount"] == "-30.00"
    assert _balance(client, headers, giro["id"], "2026-12-31") == "970.00"  # 1000.00 - 30.00

    # Vorzeichen drehen (aus dem Kauf wird eine Gutschrift): 1000.00 + 20.00 = 1020.00
    response = client.patch(url, json={"amount": "20.00"}, headers=headers)
    assert response.status_code == 200
    assert _balance(client, headers, giro["id"], "2026-12-31") == "1020.00"


def test_datum_ueber_as_of_hinaus_verschieben(client, headers, make_account):
    giro = make_account()  # 1000.00 zu Beginn von 2026-01-01
    tx = _buche(client, headers, giro["id"], "-60.00", "2026-03-10")
    url = f"/transactions/{tx['id']}"
    # Am 15. zählt die Buchung vom 10.: 1000.00 - 60.00 = 940.00
    assert _balance(client, headers, giro["id"], "2026-03-15") == "940.00"

    # Auf den 20. verschoben zählt sie am 15. noch nicht
    response = client.patch(url, json={"booking_date": "2026-03-20"}, headers=headers)
    assert response.status_code == 200
    assert _balance(client, headers, giro["id"], "2026-03-15") == "1000.00"
    assert _balance(client, headers, giro["id"], "2026-03-19") == "1000.00"
    # ... und ab dem 20. wieder: 1000.00 - 60.00 = 940.00
    assert _balance(client, headers, giro["id"], "2026-03-20") == "940.00"

    # Zurück auf den 1. verschoben zählt sie am 15. wieder
    response = client.patch(url, json={"booking_date": "2026-03-01"}, headers=headers)
    assert response.status_code == 200
    assert _balance(client, headers, giro["id"], "2026-03-15") == "940.00"

    # Vor den Stichtag (2026-01-01) lässt sie sich nicht verschieben; der Saldo bleibt
    response = client.patch(url, json={"booking_date": "2025-12-31"}, headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "before_opening"
    assert _balance(client, headers, giro["id"], "2026-03-15") == "940.00"


def test_loeschen_stellt_den_saldo_von_vorher_wieder_her(client, headers, make_account):
    giro = make_account()  # 1000.00 zu Beginn von 2026-01-01
    _buche(client, headers, giro["id"], "-10.00", "2026-02-01")
    vorher = _balance(client, headers, giro["id"], "2026-12-31")
    assert vorher == "990.00"  # 1000.00 - 10.00

    tx = _buche(client, headers, giro["id"], "-75.25", "2026-02-02")
    assert _balance(client, headers, giro["id"], "2026-12-31") == "914.75"  # 990.00 - 75.25

    assert client.delete(f"/transactions/{tx['id']}", headers=headers).status_code == 204
    assert _balance(client, headers, giro["id"], "2026-12-31") == "990.00"  # wie vorher


# --- Anfangssaldo und Stichtag ändern -------------------------------------------


def test_anfangssaldo_aendern_der_saldo_folgt(client, headers, make_account):
    giro = make_account()  # 1000.00 zu Beginn von 2026-01-01
    _buche(client, headers, giro["id"], "-100.00", "2026-02-01")
    assert _balance(client, headers, giro["id"], "2026-12-31") == "900.00"  # 1000.00 - 100.00

    response = client.patch(
        f"/accounts/{giro['id']}", json={"opening_balance": "1200.50"}, headers=headers
    )
    assert response.status_code == 200
    # Nach der Buchung: 1200.50 - 100.00 = 1100.50; davor gilt der neue Anfangssaldo 1200.50
    assert _balance(client, headers, giro["id"], "2026-12-31") == "1100.50"
    assert _balance(client, headers, giro["id"], "2026-01-31") == "1200.50"


def test_stichtag_verschieben_aendert_ab_wann_ein_saldo_verfuegbar_ist(
    client, headers, make_account
):
    giro = make_account()  # 1000.00 zu Beginn von 2026-01-01
    _buche(client, headers, giro["id"], "-60.00", "2026-03-10")
    url = f"/accounts/{giro['id']}"

    # Stichtag auf den 2026-03-01 (davor liegt keine Buchung): Saldo davor nicht mehr verfügbar
    response = client.patch(url, json={"opening_balance_date": "2026-03-01"}, headers=headers)
    assert response.status_code == 200
    assert _balance(client, headers, giro["id"], "2026-02-28") is None
    assert _balance(client, headers, giro["id"], "2026-03-01") == "1000.00"
    assert _balance(client, headers, giro["id"], "2026-03-10") == "940.00"  # 1000.00 - 60.00

    # Hinter die Buchung (2026-03-11) geht nicht, sie fiele sonst aus dem Saldo; nichts ändert sich
    response = client.patch(url, json={"opening_balance_date": "2026-03-11"}, headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "transactions_before_opening"
    assert _balance(client, headers, giro["id"], "2026-03-10") == "940.00"

    # Nach vorn auf den 2025-12-01: der Anfangssaldo gilt ab dann, spätere Salden bleiben gleich
    response = client.patch(url, json={"opening_balance_date": "2025-12-01"}, headers=headers)
    assert response.status_code == 200
    assert _balance(client, headers, giro["id"], "2025-12-15") == "1000.00"
    assert _balance(client, headers, giro["id"], "2026-03-10") == "940.00"


# --- Archivierung ---------------------------------------------------------------


def test_archiviertes_konto_behaelt_seinen_saldo(client, headers, make_account):
    make_account("Giro")  # 1000.00, bleibt aktiv
    alt = make_account("Altkonto", opening_balance="500.00")  # 500.00 zu Beginn von 2026-01-01
    _buche(client, headers, alt["id"], "-300.00", "2026-02-01")
    _buche(client, headers, alt["id"], "100.00", "2026-04-01")

    response = client.post(f"/accounts/{alt['id']}/archive", headers=headers)
    assert response.status_code == 200
    assert response.json()["archived_at"] is not None

    # Die Einzelabfrage liefert weiterhin den richtigen Saldo:
    # Ende Februar 500.00 - 300.00 = 200.00; Ende Dezember 200.00 + 100.00 = 300.00
    assert _balance(client, headers, alt["id"], "2026-02-28") == "200.00"
    assert _balance(client, headers, alt["id"], "2026-12-31") == "300.00"

    # In der Standardliste fehlt das Konto, mit include_archived ist es samt Saldo da
    assert _salden(client, headers, "2026-12-31") == {"Giro": "1000.00"}
    alle = _salden(client, headers, "2026-12-31", include_archived=True)
    assert alle == {"Giro": "1000.00", "Altkonto": "300.00"}
    assert _salden(client, headers, "2026-02-28", include_archived=True)["Altkonto"] == "200.00"


def test_archiviertes_konto_nimmt_keine_buchungen_an(client, headers, make_account):
    konto = make_account()  # 1000.00 zu Beginn von 2026-01-01
    _buche(client, headers, konto["id"], "-300.00", "2026-02-01")  # 1000.00 - 300.00 = 700.00
    assert client.post(f"/accounts/{konto['id']}/archive", headers=headers).status_code == 200

    response = _tx(client, headers, konto["id"], "-50.00", booking_date="2026-03-01")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "account_archived"
    # Der Saldo ist unverändert 700.00
    assert _balance(client, headers, konto["id"], "2026-12-31") == "700.00"


# --- Mehrere Konten -------------------------------------------------------------


def test_mehrere_konten_mit_eigenem_anfangssaldo_und_stichtag(
    client, headers, make_institution, make_account
):
    bank_a = make_institution("Bank A")
    bank_b = make_institution("Bank B")
    giro = make_account(
        "Giro", institution_id=bank_a["id"],
        opening_balance="1500.00", opening_balance_date="2026-01-01",
    )
    tagesgeld = make_account(
        "Tagesgeld", type="savings", institution_id=bank_a["id"],
        opening_balance="2000.00", opening_balance_date="2026-02-15",
    )
    karte = make_account(
        "Kreditkarte", type="credit_card", institution_id=bank_b["id"],
        opening_balance="-80.50", opening_balance_date="2026-03-01",
    )
    _buche(client, headers, giro["id"], "-200.00", "2026-01-10")
    _buche(client, headers, giro["id"], "2500.00", "2026-01-28")
    _buche(client, headers, giro["id"], "-99.99", "2026-02-20")
    _buche(client, headers, tagesgeld["id"], "50.00", "2026-02-15")  # genau am Stichtag
    _buche(client, headers, tagesgeld["id"], "25.00", "2026-03-05")
    _buche(client, headers, karte["id"], "-30.25", "2026-03-02")
    _buche(client, headers, karte["id"], "-19.75", "2026-03-20")

    # Ende Januar haben Tagesgeld (Stichtag 15.02.) und Karte (01.03.) noch keinen Saldo.
    # Giro: 1500.00 - 200.00 + 2500.00 = 3800.00
    assert _salden(client, headers, "2026-01-31") == {
        "Giro": "3800.00", "Tagesgeld": None, "Kreditkarte": None,
    }
    # Ende Februar: Karte noch ohne Saldo.
    # Giro: 3800.00 - 99.99 = 3700.01
    # Tagesgeld: 2000.00 + 50.00 = 2050.00 (die Buchung vom 05.03. fehlt noch)
    assert _salden(client, headers, "2026-02-28") == {
        "Giro": "3700.01", "Tagesgeld": "2050.00", "Kreditkarte": None,
    }
    # Am Stichtag der Karte gilt ihr Anfangssaldo: -80.50
    assert _salden(client, headers, "2026-03-01") == {
        "Giro": "3700.01", "Tagesgeld": "2050.00", "Kreditkarte": "-80.50",
    }
    # 2026-03-10: Tagesgeld 2050.00 + 25.00 = 2075.00; Karte -80.50 - 30.25 = -110.75
    assert _salden(client, headers, "2026-03-10") == {
        "Giro": "3700.01", "Tagesgeld": "2075.00", "Kreditkarte": "-110.75",
    }
    # Ende März: Karte -110.75 - 19.75 = -130.50
    assert _salden(client, headers, "2026-03-31") == {
        "Giro": "3700.01", "Tagesgeld": "2075.00", "Kreditkarte": "-130.50",
    }
    # Die Einzelabfrage stimmt mit der Liste überein
    for konto, erwartet in [(giro, "3700.01"), (tagesgeld, "2075.00"), (karte, "-130.50")]:
        assert _balance(client, headers, konto["id"], "2026-03-31") == erwartet


def test_kontoliste_nach_bank_und_typ_filtern_behaelt_die_salden(
    client, headers, make_institution, make_account
):
    bank_a = make_institution("Bank A")
    bank_b = make_institution("Bank B")
    giro = make_account("Giro", institution_id=bank_a["id"])  # 1000.00
    make_account("Tagesgeld", type="savings", institution_id=bank_a["id"], opening_balance="300.00")
    karte = make_account(
        "Kreditkarte", type="credit_card", institution_id=bank_b["id"], opening_balance="0.00"
    )
    _buche(client, headers, giro["id"], "-100.00")  # Giro: 1000.00 - 100.00 = 900.00
    _buche(client, headers, karte["id"], "-40.00")  # Karte: 0.00 - 40.00 = -40.00

    # Tagesgeld ohne Buchungen: 300.00
    assert _salden(client, headers, "2026-12-31", institution_id=bank_a["id"]) == {
        "Giro": "900.00", "Tagesgeld": "300.00",
    }
    assert _salden(client, headers, "2026-12-31", institution_id=bank_b["id"]) == {
        "Kreditkarte": "-40.00",
    }
    assert _salden(client, headers, "2026-12-31", type="savings") == {"Tagesgeld": "300.00"}


def test_konto_ohne_buchungen_erscheint_mit_dem_anfangssaldo(client, headers, make_account):
    gebucht = make_account("Gebucht")  # 1000.00
    make_account("Leer", opening_balance="75.50")
    _buche(client, headers, gebucht["id"], "-10.00")  # 1000.00 - 10.00 = 990.00
    assert _salden(client, headers, "2026-12-31") == {"Gebucht": "990.00", "Leer": "75.50"}


# --- Isolation zwischen Profilen ------------------------------------------------


def test_buchungen_anderer_profile_veraendern_die_eigenen_salden_nicht(
    client, headers, other_user, make_account
):
    kim = other_user["headers"]
    mein_giro = make_account("Giro")  # 1000.00 zu Beginn von 2026-01-01
    kims_giro = make_account("Giro", hdrs=kim, opening_balance="5000.00")
    _buche(client, headers, mein_giro["id"], "-100.00", "2026-02-01")
    _buche(client, kim, kims_giro["id"], "-2000.00", "2026-02-01")
    _buche(client, kim, kims_giro["id"], "123.45", "2026-02-02")

    # Eigener Saldo: 1000.00 - 100.00 = 900.00
    assert _balance(client, headers, mein_giro["id"], "2026-12-31") == "900.00"
    # Saldo des anderen Profils: 5000.00 - 2000.00 + 123.45 = 3123.45
    assert _balance(client, kim, kims_giro["id"], "2026-12-31") == "3123.45"
    # Jede Liste enthält nur die eigenen Konten
    assert _salden(client, headers, "2026-12-31") == {"Giro": "900.00"}
    assert _salden(client, kim, "2026-12-31") == {"Giro": "3123.45"}


def test_fremde_zugriffe_veraendern_keinen_saldo(client, headers, other_user, make_account):
    kim = other_user["headers"]
    mein_giro = make_account("Giro")  # 1000.00 zu Beginn von 2026-01-01
    kims_giro = make_account("Giro", hdrs=kim, opening_balance="500.00")

    def umbuchung(von, nach, absender):
        return client.post(
            "/transfers",
            json={"from_account_id": von["id"], "to_account_id": nach["id"],
                  "booking_date": "2026-02-01", "amount": "100.00"},
            headers=absender,
        )

    # Weder Buchungen noch Umbuchungen auf fremde Konten, in keine Richtung
    assert _tx(client, kim, mein_giro["id"], "-1.00").status_code == 404
    assert _tx(client, headers, kims_giro["id"], "-1.00").status_code == 404
    assert umbuchung(mein_giro, kims_giro, headers).status_code == 404
    assert umbuchung(kims_giro, mein_giro, kim).status_code == 404
    # Auch der Saldo des fremden Kontos ist nicht abrufbar
    assert client.get(f"/accounts/{kims_giro['id']}", headers=headers).status_code == 404

    # Beide Salden sind unverändert: 1000.00 und 500.00
    assert _balance(client, headers, mein_giro["id"], "2026-12-31") == "1000.00"
    assert _balance(client, kim, kims_giro["id"], "2026-12-31") == "500.00"


# --- Rundung --------------------------------------------------------------------


def test_viele_kleine_betraege_summieren_sich_ohne_float_fehler(client, headers, make_account):
    konto = make_account("Kleinkram", opening_balance="0.00")
    # Zehn Buchungen zu -0.10 (1. bis 10. Februar) und drei zu +0.33 (11. bis 13. Februar)
    for tag in range(1, 11):
        _buche(client, headers, konto["id"], "-0.10", f"2026-02-{tag:02d}")
    for tag in range(11, 14):
        _buche(client, headers, konto["id"], "0.33", f"2026-02-{tag:02d}")

    # Jeder Zwischenstand ist exakt (mit float käme z. B. -0.30000000000000004 bzw. am Ende
    # -0.009999999999999898 heraus)
    erwartet = {
        "2026-02-01": "-0.10",  # 1 x -0.10
        "2026-02-03": "-0.30",  # 3 x -0.10
        "2026-02-10": "-1.00",  # 10 x -0.10
        "2026-02-11": "-0.67",  # -1.00 + 0.33
        "2026-02-12": "-0.34",  # -0.67 + 0.33
        "2026-02-13": "-0.01",  # 0.00 - 10 x 0.10 + 3 x 0.33 = -1.00 + 0.99
    }
    for as_of, saldo in erwartet.items():
        assert _balance(client, headers, konto["id"], as_of) == saldo, as_of
