"""Regressionstests zu docs/PRUEFBERICHT_KI_2026-11-05.md – je Befund der dort beschriebene Nachweis."""

import os
import subprocess
import tarfile
from pathlib import Path

from app.config import get_settings

PROJECT = Path(__file__).resolve().parents[2]


def _env(**extra):
    # nie die Anwendungsdatenbank: Sicherung und Wiederherstellung laufen gegen die Testdatenbank
    return {**os.environ, "DATABASE_URL": get_settings().test_database_url, **extra}


def _backup(tmp_path, imports, documents):
    result = subprocess.run(
        [str(PROJECT / "scripts/backup.sh"), str(tmp_path / "ziel")],
        env=_env(IMPORT_DIR=str(imports), DOCUMENT_DIR=str(documents)),
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    (archive,) = (tmp_path / "ziel").glob("imports_*.tar.gz")
    (dump,) = (tmp_path / "ziel").glob("finanzplaner_*.dump")
    return dump, archive


# N37 – Backup sichert Belege auch ohne Import-Unterordner
def test_n37_backup_ohne_importordner_enthaelt_belege(tmp_path):
    imports, documents = tmp_path / "imports", tmp_path / "docs"
    imports.mkdir()
    (documents / "1").mkdir(parents=True)
    (documents / "1" / "beleg.pdf").write_bytes(b"%PDF-1.4 beleg")
    _, archive = _backup(tmp_path, imports, documents)
    with tarfile.open(archive) as tar:
        assert "documents/1/beleg.pdf" in tar.getnames()


# N38 – Restore bricht bei vorhandenen Belegen ohne --yes ab
def test_n38_restore_ueberschreibt_belege_nicht_ohne_yes(tmp_path):
    imports, documents = tmp_path / "imports", tmp_path / "docs"
    (imports / "archive").mkdir(parents=True)
    documents.mkdir()
    (documents / "beleg.pdf").write_bytes(b"ALT")
    dump, archive = _backup(tmp_path, imports, documents)
    ziel_docs = tmp_path / "ziel-docs"
    ziel_docs.mkdir()
    (ziel_docs / "beleg.pdf").write_bytes(b"VORHANDEN")
    result = subprocess.run(
        [str(PROJECT / "scripts/restore.sh"), str(dump), str(archive), "--target-db", "fin_n38_nie_angelegt"],
        env=_env(IMPORT_DIR=str(tmp_path / "ziel-imports"), DOCUMENT_DIR=str(ziel_docs)),
        capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
    )
    assert result.returncode != 0
    assert "beleg.pdf" in result.stderr
    assert (ziel_docs / "beleg.pdf").read_bytes() == b"VORHANDEN"
