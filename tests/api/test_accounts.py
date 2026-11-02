"""Konten: mehrere Konten je Profil bei gleicher/anderer Bank, IBAN, Archivierung, Isolation."""

IBAN_A1 = "DE89370400440532013000"
IBAN_A2 = "DE02120300000000202051"
IBAN_B1 = "DE02500105170137075030"


def test_mehrere_konten_bei_gleicher_und_anderer_bank(client, headers, make_institution, make_account):
    bank_a = make_institution("Sparkasse")
    bank_b = make_institution("DKB")
    make_account("Giro Alltag", institution_id=bank_a["id"], iban=IBAN_A1)
    make_account("Giro Rücklagen", institution_id=bank_a["id"], iban=IBAN_A2, type="savings")
    make_account("Giro DKB", institution_id=bank_b["id"], iban=IBAN_B1)

    alle = client.get("/accounts", headers=headers).json()
    assert [a["name"] for a in alle] == ["Giro Alltag", "Giro DKB", "Giro Rücklagen"]

    nur_a = client.get("/accounts", params={"institution_id": bank_a["id"]}, headers=headers).json()
    assert {a["name"] for a in nur_a} == {"Giro Alltag", "Giro Rücklagen"}

    sparen = client.get("/accounts", params={"type": "savings"}, headers=headers).json()
    assert [a["name"] for a in sparen] == ["Giro Rücklagen"]


def test_konto_antwort_format(make_account):
    account = make_account(iban="de89 3704 0044 0532 0130 00", opening_balance="-12.5")
    assert account["iban"] == IBAN_A1  # normalisiert
    assert account["opening_balance"] == "-12.50"  # Dezimalstring, nie float
    assert account["currency"] == "EUR"
    assert account["archived_at"] is None


