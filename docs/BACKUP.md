# Sicherung und Wiederherstellung

## Was gesichert wird – und was nicht

`scripts/backup.sh` erzeugt drei Dateien mit gemeinsamem Zeitstempel:

| Datei | Inhalt |
|---|---|
| `finanzplaner_<ts>.dump` | komplette PostgreSQL-Datenbank (`pg_dump -Fc`): Profile, Banken, Konten, Buchungen und Splits, Kredite, Kategorien, Regeln, Importprofile, Watch-Ordner, Importläufe samt Importentscheidungen, `alembic_version` |
| `imports_<ts>.tar.gz` | Original-Kontoauszüge aus `IMPORT_DIR` (Standard `imports/`): `inbox/`, `processing/`, `failed/`, `archive/` |
| `finanzplaner_<ts>.sha256` | SHA-256-Prüfsummen über beide Dateien |

**Nicht** gesichert: `.env` (Zugangsdaten, selbst aufbewahren) und der Code (Git, `uv.lock`).

**CSV- und PDF-Exporte sind keine Sicherung.** Regeln, Profile und Importentscheidungen stecken nur in der Datenbank und fehlen in jedem Export.

## Sicherung erstellen

```bash
scripts/backup.sh                    # nach backups/
scripts/backup.sh /mnt/nas/finanzen  # anderer Zielordner
```

**Vorher den Import-Worker beenden** (die API darf weiterlaufen). Der Worker verschiebt Dateien von `processing/` nach `archive/`; liefe er während der Sicherung, könnten Datenbank-Dump und Dateiarchiv verschiedene Stände enthalten. `backup.sh` erkennt einen laufenden Worker an dessen Sperrdatei `IMPORT_DIR/.worker.lock` und bricht dann ab.

Die Skripte lesen `DATABASE_URL` und `IMPORT_DIR` aus `.env`; Umgebungsvariablen und Argumente haben Vorrang. Das Passwort aus `DATABASE_URL` wird nie ausgegeben.

| Variable | Bedeutung | Standard |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://user[:pass]@host:port/db` | aus `.env` |
| `IMPORT_DIR` | Import-Ordner | `imports` |
| `PG_BIN` | Ordner mit `pg_dump`, `pg_restore`, `psql`, `createdb`, `dropdb` | `.pg/bin`, falls vorhanden, sonst PATH (`PG_BIN=` erzwingt PATH) |

Relative Werte gelten ab der Projektwurzel, relative Argumente ab dem aktuellen Ordner. Die gemeinsamen Funktionen beider Skripte (`.env` lesen, URL zerlegen, Werkzeuge aufrufen) stehen in `scripts/lib.sh`; die Datei wird per `source` eingebunden, ist nicht ausführbar und muss neben den Skripten liegen.

- **Lokal ohne Docker** (Entwicklungsrechner): `scripts/devdb.sh start`, dann `scripts/backup.sh`. Die Werkzeuge kommen aus `.pg/bin`, die Datenbank läuft auf Port 5433.
- **Docker Compose:** Die Datenbank ist auf `127.0.0.1:5432` erreichbar. In `.env` den Compose-Port und das Compose-Passwort eintragen: `DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/finanzplaner`. Auf dem Host müssen die PostgreSQL-16-Clientprogramme installiert sein (z. B. `postgresql-client-16`); `pg_dump` darf nicht älter sein als der Server. Gibt es dort auch ein `.pg/bin`, mit `PG_BIN=` die Programme aus dem PATH erzwingen.

Die Dateien enthalten alle Finanzdaten unverschlüsselt und sind deshalb nur für den Besitzer lesbar (Modus 600). `backups/` gehört in die `.gitignore` und darf nicht ins Repository.

Das Skript schreibt zuerst in einen temporären Ordner im Ziel und benennt erst am Ende um: Bei einem Fehler bleiben keine halbfertigen Dateien zurück. Nach einem harten Abbruch (`kill -9`) kann ein verstecktes `.backup-tmp.*` übrig bleiben, das sich löschen lässt.

## Wiederherstellen

```bash
scripts/restore.sh <DUMP> [IMPORT_TAR] [--target-db NAME] [--yes]

scripts/restore.sh backups/finanzplaner_<ts>.dump backups/imports_<ts>.tar.gz   # Beispiel
```

