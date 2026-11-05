# Finanzplaner

Interner Finanzplaner. Er umfasst Konten bei mehreren Banken, Buchungen mit Aufteilung, Kredite mit Tilgungsplan, den automatischen Import von Kontoauszügen (CSV, OFX, MT940), Kategorisierungsregeln, Berichte und Export.
Das Backend basiert auf FastAPI, SQLModel/SQLAlchemy, PostgreSQL 16 und Alembic. Den Entwicklungsplan beschreibt [`ARBEITSPLAN.md`](ARBEITSPLAN.md).

> **Zugriff:** Profile werden per Header `X-User-Id` gewählt, ein Passwort gibt es nicht. Das ist **kein** Zugriffsschutz.
> Deshalb antworten API und Oberfläche nur Geräten aus dem Heimnetz (`ALLOWED_NETWORKS`, Standard: Loopback und private
> Adressbereiche). Wer im WLAN ist, kann jedes Profil öffnen und ändern – Gäste-WLAN getrennt halten.

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
| `ALLOWED_NETWORKS` | Netze, die API und Oberfläche nutzen dürfen (früher `WALL_ALLOWED_NETWORKS`) | Loopback + private Netze |

## Betrieb
```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000   # API, Doku unter /docs
.venv/bin/python -m app.worker                                # Import-Worker (genau EIN Prozess)
```
Der Worker ist ein eigener Prozess und läuft bewusst nicht im API-Prozess, denn bei mehreren API-Workern gäbe es sonst mehrere Dateibeobachter. Eine Sperrdatei (`IMPORT_DIR/.worker.lock`) verhindert einen zweiten Worker. Bricht die Verarbeitung ab, reiht der Worker den Auftrag wieder ein; nach drei Abbrüchen gilt er als fehlgeschlagen (`processing_aborted`), damit eine fehlerhafte Datei nicht alle weiteren Importe blockiert. Ohne Worker lassen sich wartende Importe auch per `POST /imports/process` verarbeiten.

**Uploads** sind auf `MAX_UPLOAD_MB` begrenzt. Das Limit greift vor dem Zwischenspeichern des Bodys (Antwort 413).

**Datenbankrolle:** Für die lokale Entwicklung genügt der Superuser `postgres` mit `trust`-Anmeldung auf Loopback. Sobald mehrere Personen den Rechner nutzen oder der Dienst im Netz erreichbar ist, gehört die Anwendung auf eine eigene Rolle ohne Superuser-Rechte mit Passwort. Die Tests brauchen eine eigene Datenbank: Ihr Name muss „test“ enthalten, sonst brechen sie vor dem Löschen des Schemas ab.

## Oberfläche (Frontend)

React + Vite + TypeScript in `frontend/`. Wanddisplay unter `/wand`, persönliche Ansicht unter `/`.

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173 – leitet /api an die API auf 127.0.0.1:8000 weiter
npm run gen:api      # API-Typen (src/api/schema.d.ts) nach Backend-Änderungen neu erzeugen
npm test             # Unit-Tests (Vitest)
npm run build        # Produktionsbuild nach frontend/dist
```

**Demo-Daten zum Ausprobieren:** `.venv/bin/python scripts/seed_demo.py` legt die eigene Datenbank `finanzplaner_demo`
neu an (Profile Fabian und Lea, Konten, Fixkosten, Autokredit, Buchungen). Die echte Datenbank bleibt unberührt.
API dagegen starten: `DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5433/finanzplaner_demo .venv/bin/uvicorn app.main:app --port 8000`.
Durchklick-Tests im Browser (brauchen die Demo-API und `npm run dev`): `node e2e/paket1.mjs`, `paket2.mjs`, `paket3.mjs`, `paket4.mjs` (KI-Funktionen, läuft ohne KI-Server).

## Im Heimnetz betreiben

Ein Prozess liefert Oberfläche und API über einen Port aus (API unter `/api`):

```bash
npm --prefix frontend run build
.venv/bin/uvicorn app.server:app --host 0.0.0.0 --port 8000
.venv/bin/python -m app.worker        # Import-Worker
```

Danach im WLAN: `http://<rechner>:8000/` (persönlich, am Handy „Zum Home-Bildschirm“) und `http://<rechner>:8000/wand`
fürs Wanddisplay (Browser im Vollbild/Kiosk-Modus). Anfragen von außerhalb der erlaubten Netze bekommen 403
`local_network_only`. Den Port nicht im Router nach außen freigeben.

### Mit Docker betreiben

Das `Dockerfile` baut die Oberfläche und packt sie mit der API in ein Image. `docker-compose.yml` startet drei Container:

| Dienst | Aufgabe |
|---|---|
| `db` | PostgreSQL 16, nur über `127.0.0.1:5432` erreichbar |
| `app` | Oberfläche und API auf Port 8000 im Heimnetz; führt beim Start `alembic upgrade head` aus |
| `worker` | Import-Worker; startet erst, wenn `app` bereit ist (also nach der Migration) |

```bash
docker compose up -d --build                     # bauen und starten
docker compose logs -f app worker                # Protokolle
docker compose up -d --build app worker          # nach einem Update neu bauen
```

- **Daten:** Datenbank im Volume `pgdata`, Import-Verzeichnis im Volume `imports`, hochgeladene Belege und Verträge im Volume `documents` (jeweils gemeinsam für `app` und `worker`).
- **Watch-Ordner:** Dateien gelangen über `docker compose cp <datei> worker:/data/imports/inbox/<ordner>/` hinein, oder man ersetzt das Volume `imports` durch einen Ordner auf dem Rechner (der Container läuft als UID 1000).
- **Sicherung:** `docker compose exec db pg_dump -U postgres -Fc finanzplaner > finanzplaner.dump`.
- **Zugangsdaten:** Das Datenbank-Passwort `postgres` aus `docker-compose.yml` vor dem ersten Start ändern (in `db` und in `DATABASE_URL`).
- **Netzsperre:** Die App sieht die echte Adresse der Geräte im WLAN. Bei rootless Docker oder Podman erscheinen alle Anfragen dagegen mit einer internen Adresse und gelten damit als „Heimnetz“, die Sperre greift dann nicht. Der Port darf deshalb erst recht nicht nach außen freigegeben werden.

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

## Lokale KI in der Prüfliste

Eine KI im Heimnetz kann Kategorien für offene Buchungen vorschlagen. Sie **bestätigt nie selbst**:
- **Vorschlag:** Die Buchung landet unter „Automatisch zugeordnet“, mit Begründung und Sicherheit. Bestätigt wird wie gewohnt einzeln oder gesammelt.
- **Keine passende Kategorie:** Die Buchung bleibt unter „Ohne Kategorie“, mit dem Hinweis der KI.

Der Import-Worker arbeitet in einem eigenen Thread nach und nach alle offenen Buchungen ohne Kategorie ab, die neuesten zuerst. Importe warten dabei nicht.

**Was die KI zu sehen bekommt:**
- die Buchung selbst
- die passenden Kategorien
- bis zu fünf bestätigte Buchungen derselben Gegenpartei als Beispiele

Je mehr bestätigt ist, desto treffsicherer wird sie. Regeln haben Vorrang: „Regel anwenden“ überschreibt KI-Vorschläge.

| Variable | Bedeutung | Beispiel |
|---|---|---|
| `AI_URL` | Adresse des KI-Servers; leer = aus | Ollama: `http://192.168.178.40:11434`, LM Studio u. a.: `http://192.168.178.40:1234/v1` |
| `AI_MODEL` | Modellname auf dem Server | `gemma4:e2b` (Ollama), `google/gemma-4-12b-qat` (LM Studio) |
| `AI_TIMEOUT_SECONDS` | Höchstdauer je Buchung | `300` |

**Schnittstelle:** Endet die Adresse auf `/v1`, wird die OpenAI-kompatible Schnittstelle genutzt (LM Studio, llama.cpp, vLLM), sonst Ollama. Das „Nachdenken“ (Reasoning) wird abgeschaltet; es kostet bei der Zuordnung nur Zeit.

**Auf dem KI-Rechner:**
- **Ollama:** `OLLAMA_HOST=0.0.0.0` setzen und das Modell mit `ollama pull <modell>` laden.
- **LM Studio:** „Serve on Local Network“ einschalten und das Modell laden.

**Docker:** `AI_URL` und `AI_MODEL` in eine `.env` neben `docker-compose.yml` schreiben, danach `docker-compose up -d`.

**Status:** `GET /api/review/ai` liefert, ob die KI erreichbar ist und wie viele Buchungen noch offen sind. `POST /api/review/ai/retry` legt Buchungen ohne Treffer erneut vor, zum Beispiel nach neuen Kategorien. Beides zeigt auch die Prüfen-Seite.

**Erfahrungswerte:**

| Modell | Hardware | Zeit je Buchung |
|---|---|---|
| gemma4:e2b | Laptop-CPU | 15–20 s |
| gemma-4-12b | Heimnetz-Rechner | ca. 2–10 s |
| gemma-4-12b (Bildmodell) | Heimnetz-Rechner | Kassenbon-Foto 6–24 s |

Beide Modelle irren sich gelegentlich, auch wenn sie „hoch“ als Sicherheit angeben. Deshalb bleibt das Bestätigen beim Menschen.

