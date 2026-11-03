"""Heimnetz-Betrieb: Netzsperre, API unter /api und Auslieferung der Oberfläche."""

import pytest
from fastapi.testclient import TestClient

from app.server import create_server


@pytest.fixture
def dist(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>Finanzplaner</title>")
    (tmp_path / "assets" / "app-1234.js").write_text("console.log(1)")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    (tmp_path.parent / "geheim.txt").write_text("nicht ausliefern")
    return tmp_path


def server_client(dist, host="192.168.1.20"):
    return TestClient(create_server(dist), client=(host, 50000))


def test_api_unter_api_praefix(client, dist):  # client: DB-Override der API
    response = server_client(dist).get("/api/users")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("path", ["/", "/buchungen", "/wand", "/kredite/3"])
def test_spa_routen_liefern_index(dist, path):
    response = server_client(dist).get(path)
    assert response.status_code == 200
    assert "<title>Finanzplaner</title>" in response.text
    assert response.headers["cache-control"] == "no-cache"


def test_statische_dateien_und_kein_ausbruch(dist):
    c = server_client(dist)
    assert c.get("/assets/app-1234.js").text == "console.log(1)"
    assert c.get("/favicon.svg").text == "<svg/>"
    assert "nicht ausliefern" not in c.get("/../geheim.txt").text
    assert "nicht ausliefern" not in c.get("/%2e%2e/geheim.txt").text


def test_ohne_build_klare_meldung(tmp_path):
    response = server_client(tmp_path).get("/")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "frontend_not_built"


@pytest.mark.parametrize("host", ["8.8.8.8", "2001:db8::1", "testclient"])
def test_netzsperre_fuer_oberflaeche_und_api(dist, host):
    c = server_client(dist, host)
    for path in ("/", "/api/users", "/api/wall"):
        response = c.get(path)
        assert response.status_code == 403, path
        assert response.json()["error"]["code"] == "local_network_only"


@pytest.mark.parametrize("host", ["127.0.0.1", "10.0.0.7", "172.20.1.1", "192.168.178.40", "::1", "::ffff:192.168.1.5"])
def test_heimnetz_ist_erlaubt(dist, host):
    assert server_client(dist, host).get("/").status_code == 200


def test_upload_grenze_gilt_auch_unter_api(client, dist, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    big = b"x" * (2 * 1024 * 1024)
    response = server_client(dist).post("/api/imports", files={"file": ("a.csv", big)},
                                        data={"import_profile_id": "1"}, headers={"X-User-Id": "1"})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_alter_einstellungsname_gilt_weiter(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("WALL_ALLOWED_NETWORKS", '["10.0.0.0/8"]')
    assert Settings().allowed_networks == ["10.0.0.0/8"]