1. **App und Worker stoppen**, sonst lässt sich die Datenbank nicht löschen.
2. Das Skript prüft die Prüfsummen (`.sha256` neben dem Dump) und liest den Dump probeweise vollständig ein. Bis hierhin ändert es nichts.
3. Standardziel ist die Datenbank aus `DATABASE_URL`, mit `--target-db NAME` eine andere. Ist sie nicht leer, fragt das Skript nach (`--yes` unterdrückt die Frage).
4. Die Ziel-DB wird gelöscht, neu angelegt und mit `pg_restore --no-owner --exit-on-error --single-transaction` gefüllt.
5. Das Import-Archiv wird nach `IMPORT_DIR` entpackt. Würde dabei eine bestehende Datei überschrieben, bricht das Skript vorher ab (außer mit `--yes`).
6. Zum Schluss stehen Alembic-Revision und Zeilenzahlen (`app_user`, `account`, `transaction`, …) im Ergebnis. Sie sollten mit der Ausgabe von `backup.sh` übereinstimmen.

Ist der Code neuer als die wiederhergestellte Revision: `uv run alembic upgrade head`.

**Docker Compose ohne Clientprogramme auf dem Host** (auf dem Entwicklungsrechner nicht getestet, dort gibt es kein Docker):

```bash
TS=$(date +%Y%m%d-%H%M%S); mkdir -p backups
docker compose exec -T db pg_dump -U postgres -Fc finanzplaner > backups/finanzplaner_$TS.dump
tar -czf backups/imports_$TS.tar.gz -C imports inbox processing failed archive   # fehlende Ordner weglassen
(cd backups && sha256sum finanzplaner_$TS.dump imports_$TS.tar.gz > finanzplaner_$TS.sha256)

# Wiederherstellen (hier in eine Test-DB; für die echte DB den Namen finanzplaner einsetzen)
docker compose exec -T db dropdb -U postgres --if-exists finanzplaner_restore_test
docker compose exec -T db createdb -U postgres -T template0 finanzplaner_restore_test
docker compose exec -T db pg_restore -U postgres --no-owner --exit-on-error --single-transaction \
  -d finanzplaner_restore_test < backups/finanzplaner_<ts>.dump
```

## Empfehlung

- **Häufigkeit:** täglich per Cron oder systemd-Timer, zusätzlich vor jedem `alembic upgrade`, vor großen Importen und vor einer Massenänderung der Regeln.
  `15 2 * * *  /pfad/zum/projekt/scripts/backup.sh /mnt/nas/finanzen`
- **Aufbewahrung:** etwa 14 tägliche und 12 monatliche Stände. Mindestens eine Kopie außerhalb des Rechners (andere Platte, NAS, verschlüsselter Cloud-Speicher). Die drei Dateien eines Zeitstempels immer zusammen kopieren und löschen.
- **Alte Stände** räumt kein Skript auf; das geschieht von Hand oder per eigenem Cron-Job.

## Wiederherstellung regelmäßig proben

Eine Sicherung gilt erst als brauchbar, wenn ein Restore geklappt hat. Mindestens monatlich und nach jeder Schemaänderung in eine leere Test-DB und einen eigenen Import-Ordner einspielen, nie in die produktive Datenbank:

```bash
IMPORT_DIR=/tmp/restore-probe/imports scripts/restore.sh \
  backups/finanzplaner_<ts>.dump backups/imports_<ts>.tar.gz --target-db finanzplaner_restore_test
```

Zeilenzahlen und Revision mit der Ausgabe von `backup.sh` vergleichen und stichprobenartig einen Report prüfen. Danach die Test-DB löschen: `dropdb finanzplaner_restore_test` (lokal: `.pg/bin/dropdb -h 127.0.0.1 -p 5433 -U postgres finanzplaner_restore_test`).

## Fehlermeldungen

- **„Prüfsumme stimmt nicht“:** Datei beschädigt oder unvollständig kopiert; einen anderen Stand nehmen. Das Skript hat dann nichts verändert.
- **„database … is being accessed by other users“:** App oder Worker laufen noch.
- **„Keine Prüfsummendatei gefunden“:** Die `.sha256` fehlt neben dem Dump; die Integrität wird dann nur über den Probelauf geprüft.