def test_doppelte_iban_im_profil_gibt_409(client, headers, make_account):
    make_account("Giro 1", iban=IBAN_A1)
    response = client.post(
        "/accounts",
        json={"name": "Giro 2", "type": "checking", "opening_balance": "0",
              "opening_balance_date": "2026-01-01", "iban": IBAN_A1},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["details"]["constraint"] == "uq_account_user_id_iban_normalized"


def test_gleiche_iban_in_anderem_profil_erlaubt(make_account, other_user):
    make_account("Giro", iban=IBAN_A1)
    make_account("Giro", iban=IBAN_A1, hdrs=other_user["headers"])


def test_doppelter_kontoname_gibt_409(client, headers, make_account):
    make_account("Giro")
    response = client.post(
        "/accounts",
        json={"name": "Giro", "type": "cash", "opening_balance": "0", "opening_balance_date": "2026-01-01"},
        headers=headers,
    )
    assert response.status_code == 409


def test_kontoreferenz_eindeutig_je_bank(client, headers, make_institution, make_account):
    bank_a = make_institution("Sparkasse")
    bank_b = make_institution("DKB")
    make_account("Karte A", type="credit_card", institution_id=bank_a["id"], bank_account_ref="4111-XX-1111")
    make_account("Karte B", type="credit_card", institution_id=bank_b["id"], bank_account_ref="4111-XX-1111")
    response = client.post(
        "/accounts",
        json={"name": "Karte A2", "type": "credit_card", "opening_balance": "0",
              "opening_balance_date": "2026-01-01", "institution_id": bank_a["id"],
              "bank_account_ref": "4111-XX-1111"},
        headers=headers,
    )
    assert response.status_code == 409


def test_ungueltige_iban_gibt_422(client, headers):
    for iban in ["DE89370400440532013001", "DE8937040044", "XX!!"]:
        response = client.post(
            "/accounts",
            json={"name": "Giro", "type": "checking", "opening_balance": "0",
                  "opening_balance_date": "2026-01-01", "iban": iban},
            headers=headers,
        )
        assert response.status_code == 422, iban
        assert response.json()["error"]["code"] in {"invalid_iban", "validation_error"}


def test_geldbetrag_validierung(client, headers):
    for amount in ["1.234", "NaN", "Infinity", "10000000000.00"]:
        response = client.post(
            "/accounts",
            json={"name": "Giro", "type": "checking", "opening_balance": amount,
                  "opening_balance_date": "2026-01-01"},
            headers=headers,
        )
        assert response.status_code == 422, amount


def test_nur_eur(client, headers):
    response = client.post(
        "/accounts",
        json={"name": "Giro", "type": "checking", "opening_balance": "0",
              "opening_balance_date": "2026-01-01", "currency": "USD"},
        headers=headers,
    )
    assert response.status_code == 422


def test_kreditkonto_nur_ueber_loans(client, headers, make_account):
    response = client.post(
        "/accounts",
        json={"name": "Kredit", "type": "loan", "opening_balance": "-5000",
              "opening_balance_date": "2026-01-01"},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "loan_account_via_loans"

    giro = make_account()
    response = client.patch(f"/accounts/{giro['id']}", json={"type": "loan"}, headers=headers)
    assert response.status_code == 422


def test_patch_unterscheidet_fehlend_und_null(client, headers, make_institution, make_account):
    bank = make_institution()
    account = make_account(institution_id=bank["id"], iban=IBAN_A1)

    # Nur Name ändern: IBAN und Bank bleiben
    response = client.patch(f"/accounts/{account['id']}", json={"name": "Neu"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["iban"] == IBAN_A1
    assert response.json()["institution_id"] == bank["id"]

    # Bewusst auf null setzen
    response = client.patch(
        f"/accounts/{account['id']}", json={"iban": None, "institution_id": None}, headers=headers
    )
    assert response.json()["iban"] is None
    assert response.json()["institution_id"] is None

    # Pflichtfelder dürfen nicht null werden
    response = client.patch(f"/accounts/{account['id']}", json={"name": None}, headers=headers)
    assert response.status_code == 422

    # Unbekannte Felder werden abgelehnt
    response = client.patch(f"/accounts/{account['id']}", json={"saldo": "5"}, headers=headers)
    assert response.status_code == 422


def test_archivieren_und_reaktivieren(client, headers, make_account):
    account = make_account()
    response = client.post(f"/accounts/{account['id']}/archive", headers=headers)
    assert response.status_code == 200
    assert response.json()["archived_at"] is not None

    assert client.get("/accounts", headers=headers).json() == []
    archiviert = client.get("/accounts", params={"include_archived": True}, headers=headers).json()
    assert [a["id"] for a in archiviert] == [account["id"]]

    response = client.post(f"/accounts/{account['id']}/unarchive", headers=headers)
    assert response.json()["archived_at"] is None


def test_konto_loeschen(client, headers, make_account):
    account = make_account()
    assert client.delete(f"/accounts/{account['id']}", headers=headers).status_code == 204
    assert client.get(f"/accounts/{account['id']}", headers=headers).status_code == 404


def test_profil_isolation(client, headers, other_user, make_account, make_institution):
    account = make_account()
    fremd = other_user["headers"]
    assert client.get(f"/accounts/{account['id']}", headers=fremd).status_code == 404
    assert client.patch(f"/accounts/{account['id']}", json={"name": "x"}, headers=fremd).status_code == 404
    assert client.delete(f"/accounts/{account['id']}", headers=fremd).status_code == 404
    assert client.get("/accounts", headers=fremd).json() == []

    # Fremde Bank kann nicht zugeordnet werden
    fremde_bank = make_institution("Fremdbank", hdrs=fremd)
    response = client.post(
        "/accounts",
        json={"name": "Giro X", "type": "checking", "opening_balance": "0",
              "opening_balance_date": "2026-01-01", "institution_id": fremde_bank["id"]},
        headers=headers,
    )
    assert response.status_code == 404


def test_profilheader_pflicht(client, user):
    response = client.get("/accounts")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "profile_required"

    response = client.get("/accounts", headers={"X-User-Id": "999999"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "profile_not_found"
