# Finanzplaner – Backend

Interner Finanzplaner. Er umfasst Konten bei mehreren Banken, Buchungen mit Aufteilung, Kredite mit Tilgungsplan, den automatischen Import von Kontoauszügen (CSV, OFX, MT940), Kategorisierungsregeln, Berichte und Export.
Das Backend basiert auf FastAPI, SQLModel/SQLAlchemy, PostgreSQL 16 und Alembic. Den Entwicklungsplan beschreibt [`ARBEITSPLAN.md`](ARBEITSPLAN.md).

> **Zugriff:** Profile werden per Header `X-User-Id` gewählt, ein Passwort gibt es nicht. Das ist **kein** Zugriffsschutz.
> API und Datenbank sind deshalb nur lokal erreichbar (`127.0.0.1`). Bevor das System im Netzwerk freigegeben wird, braucht es eine bewusste Entscheidung über den Zugriffsschutz.

## Einrichtung

### Ohne Docker (so ist dieser Rechner eingerichtet)
- `uv` liegt im Projekt unter `.tools/bin/uv`.
- PostgreSQL 16 liegt unter `.pg/` und läuft auf Port **5433**.

```bash
export UV_CACHE_DIR=$PWD/.uv-cache
.tools/bin/uv sync                 # Abhängigkeiten aus uv.lock
scripts/devdb.sh start             # PostgreSQL starten (status | stop | psql)
cp .env.example .env               # Verbindungsdaten prüfen
.venv/bin/alembic upgrade head     # Schema anlegen bzw. aktualisieren
```

### Mit Docker
```bash
docker compose up -d db            # PostgreSQL 16 auf 127.0.0.1:5432
```
Anschließend in `.env` den Port auf `5432` stellen und `alembic upgrade head` ausführen.

### Einstellungen (`.env`)
| Variable | Bedeutung | Standard |
|---|---|---|
| `DATABASE_URL` | Datenbank der Anwendung | `…@127.0.0.1:5433/finanzplaner` |
| `TEST_DATABASE_URL` | eigene Datenbank für Tests, wird bei jedem Testlauf geleert | `…/finanzplaner_test` |
| `IMPORT_DIR` | Import-Verzeichnis | `imports` |
| `TIMEZONE` | Zeitzone für „heute“ | `Europe/Berlin` |
| `CORS_ORIGINS` | erlaubte Frontend-Ursprünge | `["http://localhost:5173"]` |
| `MAX_UPLOAD_MB` | Größenlimit für Uploads | `10` |

## Betrieb
```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000   # API, Doku unter /docs
.venv/bin/python -m app.worker                                # Import-Worker (genau EIN Prozess)
```
Der Worker ist ein eigener Prozess und läuft bewusst nicht im API-Prozess, denn bei mehreren API-Workern gäbe es sonst mehrere Dateibeobachter. Eine Sperrdatei (`IMPORT_DIR/.worker.lock`) verhindert einen zweiten Worker. Bricht die Verarbeitung ab, reiht der Worker den Auftrag wieder ein; nach drei Abbrüchen gilt er als fehlgeschlagen (`processing_aborted`), damit eine fehlerhafte Datei nicht alle weiteren Importe blockiert. Ohne Worker lassen sich wartende Importe auch per `POST /imports/process` verarbeiten.

**Uploads** sind auf `MAX_UPLOAD_MB` begrenzt. Das Limit greift vor dem Zwischenspeichern des Bodys (Antwort 413).

**Datenbankrolle:** Für die lokale Entwicklung genügt der Superuser `postgres` mit `trust`-Anmeldung auf Loopback. Sobald mehrere Personen den Rechner nutzen oder der Dienst im Netz erreichbar ist, gehört die Anwendung auf eine eigene Rolle ohne Superuser-Rechte mit Passwort. Die Tests brauchen eine eigene Datenbank: Ihr Name muss „test“ enthalten, sonst brechen sie vor dem Löschen des Schemas ab.

## Kontoauszüge importieren
1. **Bank** anlegen: `POST /institutions`.
2. **Konten** anlegen: `POST /accounts`, mit IBAN und **Stichtag**. Der Anfangssaldo gilt zu *Beginn* des Stichtags.
3. **Importprofil** je Bank anlegen: `POST /import-profiles`.
   - CSV: Spaltenzuordnung (`column_map`), Trennzeichen, Kodierung, Datumsformat, Vorzeichenlogik.
   - Alternativ `format: ofx` bzw. `mt940`.
   - Das Profil gilt für alle Konten dieser Bank.
4. **Datei einreichen**, auf einem dieser Wege:
   - **Upload:** `POST /imports` (Multipart: `file`, `import_profile_id`, optional `account_id`).
   - **Watch-Ordner:** `POST /watch-folders` legt `imports/inbox/<ordner>/` an.
     - Dateien dort zuerst als `*.part` schreiben und danach umbenennen.
     - Ohne festes Konto ordnet der Worker jede Zeile über die IBAN in der Datei einem Konto der Bank zu. So funktionieren auch mehrere Konten bei derselben Bank.
