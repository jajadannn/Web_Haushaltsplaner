"""Banken: Anlegen, BIC-Validierung, Eindeutigkeit je Profil, PATCH-Semantik, Löschen, Isolation."""

from datetime import datetime

import pytest


def _fehler(response, status, code=None):
    """Prüft Status und das einheitliche Fehlerformat; gibt den Fehlerblock zurück."""
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert set(error) == {"code", "message", "details"}
    assert isinstance(error["message"], str) and error["message"]
    if code is not None:
        assert error["code"] == code
    return error


def test_bank_anlegen_antwortformat(client, headers):
    response = client.post("/institutions", json={"name": "Sparkasse", "bic": "COBADEFFXXX"}, headers=headers)
    assert response.status_code == 201, response.text
    bank = response.json()
    assert {"id", "name", "bic", "created_at"} <= set(bank)
    assert isinstance(bank["id"], int)
    assert bank["name"] == "Sparkasse"
    assert bank["bic"] == "COBADEFFXXX"
    datetime.fromisoformat(bank["created_at"])  # gültiger Zeitstempel

    # Die BIC ist optional: fehlend oder explizit null
    for payload in [{"name": "DKB"}, {"name": "ING", "bic": None}]:
        response = client.post("/institutions", json=payload, headers=headers)
        assert response.status_code == 201, response.text
        assert response.json()["bic"] is None


@pytest.mark.parametrize("bic", ["COBADEFFXXX", "COBADEFF", "DEUTDEFF500", "GENODEF1S04"])
def test_gueltige_bic(client, headers, bic):
    response = client.post("/institutions", json={"name": "Bank", "bic": bic}, headers=headers)
    assert response.status_code == 201, response.text
    assert response.json()["bic"] == bic


@pytest.mark.parametrize(
    "bic",
    ["cobadeff", "COBA", "COBADEFFXX", "COBADEFFXXXX", "COBA1EFF", "COBADEF!", ""],
    ids=[
        "kleinbuchstaben",
        "zu_kurz",
        "10_zeichen",
        "12_zeichen",
        "ziffer_im_laendercode",
        "sonderzeichen",
        "leer",
    ],
)
def test_ungueltige_bic_gibt_422(client, headers, bic):
    response = client.post("/institutions", json={"name": "Bank", "bic": bic}, headers=headers)
    error = _fehler(response, 422, "validation_error")
    assert error["details"][0]["loc"][:2] == ["body", "bic"]  # die BIC ist der Grund, nicht der Name
    assert client.get("/institutions", headers=headers).json() == []  # nichts wurde angelegt


@pytest.mark.parametrize(
    "payload",
    [
        {"name": ""},
        {"name": "x" * 101},
        {"name": None},
        {"bic": "COBADEFF"},
        {"name": "DKB", "iban": "DE89370400440532013000"},
    ],
    ids=["leerer_name", "name_zu_lang", "name_null", "name_fehlt", "unbekanntes_feld"],
)
def test_ungueltige_bankdaten_geben_422(client, headers, payload):
    response = client.post("/institutions", json=payload, headers=headers)
    _fehler(response, 422, "validation_error")
    assert client.get("/institutions", headers=headers).json() == []  # nichts wurde angelegt


def test_bankname_mit_100_zeichen_ist_erlaubt(client, headers):
    for name in ["x" * 100, "ä" * 100]:  # die Grenze zählt Zeichen, nicht Bytes
        response = client.post("/institutions", json={"name": name}, headers=headers)
        assert response.status_code == 201, response.text
        assert response.json()["name"] == name


def test_doppelter_bankname_im_profil_gibt_409(client, headers, make_institution):
    make_institution("Sparkasse", bic="COBADEFFXXX")

    # Der Name entscheidet, auch bei abweichender BIC
    response = client.post("/institutions", json={"name": "Sparkasse", "bic": "GENODEF1"}, headers=headers)
    error = _fehler(response, 409)
    assert error["details"]["constraint"] == "uq_institution_user_id_name"
    assert [b["name"] for b in client.get("/institutions", headers=headers).json()] == ["Sparkasse"]


