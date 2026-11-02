"""Buchungen: Anlage, Splits, Umbuchungen, Ausschluss importierter Buchungen, Filter."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models import Transaction


def _category(client, headers, system_key=None, name=None):
    categories = client.get("/categories", headers=headers).json()
    if system_key:
        return next(c for c in categories if c["system_key"] == system_key)
    return next(c for c in categories if c["name"] == name)


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


# --- Anlage & Kategorisierung -------------------------------------------------


def test_buchung_mit_kategorie_ist_bestaetigt(client, headers, make_account):
    giro = make_account()
    kat = _expense(client, headers)
    response = _tx(client, headers, giro["id"], "-42.10", category_id=kat["id"])
    assert response.status_code == 201
    tx = response.json()
    assert tx["amount"] == "-42.10"
    assert tx["review_status"] == "confirmed"
    assert tx["category_source"] == "manual"
    assert tx["source"] == "manual"
    assert tx["splits"] == []


def test_buchung_ohne_kategorie_landet_in_pruefung(client, headers, make_account):
    giro = make_account()
    tx = _tx(client, headers, giro["id"], "-5.00").json()
    assert tx["review_status"] == "needs_review"
    assert tx["category_source"] == "none"


def test_erstattung_in_ausgabenkategorie_erlaubt(client, headers, make_account):
    giro = make_account()
    kat = _expense(client, headers, "Shopping-Test")
    assert _tx(client, headers, giro["id"], "-100.00", category_id=kat["id"]).status_code == 201
    assert _tx(client, headers, giro["id"], "30.00", category_id=kat["id"]).status_code == 201


@pytest.mark.parametrize("amount", ["0", "0.00", "1.001", "abc"])
def test_ungueltige_betraege(client, headers, make_account, amount):
    giro = make_account()
    assert _tx(client, headers, giro["id"], amount).status_code == 422


def test_vor_stichtag_abgelehnt(client, headers, make_account):
    giro = make_account(opening_balance_date="2026-01-15")
    response = _tx(client, headers, giro["id"], "-1.00", booking_date="2026-01-14")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "before_opening"
    assert _tx(client, headers, giro["id"], "-1.00", booking_date="2026-01-15").status_code == 201


def test_archiviertes_konto_nimmt_keine_buchungen(client, headers, make_account):
    giro = make_account()
    client.post(f"/accounts/{giro['id']}/archive", headers=headers)
    response = _tx(client, headers, giro["id"], "-1.00")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "account_archived"


def test_deaktivierte_kategorie_nicht_neu_zuordenbar(client, headers, make_account):
    giro = make_account()
    kat = _expense(client, headers)
    tx = _tx(client, headers, giro["id"], "-1.00", category_id=kat["id"]).json()
    client.patch(f"/categories/{kat['id']}", json={"active": False}, headers=headers)
    response = _tx(client, headers, giro["id"], "-1.00", category_id=kat["id"])
    assert response.json()["error"]["code"] == "category_inactive"
    # Bestehende Zuordnung bleibt editierbar
    response = client.patch(f"/transactions/{tx['id']}", json={"description": "neu"}, headers=headers)
    assert response.status_code == 200


def test_fremde_konten_und_kategorien(client, headers, other_user, make_account):
    fremd = other_user["headers"]
    fremdes_konto = make_account("Fremd", hdrs=fremd)
    fremde_kat = _expense(client, fremd, "Fremdkategorie")
    eigenes = make_account()
    assert _tx(client, headers, fremdes_konto["id"], "-1.00").status_code == 404
    assert _tx(client, headers, eigenes["id"], "-1.00", category_id=fremde_kat["id"]).status_code == 404
    tx = _tx(client, headers, eigenes["id"], "-1.00").json()
    assert client.get(f"/transactions/{tx['id']}", headers=fremd).status_code == 404


def test_transfer_hat_keine_kategorie(client, headers, make_account):
    giro = make_account()
    kat = _expense(client, headers)
    response = _tx(client, headers, giro["id"], "-1.00", kind="transfer", category_id=kat["id"])
    assert response.json()["error"]["code"] == "transfer_without_category"
    tx = _tx(client, headers, giro["id"], "-1.00", kind="transfer").json()
    assert tx["review_status"] == "confirmed"


# --- Splits -------------------------------------------------------------------


def test_split_buchung(client, headers, make_account):
    giro = make_account()
    a = _expense(client, headers, "A")
    b = _expense(client, headers, "B")
    response = _tx(
        client, headers, giro["id"], "-100.00",
        splits=[{"amount": "-70.00", "category_id": a["id"]}, {"amount": "-30.00", "category_id": b["id"]}],
    )
    assert response.status_code == 201, response.text
    tx = response.json()
    assert [(s["line_no"], s["amount"]) for s in tx["splits"]] == [(1, "-70.00"), (2, "-30.00")]
    assert tx["category_id"] is None
    assert tx["review_status"] == "confirmed"


@pytest.mark.parametrize(
    ("splits", "extra", "code"),
    [
        ([{"amount": "-70.00"}, {"amount": "-20.00"}], {}, "split_sum_mismatch"),
        ([{"amount": "-100.00"}], {}, "split_too_few"),
        ([{"amount": "-70.00"}, {"amount": "-30.00"}], {"kind": "transfer"}, "split_on_line_level"),
    ],
)
def test_split_fehler(client, headers, make_account, splits, extra, code):
    giro = make_account()
    response = _tx(client, headers, giro["id"], "-100.00", splits=splits, **extra)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


def test_split_mit_transfer_zeile_und_teilweise_kategorisiert(client, headers, make_account):
    giro = make_account()
    zinsen = _category(client, headers, system_key="loan_interest")
    tx = _tx(
        client, headers, giro["id"], "-500.00",
        splits=[{"amount": "-380.00", "kind": "transfer"}, {"amount": "-120.00", "category_id": zinsen["id"]}],
    ).json()
    assert tx["review_status"] == "confirmed"
    tx = _tx(
        client, headers, giro["id"], "-500.00",
        splits=[{"amount": "-380.00", "kind": "transfer"}, {"amount": "-120.00"}],
    ).json()
    assert tx["review_status"] == "needs_review"


def test_split_aendern_und_entfernen(client, headers, make_account):
    giro = make_account()
    a = _expense(client, headers, "A")
    tx = _tx(client, headers, giro["id"], "-100.00",
             splits=[{"amount": "-60.00", "category_id": a["id"]}, {"amount": "-40.00"}]).json()
    url = f"/transactions/{tx['id']}"

    # Betrag ändern, ohne Zeilen anzupassen -> Summe passt nicht mehr
    assert client.patch(url, json={"amount": "-90.00"}, headers=headers).status_code == 422

    response = client.patch(
        url,
        json={"amount": "-90.00", "splits": [{"amount": "-50.00", "category_id": a["id"]},
                                             {"amount": "-40.00", "category_id": a["id"]}]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert [s["amount"] for s in response.json()["splits"]] == ["-50.00", "-40.00"]
    assert response.json()["review_status"] == "confirmed"

    response = client.patch(url, json={"splits": None, "category_id": a["id"]}, headers=headers)
    assert response.json()["splits"] == []
    assert response.json()["category_id"] == a["id"]


def test_datenbank_erzwingt_split_summe(session, client, headers, make_account):
    """Letzte Absicherung neben dem Service: der Constraint-Trigger in PostgreSQL."""
    giro = make_account()
    tx = _tx(client, headers, giro["id"], "-100.00",
             splits=[{"amount": "-60.00"}, {"amount": "-40.00"}]).json()
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.execute(
                text("UPDATE transaction_split SET amount = -10 WHERE transaction_id = :id AND line_no = 1"),
                {"id": tx["id"]},
            )


# --- Ändern / Löschen ---------------------------------------------------------


def test_kategorie_setzen_bestaetigt(client, headers, make_account):
    giro = make_account()
    kat = _expense(client, headers)
    tx = _tx(client, headers, giro["id"], "-5.00").json()
    response = client.patch(f"/transactions/{tx['id']}", json={"category_id": kat["id"]}, headers=headers)
    assert response.json()["review_status"] == "confirmed"
    response = client.patch(f"/transactions/{tx['id']}", json={"category_id": None}, headers=headers)
    assert response.json()["review_status"] == "needs_review"


def test_kontowechsel_manueller_buchung(client, headers, make_account):
    a = make_account("A")
    b = make_account("B", opening_balance_date="2026-03-01")
    tx = _tx(client, headers, a["id"], "-5.00").json()
    response = client.patch(f"/transactions/{tx['id']}", json={"account_id": b["id"]}, headers=headers)
    assert response.json()["error"]["code"] == "before_opening"
    response = client.patch(
        f"/transactions/{tx['id']}", json={"account_id": b["id"], "booking_date": "2026-03-02"}, headers=headers
    )
    assert response.status_code == 200
    assert _balance(client, headers, a["id"], "2026-12-31") == "1000.00"
    assert _balance(client, headers, b["id"], "2026-12-31") == "995.00"


def test_manuelle_buchung_loeschen(client, headers, make_account):
    giro = make_account()
    tx = _tx(client, headers, giro["id"], "-5.00").json()
    assert client.delete(f"/transactions/{tx['id']}", headers=headers).status_code == 204
    assert client.get(f"/transactions/{tx['id']}", headers=headers).status_code == 404


def _as_imported(session, tx_id):
    session.get(Transaction, tx_id).source = "import"
    session.flush()


def test_importierte_buchung_ausschliessen_statt_loeschen(client, headers, session, make_account):
    giro = make_account()
    tx = _tx(client, headers, giro["id"], "-200.00").json()
    _as_imported(session, tx["id"])
    url = f"/transactions/{tx['id']}"

    response = client.delete(url, headers=headers)
    assert response.json()["error"]["code"] == "imported_use_exclude"
    response = client.patch(url, json={"amount": "-1.00"}, headers=headers)
    assert response.json()["error"]["code"] == "imported_fields_fixed"
    assert client.patch(url, json={"description": "ok"}, headers=headers).status_code == 200

    assert _balance(client, headers, giro["id"], "2026-12-31") == "800.00"
    response = client.post(f"{url}/exclude", json={"reason": "Doppelt gebucht"}, headers=headers)
    assert response.json()["excluded_at"] is not None
    assert _balance(client, headers, giro["id"], "2026-12-31") == "1000.00"

    listed = client.get("/transactions", headers=headers).json()
    assert listed["total"] == 0
    listed = client.get("/transactions", params={"include_excluded": True}, headers=headers).json()
    assert listed["total"] == 1

    client.post(f"{url}/include", headers=headers)
    assert _balance(client, headers, giro["id"], "2026-12-31") == "800.00"


def test_manuelle_buchung_nicht_ausschliessbar(client, headers, make_account):
    giro = make_account()
    tx = _tx(client, headers, giro["id"], "-5.00").json()
    response = client.post(f"/transactions/{tx['id']}/exclude", json={"reason": "x"}, headers=headers)
    assert response.json()["error"]["code"] == "manual_use_delete"


# --- Umbuchungen --------------------------------------------------------------


def test_umbuchung_zwischen_banken(client, headers, make_institution, make_account):
    giro = make_account("Giro", institution_id=make_institution("Sparkasse")["id"])
    tagesgeld = make_account("Tagesgeld", type="savings", opening_balance="0",
                             institution_id=make_institution("DKB")["id"])
    response = client.post(
        "/transfers",
        json={"from_account_id": giro["id"], "to_account_id": tagesgeld["id"],
              "booking_date": "2026-02-01", "amount": "250.00"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    out, inc = response.json()["outgoing"], response.json()["incoming"]
    assert (out["amount"], inc["amount"]) == ("-250.00", "250.00")
    assert out["kind"] == inc["kind"] == "transfer"
    assert out["transfer_peer_id"] == inc["id"] and inc["transfer_peer_id"] == out["id"]
    assert _balance(client, headers, giro["id"], "2026-12-31") == "750.00"
    assert _balance(client, headers, tagesgeld["id"], "2026-12-31") == "250.00"

    # Gekoppelte Seite: Betrag nicht einseitig änderbar
    response = client.patch(f"/transactions/{out['id']}", json={"amount": "-1.00"}, headers=headers)
    assert response.json()["error"]["code"] == "transfer_pair_linked"
    # Löschen einer Seite löscht beide – sonst entstünde Geld aus dem Nichts
    assert client.delete(f"/transactions/{out['id']}", headers=headers).status_code == 204
    assert client.get(f"/transactions/{inc['id']}", headers=headers).status_code == 404
    assert _balance(client, headers, giro["id"], "2026-12-31") == "1000.00"
    assert _balance(client, headers, tagesgeld["id"], "2026-12-31") == "0.00"


@pytest.mark.parametrize("case", ["same", "negative"])
def test_umbuchung_fehler(client, headers, make_account, case):
    a = make_account("A")
    b = make_account("B")
    payload = {"from_account_id": a["id"], "to_account_id": b["id"], "booking_date": "2026-02-01", "amount": "5.00"}
    if case == "same":
        payload["to_account_id"] = a["id"]
    else:
        payload["amount"] = "-5.00"
    assert client.post("/transfers", json=payload, headers=headers).status_code == 422


# --- Liste & Filter -----------------------------------------------------------


def test_liste_sortierung_pagination_und_filter(client, headers, make_institution, make_account):
    bank = make_institution("Sparkasse")
    a = make_account("A", institution_id=bank["id"])
    b = make_account("B")
    eltern = _expense(client, headers, "Eltern")
    kind = client.post("/categories", json={"name": "Kind", "type": "expense", "parent_id": eltern["id"]},
                       headers=headers).json()
    t1 = _tx(client, headers, a["id"], "-10.00", booking_date="2026-02-01", description="REWE Markt").json()
    t2 = _tx(client, headers, a["id"], "-20.00", booking_date="2026-02-03", category_id=kind["id"]).json()
    t3 = _tx(client, headers, b["id"], "15.00", booking_date="2026-02-03", counterparty="Arbeitgeber 50%").json()
    t4 = _tx(client, headers, b["id"], "-7.00", booking_date="2026-02-02",
             splits=[{"amount": "-5.00", "category_id": eltern["id"]}, {"amount": "-2.00"}]).json()

    def ids(**params):
        return [t["id"] for t in client.get("/transactions", params=params, headers=headers).json()["items"]]

    # booking_date absteigend, bei gleichem Datum id absteigend
    assert ids() == [t3["id"], t2["id"], t4["id"], t1["id"]]
    page = client.get("/transactions", params={"limit": 2, "offset": 1}, headers=headers).json()
    assert [t["id"] for t in page["items"]] == [t2["id"], t4["id"]] and page["total"] == 4

    assert ids(date_from="2026-02-02", date_to="2026-02-02") == [t4["id"]]  # inklusive Grenzen
    assert ids(account_ids=[b["id"]]) == [t3["id"], t4["id"]]
    assert ids(institution_id=bank["id"]) == [t2["id"], t1["id"]]
    assert ids(category_id=eltern["id"]) == [t2["id"], t4["id"]]  # inkl. Unterkategorie & Split
    assert ids(category_id=eltern["id"], include_subcategories=False) == [t4["id"]]
    assert ids(search="rewe") == [t1["id"]]
    assert ids(search="50%") == [t3["id"]]  # % wird nicht als Platzhalter interpretiert
    assert ids(amount_min="0") == [t3["id"]]
    assert ids(uncategorized=True) == [t3["id"], t4["id"], t1["id"]]
    assert ids(review_status="confirmed") == [t2["id"]]
    assert client.get("/transactions", params={"limit": 500}, headers=headers).status_code == 422


# --- Auswirkungen auf Konten & Kategorien ---------------------------------------


def test_konto_mit_buchungen_nur_archivierbar(client, headers, make_account):
    giro = make_account()
    _tx(client, headers, giro["id"], "-5.00")
    response = client.delete(f"/accounts/{giro['id']}", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "account_in_use"


def test_stichtag_nicht_hinter_vorhandene_buchungen(client, headers, make_account):
    giro = make_account()
    _tx(client, headers, giro["id"], "-5.00", booking_date="2026-02-01")
    response = client.patch(f"/accounts/{giro['id']}", json={"opening_balance_date": "2026-03-01"}, headers=headers)
    assert response.json()["error"]["code"] == "transactions_before_opening"
    response = client.patch(f"/accounts/{giro['id']}", json={"opening_balance_date": "2025-12-01"}, headers=headers)
    assert response.status_code == 200


def test_benutzte_kategorie_nicht_loeschbar_aber_zusammenfuehrbar(client, headers, make_account):
    giro = make_account()
    quelle = _expense(client, headers, "Quelle")
    ziel = _expense(client, headers, "Ziel")
    tx = _tx(client, headers, giro["id"], "-5.00", category_id=quelle["id"]).json()
    split_tx = _tx(client, headers, giro["id"], "-9.00",
                   splits=[{"amount": "-4.00", "category_id": quelle["id"]}, {"amount": "-5.00"}]).json()

    response = client.delete(f"/categories/{quelle['id']}", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["details"] == {"transactions": 1, "splits": 1}
    assert client.patch(f"/categories/{quelle['id']}", json={"type": "income"}, headers=headers).status_code == 409

    response = client.post(f"/categories/{quelle['id']}/merge", json={"target_id": ziel["id"]}, headers=headers)
    assert response.status_code == 200
    assert client.get(f"/transactions/{tx['id']}", headers=headers).json()["category_id"] == ziel["id"]
    lines = client.get(f"/transactions/{split_tx['id']}", headers=headers).json()["splits"]
    assert lines[0]["category_id"] == ziel["id"]