5. **Klären:** `GET /imports/{id}/rows?open_only=true`.
   - Mögliche Dubletten (`ambiguous`) und Zeilen vor dem Stichtag (`before_opening`) wartet der Import auf eine Entscheidung.
   - Entscheiden per `POST /imports/{id}/rows/resolve`: `import`, `duplicate` oder `skip`, auch als Sammelaktion.
   - Danach übernehmen: `POST /imports/{id}/commit`.
6. **Fehlerfälle:** `failed` bedeutet, dass nichts gebucht wurde. Nach Korrektur des Profils oder mit anderem Konto: `POST /imports/{id}/retry`.

Die Ablage im Import-Verzeichnis:
- `processing/`: unveränderliche Arbeitskopie während der Verarbeitung
- `archive/`: erledigte Dateien
- `failed/`: fehlgeschlagene Dateien

Eine schon erfolgreich verarbeitete Datei wird nicht noch einmal gebucht.

**Dubletten:**
- Eine Bank-ID (OFX FITID) gilt als verlässlich.
- Ohne ID gilt ein Treffer über gleichen Text, Betrag und Tag nur als *mögliche* Dublette, ebenso eine ähnliche manuell erfasste Buchung.
- Nichts wird still verworfen, und Zahlungen, die mehrfach echt vorkommen, bleiben erhalten.

## Fachliche Regeln (Kurzfassung)
- **Saldo** = Anfangssaldo + Buchungen vom Stichtag bis zum Abfragetag. Er wird immer berechnet und nie gespeichert.
- **Umbuchungen** (`kind: transfer`, `POST /transfers`) ändern Kontostände, zählen aber nicht als Einnahme oder Ausgabe.
- **Erstattungen** werden in ihrer Kategorie verrechnet: −100 € und +30 € ergeben 70 € Ausgabe.
- **Splits:** Eine Buchung kann auf mehrere Kategorien bzw. Arten aufgeteilt werden. Die Summe der Zeilen muss dem Betrag entsprechen; das prüft auch die Datenbank.
- **Kredite** (`/loans`): Annuitätendarlehen, Tilgungsdarlehen/Ratenkredit und Privatkredit.
  - Jede Rate wird aufgeteilt: Tilgung ist eine Umbuchung aufs Kreditkonto, Zinsen und Gebühren sind Ausgaben.
  - Nach jeder Zahlung wird der Plan ab der tatsächlichen Restschuld neu berechnet.
  - Bei vereinbarter Laufzeit ist die Rate am Laufzeitende die **Schlussrate**: Sie gleicht jeden Rundungsrest aus, es gibt nie mehr Raten als vereinbart. Eine Ratenpause verlängert die Laufzeit um einen Monat.
  - Importierte Raten werden erkannt: automatisch, wenn der Betrag exakt passt, sonst als Vorschlag in der Prüfliste.
- **Regeln** (`/mapping-rules`):
  - Teiltext oder Regex mit Zeitlimit; es gewinnt die Regel mit der kleinsten (priority, id).
  - Manuelle Kategorien werden nie überschrieben.
  - Die Prüfliste (`/review`) zeigt offene und automatisch kategorisierte Buchungen.
- **Berichte** (`/reports/…`): Nettovermögen, Kategorien (Brutto, Erstattung, Netto), Monatstrends ohne Lücken und Kredite. Export als CSV und PDF unter `/export/…`.
- **Löschen:**
  - Konten mit Buchungen werden archiviert.
  - Verwendete Kategorien werden deaktiviert oder zusammengeführt.
  - Importierte Buchungen werden *ausgeschlossen* statt gelöscht.
- Nur **EUR** und nur gebuchte Umsätze. Vorgemerkte Umsätze werden beim Import übersprungen.

## Tests
```bash
.venv/bin/python -m pytest          # Tests
.venv/bin/ruff check app tests      # Linter
```
- **Datenbank:** Die Tests laufen gegen PostgreSQL (`TEST_DATABASE_URL`). Das Schema wird bei jedem Lauf frisch per Alembic aufgebaut; das prüft auch die Migrationen.
- **Isolation:** Jeder Test läuft in einer Transaktion, die am Ende zurückgerollt wird.
- **Import-Verzeichnis:** Import-Tests nutzen ein temporäres Verzeichnis.
- **Beispieldateien:** Anonymisierte Kontoauszüge für die Parser-Tests liegen unter `tests/fixtures/imports/`. Die Bankformate sind nachgebildet und nicht mit echten Exporten verifiziert.

## Sicherung
Siehe [`docs/BACKUP.md`](docs/BACKUP.md): Datenbank-Dump plus Original-Kontoauszüge. CSV- und PDF-Exporte sind keine vollständige Sicherung, weil Regeln, Profile und Importentscheidungen fehlen.
