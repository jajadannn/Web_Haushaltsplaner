"""Kategorien: Seed, Hierarchie (gleicher Typ, keine Zyklen), Deaktivieren, Merge, Löschen."""

import pytest

from app.services.categories import seed_default_categories


def _create(client, headers, name, type_="expense", **extra):
    response = client.post("/categories", json={"name": name, "type": type_, **extra}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _by_system_key(categories, key):
    return next(c for c in categories if c["system_key"] == key)


def test_neues_profil_hat_standard_und_systemkategorien(client, headers):
    categories = client.get("/categories", headers=headers).json()
    assert len(categories) > 10
    assert {c["type"] for c in categories} == {"income", "expense"}
    zinsen = _by_system_key(categories, "loan_interest")
    gebuehren = _by_system_key(categories, "loan_fees")
    assert zinsen["type"] == gebuehren["type"] == "expense"


def test_seed_ist_idempotent(client, headers, session, user):
    vorher = client.get("/categories", headers=headers).json()
    seed_default_categories(session, user["id"])
    seed_default_categories(session, user["id"])
    nachher = client.get("/categories", headers=headers).json()
    assert len(nachher) == len(vorher)


def test_seed_nach_umbenennung_der_systemkategorie_ohne_dublette(client, headers, session, user):
    zinsen = _by_system_key(client.get("/categories", headers=headers).json(), "loan_interest")
    client.patch(f"/categories/{zinsen['id']}", json={"name": "Zinsen Kredite"}, headers=headers)
    seed_default_categories(session, user["id"])
    alle = client.get("/categories", headers=headers).json()
    assert sum(1 for c in alle if c["system_key"] == "loan_interest") == 1


def test_profile_haben_getrennte_kategorien(client, headers, other_user):
    eigene = {c["id"] for c in client.get("/categories", headers=headers).json()}
    fremde = {c["id"] for c in client.get("/categories", headers=other_user["headers"]).json()}
    assert eigene and fremde and not eigene & fremde


def test_filter_typ_und_aktiv(client, headers):
    einnahmen = client.get("/categories", params={"type": "income"}, headers=headers).json()
    assert einnahmen and all(c["type"] == "income" for c in einnahmen)
    kat = _create(client, headers, "Testkategorie")
    client.patch(f"/categories/{kat['id']}", json={"active": False}, headers=headers)
    aktive = client.get("/categories", params={"active": True}, headers=headers).json()
    assert kat["id"] not in {c["id"] for c in aktive}


def test_unterkategorie_braucht_gleichen_typ(client, headers):
    parent = _create(client, headers, "Hobby")
    response = client.post(
        "/categories", json={"name": "Verkauf", "type": "income", "parent_id": parent["id"]}, headers=headers
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "parent_type_mismatch"


def test_gleicher_name_auf_gleicher_ebene_409_sonst_erlaubt(client, headers):
    a = _create(client, headers, "Hobby")
    b = _create(client, headers, "Urlaub")
    _create(client, headers, "Ausrüstung", parent_id=a["id"])
    _create(client, headers, "Ausrüstung", parent_id=b["id"])  # anderer Elternteil: ok
    response = client.post(
        "/categories", json={"name": "Ausrüstung", "type": "expense", "parent_id": a["id"]}, headers=headers
    )
    assert response.status_code == 409
    response = client.post("/categories", json={"name": "Hobby", "type": "expense"}, headers=headers)
    assert response.status_code == 409  # auch auf oberster Ebene (NULLS NOT DISTINCT)


def test_zyklen_werden_abgewiesen(client, headers):
    a = _create(client, headers, "A")
    b = _create(client, headers, "B", parent_id=a["id"])
    c = _create(client, headers, "C", parent_id=b["id"])
    for parent in (a["id"], c["id"]):
        response = client.patch(f"/categories/{a['id']}", json={"parent_id": parent}, headers=headers)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "category_cycle"
    # Umhängen ohne Zyklus ist erlaubt
    response = client.patch(f"/categories/{c['id']}", json={"parent_id": a["id"]}, headers=headers)
    assert response.status_code == 200
    response = client.patch(f"/categories/{c['id']}", json={"parent_id": None}, headers=headers)
    assert response.json()["parent_id"] is None


def test_fremde_elternkategorie_404(client, headers, other_user):
    fremd = _create(client, other_user["headers"], "Fremd")
    response = client.post(
        "/categories", json={"name": "X", "type": "expense", "parent_id": fremd["id"]}, headers=headers
    )
    assert response.status_code == 404


def test_typwechsel_nur_ohne_unterkategorien(client, headers):
    parent = _create(client, headers, "Eltern")
    _create(client, headers, "Kind", parent_id=parent["id"])
    response = client.patch(f"/categories/{parent['id']}", json={"type": "income"}, headers=headers)
    assert response.status_code == 409
    einzel = _create(client, headers, "Einzeln")
    response = client.patch(f"/categories/{einzel['id']}", json={"type": "income"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["type"] == "income"


def test_systemkategorie_geschuetzt(client, headers):
    zinsen = _by_system_key(client.get("/categories", headers=headers).json(), "loan_interest")
    url = f"/categories/{zinsen['id']}"
    assert client.delete(url, headers=headers).status_code == 409
    assert client.patch(url, json={"active": False}, headers=headers).status_code == 422
    assert client.patch(url, json={"type": "income"}, headers=headers).status_code == 422
    assert client.patch(url, json={"color": "#112233"}, headers=headers).status_code == 200


def test_loeschen_nur_ohne_unterkategorien(client, headers):
    parent = _create(client, headers, "Eltern")
    kind = _create(client, headers, "Kind", parent_id=parent["id"])
    response = client.delete(f"/categories/{parent['id']}", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["details"] == {"children": 1}
    assert client.delete(f"/categories/{kind['id']}", headers=headers).status_code == 204
    assert client.delete(f"/categories/{parent['id']}", headers=headers).status_code == 204


def test_merge_haengt_unterkategorien_um(client, headers):
    quelle = _create(client, headers, "Essen gehen")
    kind = _create(client, headers, "Lieferdienst", parent_id=quelle["id"])
    ziel = _create(client, headers, "Restaurant")
    response = client.post(f"/categories/{quelle['id']}/merge", json={"target_id": ziel["id"]}, headers=headers)
    assert response.status_code == 200
    assert response.json()["id"] == ziel["id"]
    assert client.get(f"/categories/{quelle['id']}", headers=headers).status_code == 404
    assert client.get(f"/categories/{kind['id']}", headers=headers).json()["parent_id"] == ziel["id"]


@pytest.mark.parametrize(
    ("setup", "expected_status", "expected_code"),
    [
        ("same", 422, "merge_same_category"),
        ("other_type", 422, "parent_type_mismatch"),
        ("inactive", 422, "category_inactive"),
        ("descendant", 422, "category_cycle"),
        ("name_clash", 409, "merge_name_clash"),
    ],
)
def test_merge_fehlerfaelle(client, headers, setup, expected_status, expected_code):
    quelle = _create(client, headers, "Quelle")
    if setup == "same":
        ziel = quelle
    elif setup == "other_type":
        ziel = _create(client, headers, "Ziel", "income")
    elif setup == "inactive":
        ziel = _create(client, headers, "Ziel")
        client.patch(f"/categories/{ziel['id']}", json={"active": False}, headers=headers)
    elif setup == "descendant":
        ziel = _create(client, headers, "Ziel", parent_id=quelle["id"])
    else:
        ziel = _create(client, headers, "Ziel")
        _create(client, headers, "Gleich", parent_id=quelle["id"])
        _create(client, headers, "Gleich", parent_id=ziel["id"])
    response = client.post(f"/categories/{quelle['id']}/merge", json={"target_id": ziel["id"]}, headers=headers)
    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code


def test_merge_systemkategorie_verboten(client, headers):
    zinsen = _by_system_key(client.get("/categories", headers=headers).json(), "loan_interest")
    ziel = _create(client, headers, "Ziel")
    response = client.post(f"/categories/{zinsen['id']}/merge", json={"target_id": ziel["id"]}, headers=headers)
    assert response.status_code == 409


def test_farbe_und_icon_validierung(client, headers):
    for payload in ({"color": "rot"}, {"color": "#12345"}, {"icon": "x" * 51}):
        response = client.post("/categories", json={"name": "X", "type": "expense", **payload}, headers=headers)
        assert response.status_code == 422
