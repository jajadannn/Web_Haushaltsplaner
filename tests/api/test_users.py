"""Profile: Anlegen, Eindeutigkeit, Validierung, Umbenennen, Standardkategorien (alles ohne X-User-Id)."""

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


def test_profil_anlegen_antwortformat(client):
    response = client.post("/users", json={"name": "Alex"})  # bewusst ohne X-User-Id
    assert response.status_code == 201, response.text
    user = response.json()
    assert {"id", "name", "created_at"} <= set(user)
    assert isinstance(user["id"], int)
    assert user["name"] == "Alex"
    datetime.fromisoformat(user["created_at"])  # gültiger Zeitstempel


def test_doppelter_profilname_gibt_409(client, make_user):
    alex = make_user("Alex")
    kategorien = client.get("/categories", headers=alex["headers"]).json()

    response = client.post("/users", json={"name": "Alex"})
    error = _fehler(response, 409)
    assert error["details"]["constraint"] == "uq_app_user_name"

    # Es gibt weiterhin nur ein Profil, und seine Kategorien wurden nicht erneut angelegt
    assert [u["name"] for u in client.get("/users").json()] == ["Alex"]
    assert client.get("/categories", headers=alex["headers"]).json() == kategorien


@pytest.mark.parametrize(
    "payload",
    [{"name": ""}, {"name": "x" * 101}, {"name": None}, {}, {"name": "Alex", "email": "alex@example.org"}],
    ids=["leerer_name", "name_zu_lang", "name_null", "name_fehlt", "unbekanntes_feld"],
)
def test_ungueltige_profildaten_geben_422(client, payload):
    response = client.post("/users", json=payload)
    _fehler(response, 422, "validation_error")
    assert client.get("/users").json() == []  # nichts wurde angelegt


def test_name_mit_100_zeichen_ist_erlaubt(client):
    for name in ["x" * 100, "ä" * 100]:  # die Grenze zählt Zeichen, nicht Bytes
        response = client.post("/users", json={"name": name})
        assert response.status_code == 201, response.text
        assert response.json()["name"] == name


def test_profile_nach_name_sortiert_auflisten(client, make_user):
    assert client.get("/users").json() == []

    for name in ["Mia", "Zoe", "Alex", "Kim"]:  # bewusst nicht in Namensreihenfolge angelegt
        make_user(name)

    response = client.get("/users")  # ohne X-User-Id
    assert response.status_code == 200
    assert [u["name"] for u in response.json()] == ["Alex", "Kim", "Mia", "Zoe"]
    assert all({"id", "name", "created_at"} <= set(u) for u in response.json())


def test_profil_abrufen_und_unbekannte_id_gibt_404(client, make_user):
    alex = make_user("Alex")
    make_user("Kim")

    response = client.get(f"/users/{alex['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == alex["id"]
    assert response.json()["name"] == "Alex"

    response = client.get("/users/999999")
    _fehler(response, 404, "profile_not_found")


def test_profil_umbenennen(client, make_user):
    alex = make_user("Alex")

    response = client.patch(f"/users/{alex['id']}", json={"name": "Neu"})
    assert response.status_code == 200
    assert response.json()["id"] == alex["id"]
    assert response.json()["name"] == "Neu"
    assert response.json()["created_at"] == alex["created_at"]

    assert client.get(f"/users/{alex['id']}").json()["name"] == "Neu"
    assert [u["name"] for u in client.get("/users").json()] == ["Neu"]

    # Leerer Body: fehlende Felder bleiben unverändert
    response = client.patch(f"/users/{alex['id']}", json={})
    assert response.status_code == 200
    assert response.json()["name"] == "Neu"

    # Der alte Name ist danach wieder frei
    make_user("Alex")


@pytest.mark.parametrize(
    "payload",
    [{"name": None}, {"name": ""}, {"name": "x" * 101}, {"alter": 42}],
    ids=["name_null", "leerer_name", "name_zu_lang", "unbekanntes_feld"],
)
def test_ungueltiges_umbenennen_gibt_422(client, make_user, payload):
    alex = make_user("Alex")
    response = client.patch(f"/users/{alex['id']}", json=payload)
    _fehler(response, 422, "validation_error")
    assert client.get(f"/users/{alex['id']}").json()["name"] == "Alex"  # unverändert


def test_unbekanntes_profil_umbenennen_gibt_404(client):
    response = client.patch("/users/999999", json={"name": "Neu"})
    _fehler(response, 404, "profile_not_found")


def test_umbenennen_auf_vorhandenen_namen_gibt_409(client, make_user):
    make_user("Alex")
    kim = make_user("Kim")

    response = client.patch(f"/users/{kim['id']}", json={"name": "Alex"})
    error = _fehler(response, 409)
    assert error["details"]["constraint"] == "uq_app_user_name"
    assert client.get(f"/users/{kim['id']}").json()["name"] == "Kim"  # unverändert

    # Den eigenen Namen erneut zu setzen ist kein Konflikt
    response = client.patch(f"/users/{kim['id']}", json={"name": "Kim"})
    assert response.status_code == 200


def test_neues_profil_bekommt_automatisch_kategorien(client, make_user):
    # Nicht nur das erste, jedes neue Profil bekommt seine Kategorien
    for name in ["Alex", "Kim"]:
        user = make_user(name)
        response = client.get("/categories", headers=user["headers"])
        assert response.status_code == 200
        kategorien = response.json()
        assert kategorien
        system_keys = [k["system_key"] for k in kategorien]
        assert system_keys.count("loan_interest") == 1
        assert system_keys.count("loan_fees") == 1