def test_gleicher_bankname_in_anderem_profil_erlaubt(client, headers, other_user, make_institution):
    fremd = other_user["headers"]
    eigene = make_institution("Sparkasse")
    fremde = make_institution("Sparkasse", hdrs=fremd)
    assert eigene["id"] != fremde["id"]

    assert [b["id"] for b in client.get("/institutions", headers=headers).json()] == [eigene["id"]]
    assert [b["id"] for b in client.get("/institutions", headers=fremd).json()] == [fremde["id"]]

    # Auch Umbenennen auf einen Namen, den nur das andere Profil verwendet, ist erlaubt
    make_institution("DKB", hdrs=fremd)
    response = client.patch(f"/institutions/{eigene['id']}", json={"name": "DKB"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["name"] == "DKB"


def test_banken_nach_name_sortiert_und_nur_eigene(client, headers, other_user, make_institution):
    assert client.get("/institutions", headers=headers).json() == []

    for name in ["Sparkasse", "DKB", "Commerzbank", "ING"]:  # bewusst nicht in Namensreihenfolge angelegt
        make_institution(name)
    make_institution("Fremdbank", hdrs=other_user["headers"])

    response = client.get("/institutions", headers=headers)
    assert response.status_code == 200
    assert [b["name"] for b in response.json()] == ["Commerzbank", "DKB", "ING", "Sparkasse"]

    fremde = client.get("/institutions", headers=other_user["headers"]).json()
    assert [b["name"] for b in fremde] == ["Fremdbank"]


def test_bank_abrufen_und_unbekannte_id_gibt_404(client, headers, make_institution):
    bank = make_institution("Sparkasse", bic="COBADEFFXXX")
    make_institution("DKB")

    response = client.get(f"/institutions/{bank['id']}", headers=headers)
    assert response.status_code == 200
    assert response.json() == bank

    _fehler(client.get("/institutions/999999", headers=headers), 404, "not_found")
    _fehler(client.patch("/institutions/999999", json={"name": "x"}, headers=headers), 404, "not_found")
    _fehler(client.delete("/institutions/999999", headers=headers), 404, "not_found")


def test_patch_aendert_nur_gesetzte_felder(client, headers, make_institution):
    bank = make_institution("Sparkasse", bic="COBADEFFXXX")
    url = f"/institutions/{bank['id']}"

    # Nur den Namen ändern: die BIC bleibt
    response = client.patch(url, json={"name": "Stadtsparkasse"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["name"] == "Stadtsparkasse"
    assert response.json()["bic"] == "COBADEFFXXX"

    # Nur die BIC ändern: der Name bleibt
    response = client.patch(url, json={"bic": "GENODEF1S04"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["name"] == "Stadtsparkasse"
    assert response.json()["bic"] == "GENODEF1S04"

    # Beides zugleich
    response = client.patch(url, json={"name": "Volksbank", "bic": "GENODEF1"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["name"] == "Volksbank"
    assert response.json()["bic"] == "GENODEF1"
    assert response.json()["id"] == bank["id"]
    assert response.json()["created_at"] == bank["created_at"]

    # Leerer Body: nichts ändert sich
    response = client.patch(url, json={}, headers=headers)
    assert response.status_code == 200
    assert response.json()["name"] == "Volksbank"
    assert response.json()["bic"] == "GENODEF1"

    # Die Änderungen sind gespeichert
    assert client.get(url, headers=headers).json() == response.json()


def test_patch_bic_null_entfernt_die_bic(client, headers, make_institution):
    bank = make_institution("Sparkasse", bic="COBADEFFXXX")
    url = f"/institutions/{bank['id']}"

    response = client.patch(url, json={"bic": None}, headers=headers)
    assert response.status_code == 200
    assert response.json()["bic"] is None
    assert response.json()["name"] == "Sparkasse"
    assert client.get(url, headers=headers).json()["bic"] is None

    # Danach lässt sich wieder eine BIC setzen
    response = client.patch(url, json={"bic": "COBADEFF"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["bic"] == "COBADEFF"


@pytest.mark.parametrize(
    "payload",
    [
        {"name": None},
        {"name": ""},
        {"name": "x" * 101},
        {"bic": "cobadeff"},
        {"bic": "COBA"},
        {"saldo": "5"},
        {"user_id": 99},
        {"name": "Neu", "bic": "COBA"},
        {"name": None, "bic": "GENODEF1"},
    ],
    ids=[
        "name_null",
        "leerer_name",
        "name_zu_lang",
        "bic_kleinbuchstaben",
        "bic_zu_kurz",
        "unbekanntes_feld",
        "user_id_nicht_aenderbar",
        "gueltiger_name_ungueltige_bic",
        "name_null_gueltige_bic",
    ],
)
def test_ungueltiges_patch_gibt_422_und_aendert_nichts(client, headers, make_institution, payload):
    bank = make_institution("Sparkasse", bic="COBADEFFXXX")
    response = client.patch(f"/institutions/{bank['id']}", json=payload, headers=headers)
    _fehler(response, 422, "validation_error")
    # Auch gültige Teile eines fehlerhaften Requests werden nicht übernommen
    assert client.get(f"/institutions/{bank['id']}", headers=headers).json() == bank


def test_umbenennen_auf_vorhandenen_namen_gibt_409(client, headers, make_institution):
    make_institution("Sparkasse")
    dkb = make_institution("DKB", bic="GENODEF1S04")

    response = client.patch(
        f"/institutions/{dkb['id']}", json={"name": "Sparkasse", "bic": "COBADEFF"}, headers=headers
    )
    error = _fehler(response, 409)
    assert error["details"]["constraint"] == "uq_institution_user_id_name"
    # Auch die BIC aus dem fehlgeschlagenen Request wurde nicht übernommen
    assert client.get(f"/institutions/{dkb['id']}", headers=headers).json() == dkb

    # Den eigenen Namen erneut zu setzen ist kein Konflikt
    response = client.patch(f"/institutions/{dkb['id']}", json={"name": "DKB"}, headers=headers)
    assert response.status_code == 200


def test_bank_loeschen(client, headers, make_institution):
    bank = make_institution("Sparkasse")
    make_institution("DKB")

    response = client.delete(f"/institutions/{bank['id']}", headers=headers)
    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"/institutions/{bank['id']}", headers=headers).status_code == 404
    assert [b["name"] for b in client.get("/institutions", headers=headers).json()] == ["DKB"]

    # Zweites Löschen: die Bank gibt es nicht mehr
    assert client.delete(f"/institutions/{bank['id']}", headers=headers).status_code == 404

    # Der Name ist danach wieder frei
    make_institution("Sparkasse")


def test_bank_mit_konten_nicht_loeschbar(client, headers, make_institution, make_account):
    sparkasse = make_institution("Sparkasse")
    dkb = make_institution("DKB")
    leer = make_institution("ING")
    make_account("Giro Alltag", institution_id=sparkasse["id"])
    make_account("Tagesgeld", institution_id=sparkasse["id"], type="savings")
    make_account("Giro DKB", institution_id=dkb["id"])

    # Gezählt werden nur die Konten der jeweiligen Bank
    response = client.delete(f"/institutions/{sparkasse['id']}", headers=headers)
    error = _fehler(response, 409, "institution_in_use")
    assert error["details"] == {"accounts": 2}

    response = client.delete(f"/institutions/{dkb['id']}", headers=headers)
    error = _fehler(response, 409, "institution_in_use")
    assert error["details"] == {"accounts": 1}

    # Die Banken sind weiterhin vorhanden; eine Bank ohne Konten lässt sich löschen
    assert client.get(f"/institutions/{sparkasse['id']}", headers=headers).status_code == 200
    assert client.get(f"/institutions/{dkb['id']}", headers=headers).status_code == 200
    assert client.delete(f"/institutions/{leer['id']}", headers=headers).status_code == 204


def test_archiviertes_konto_zaehlt_als_zugeordnet(client, headers, make_institution, make_account):
    bank = make_institution("Sparkasse")
    konto = make_account("Giro", institution_id=bank["id"])
    response = client.post(f"/accounts/{konto['id']}/archive", headers=headers)
    assert response.status_code == 200
    assert response.json()["archived_at"] is not None

    # In der normalen Kontoliste fehlt das archivierte Konto, die Bank bleibt trotzdem gesperrt
    assert client.get("/accounts", params={"institution_id": bank["id"]}, headers=headers).json() == []
    response = client.delete(f"/institutions/{bank['id']}", headers=headers)
    error = _fehler(response, 409, "institution_in_use")
    assert error["details"] == {"accounts": 1}
    assert client.get(f"/institutions/{bank['id']}", headers=headers).status_code == 200


def test_bank_loeschbar_nach_loeschen_oder_umhaengen_der_konten(
    client, headers, make_institution, make_account
):
    alt = make_institution("Sparkasse")
    neu = make_institution("DKB")
    giro = make_account("Giro", institution_id=alt["id"])
    sparen = make_account("Tagesgeld", institution_id=alt["id"], type="savings")
    assert client.delete(f"/institutions/{alt['id']}", headers=headers).status_code == 409

    # Ein Konto wird gelöscht: die Bank hat noch ein Konto
    assert client.delete(f"/accounts/{giro['id']}", headers=headers).status_code == 204
    response = client.delete(f"/institutions/{alt['id']}", headers=headers)
    assert _fehler(response, 409, "institution_in_use")["details"] == {"accounts": 1}

    # Das andere Konto wird der neuen Bank zugeordnet: jetzt lässt sich die alte Bank löschen
    response = client.patch(f"/accounts/{sparen['id']}", json={"institution_id": neu["id"]}, headers=headers)
    assert response.status_code == 200
    assert client.delete(f"/institutions/{alt['id']}", headers=headers).status_code == 204

    # Das umgehängte Konto ist unversehrt
    assert client.get(f"/accounts/{sparen['id']}", headers=headers).json()["institution_id"] == neu["id"]


def test_profil_isolation(client, headers, other_user, make_institution):
    bank = make_institution("Sparkasse", bic="COBADEFFXXX")
    fremd = other_user["headers"]
    url = f"/institutions/{bank['id']}"

    _fehler(client.get(url, headers=fremd), 404, "not_found")
    _fehler(client.patch(url, json={"name": "Gekapert", "bic": None}, headers=fremd), 404, "not_found")
    _fehler(client.delete(url, headers=fremd), 404, "not_found")
    assert client.get("/institutions", headers=fremd).json() == []

    # Die Bank des Besitzers ist unverändert und noch vorhanden
    assert client.get(url, headers=headers).json() == bank


def test_profilheader_pflicht(client, headers, make_institution):
    bank = make_institution("Sparkasse")
    url = f"/institutions/{bank['id']}"
    anfragen = [
        ("GET", "/institutions", None),
        ("POST", "/institutions", {"name": "DKB"}),
        ("GET", url, None),
        ("PATCH", url, {"name": "Neu"}),
        ("DELETE", url, None),
    ]
    for method, pfad, body in anfragen:
        response = client.request(method, pfad, json=body)
        _fehler(response, 400, "profile_required")

        response = client.request(method, pfad, json=body, headers={"X-User-Id": "999999"})
        _fehler(response, 404, "profile_not_found")

    # Ohne gültiges Profil wurde nichts angelegt, geändert oder gelöscht
    assert client.get("/institutions", headers=headers).json() == [bank]