## Vorschläge, Automatik und weitere KI-Funktionen

Nach jedem Import wertet der Worker das Profil aus (manuell: „Jetzt prüfen“ bzw. `POST /api/suggestions/refresh`).
Alles Erkannte landet als **Vorschlag** mit Begründung und Belegen; übernommen wird nur, was du bestätigst.
Abgelehnte Vorschläge erscheinen nicht erneut, solange sich nichts Wesentliches ändert.

| Bereich | Was erkannt bzw. angeboten wird |
|---|---|
| Fixkosten | wiederkehrende Abbuchungen (monatlich, vierteljährlich, halbjährlich, jährlich), Preisänderungen ab einem Monat, Jahresposten |
| Prüfliste | Regelvorschläge aus Korrekturen, Gruppen ähnlicher Buchungen, Reihenfolge nach Klärungsbedarf, Rückfragen zu Verträgen, widersprüchliche Zuordnungen |
| Zahlungen | erwartete Zahlung fehlt (nur in importierten Zeiträumen, nach fünf Bankarbeitstagen), doppelte Abbuchung |
| Zuordnung | Umbuchungen zwischen eigenen Konten, Erstattungen zu Einkäufen, wiederkehrende Aufteilungen |
| Import | Aufbau einer CSV-Datei erkennen (Assistent unter Einstellungen › Importprofile), verständliche Fehlerdiagnose mit Profilkorrektur |
| Vorschau | erwartete Einnahmen, Kontovorschau bis zu einem Datum (erwartet und tatsächlich getrennt) |
| Berichte | Monatsvergleich mit KI-Erklärung, Fragen zu den eigenen Buchungen (nur lesend) |
| Erfassung | „Gestern 18,50 € bar Mittagessen“ im Plus-Dialog → ausgefüllter Entwurf |
| Belege | Belege und Verträge hochladen; die KI liest Händler, Betrag, Positionen und Vertragsdaten (nur mit Fundstelle) |

**Automatik:** Unter Einstellungen › Automatik & KI je Profil und Funktion: *Aus*, *Nur Vorschläge* (Standard),
*Probelauf* (zeigt, was automatisch übernommen worden wäre) oder *Automatisch* (nur eindeutige Fälle, mit Rückgängig im Verlauf).

**Grundsätze:** Die Rechnung macht das Backend; die KI formuliert nur und bekommt Buchungstexte als markierte Daten.
Jede KI-Antwort wird gegen ein festes Schema geprüft. Ohne `AI_URL` funktioniert alles Deterministische weiter.
Keine automatischen Überweisungen, Kündigungen oder Löschungen.

| Variable | Bedeutung |
|---|---|
| `AI_VISION_MODEL` | Bildmodell für Fotos von Belegen (leer = `AI_MODEL`); PDFs mit Textebene brauchen es nicht |
| `DOCUMENT_DIR` | Ordner für hochgeladene Belege und Verträge (Standard `documents/`, Teil der Sicherung) |
| `AI_URL_2`, `AI_MODEL_2`, `AI_VISION_MODEL_2` | zweiter KI-Server (Priorität 2) mit eigenem Modell und Bildmodell; leer = aus |
| `AI_FAILOVER_COOLDOWN_SECONDS` | so lange wird ein ausgefallener Server übersprungen (Standard 60) |
| `AI_CONNECT_TIMEOUT_SECONDS` | kurzer Verbindungstest vor jeder Anfrage (Standard 5) |

**Zwei KI-Server:** Priorität 1 (`AI_URL`) wird immer zuerst gefragt. Ist sie nicht erreichbar, antwortet mit
einem Serverfehler oder kennt das Modell nicht, übernimmt Priorität 2 (`AI_URL_2`). Jeder Server kann eine andere
Schnittstelle haben (Ollama oder OpenAI-kompatibel). Eine Antwort, die nicht ins vorgegebene Format passt, gilt nicht
als Ausfall. Welche Server erreichbar sind, zeigt `GET /api/review/ai` (Feld `endpoints`).

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
- **Fixkosten und Spielraum** (`/fixed-costs`, `/budget/month`): Frei verfügbar im Monat = Einnahmen − Fixkosten (inkl. fälliger Kreditraten) − variable Ausgaben. Eine Fixkost gilt als bezahlt, sobald eine passende Buchung (Kategorie und/oder Suchtext) im Monat vorliegt.
- **Wanddisplay** (`GET /wall`): gemeinsamer Überblick über alle Profile ohne Profilwahl, nur lesend; wie alle Routen nur aus dem Heimnetz (`ALLOWED_NETWORKS`).
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
