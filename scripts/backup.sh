#!/usr/bin/env bash
# Sicherung des Finanzplaners: Datenbank (pg_dump -Fc) + Import-Ordner (tar.gz) + SHA-256-Prüfsummen.
#
# Nutzung: scripts/backup.sh [ZIELORDNER]          (Standard: backups/ in der Projektwurzel)
#
# Ergebnis (alle drei Dateien mit demselben Zeitstempel):
#   <ziel>/finanzplaner_<YYYYMMDD-HHMMSS>.dump     pg_dump im Custom-Format (für pg_restore)
#   <ziel>/imports_<YYYYMMDD-HHMMSS>.tar.gz        inbox/ processing/ failed/ archive/ des Import-Ordners
#   <ziel>/finanzplaner_<YYYYMMDD-HHMMSS>.sha256   Prüfsummen über beide Dateien (sha256sum -c)
#
# Konfiguration (Umgebungsvariable vor .env vor Standard):
#   DATABASE_URL  postgresql+psycopg://user[:pass]@host:port/db   (wie in .env)
#   IMPORT_DIR    Import-Ordner mit inbox/ processing/ archive/ failed/   (Standard: imports)
#   DOCUMENT_DIR  hochgeladene Belege und Verträge, im Archiv als documents/  (Standard: documents)
#   PG_BIN        Ordner mit pg_dump/psql/...   (Standard: .pg/bin, falls vorhanden, sonst PATH)
# Relative Werte von DATABASE_URL/IMPORT_DIR/PG_BIN gelten ab der Projektwurzel, ein relativer
# ZIELORDNER ab dem aktuellen Ordner. Das Passwort aus DATABASE_URL wird nie ausgegeben.
#
# Es entstehen nie halbfertige Dateien: Alles wird zuerst in einem temporären Unterordner des
# Zielordners erzeugt und erst am Ende (gleiches Dateisystem, daher atomar) umbenannt.
#
# Gemeinsame Funktionen mit restore.sh: scripts/lib.sh (muss neben diesem Skript liegen).
set -euo pipefail
AUFRUFER_PWD=$PWD
# Gemeinsame Funktionen (Konfiguration, Datenbankzugriff). Vor dem cd einbinden:
# $0 kann relativ zum aktuellen Ordner sein.
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"
cd "$(dirname "$0")/.."
umask 077   # Sicherungen enthalten alle Finanzdaten: nur der Besitzer darf sie lesen

usage() {
  cat <<'EOF'
Nutzung: scripts/backup.sh [ZIELORDNER]
  ZIELORDNER  Ablageort der Sicherung (Standard: backups/ in der Projektwurzel)
Konfiguration über DATABASE_URL, IMPORT_DIR und PG_BIN (Umgebung oder .env), siehe docs/BACKUP.md.
EOF
}

# ---- Argumente --------------------------------------------------------------------------------
usage_fehler() { echo "FEHLER: $*" >&2; usage >&2; exit 2; }
case ${1:-} in
  -h|--help) usage; exit 0 ;;
  -*) usage_fehler "Unbekannte Option: $1" ;;
esac
if [ $# -gt 1 ]; then usage_fehler "Zu viele Argumente (erwartet: höchstens ein ZIELORDNER)."; fi
if [ $# -eq 1 ]; then
  case $1 in /*) ZIEL=$1 ;; *) ZIEL=$AUFRUFER_PWD/$1 ;; esac
else
  ZIEL=$PWD/backups
fi
konfiguration_laden
[ -n "$URL_DBNAME" ] || fehler "DATABASE_URL enthält keinen Datenbanknamen."

# ---- Aufräumen: nie halbfertige Dateien hinterlassen ------------------------------------------
TMP=""
VERSCHOBEN=()   # bereits an den Zielort umbenannte Dateien (werden bei einem Fehler wieder entfernt)
aufraeumen() {
  local rc=$?
  trap - EXIT
  if [ -n "$TMP" ]; then rm -rf "$TMP"; fi
  if [ "$rc" -ne 0 ] && [ "${#VERSCHOBEN[@]}" -gt 0 ]; then rm -f "${VERSCHOBEN[@]}"; fi
  exit "$rc"
}
trap aufraeumen EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# ---- Vorbedingungen ---------------------------------------------------------------------------
werkzeug_pruefen pg_dump pg_restore psql
command -v tar >/dev/null 2>&1 || fehler "tar nicht gefunden."
# API und Worker verschieben Import-Dateien (inbox/ → processing/ → archive/) samt DB-Update
# unter einer geteilten flock-Sperre. Die Sicherung hält sie exklusiv bis zum Ende (fd 9 bleibt
# offen): Verschiebungen warten so lange, Dump und Dateiarchiv zeigen denselben Stand.
if [ -d "$IMPORT_DIR" ]; then
  if command -v flock >/dev/null 2>&1; then
    exec 9>>"$IMPORT_DIR/.files.lock"
    flock -x -w "${BACKUP_LOCK_TIMEOUT:-60}" 9 \
      || fehler "Import-Dateien werden gerade verschoben – Sperre nicht erhalten, später erneut versuchen."
  else
    warnung "flock nicht gefunden: Während der Sicherung sollten API und Worker keine Importe verarbeiten."
  fi
fi
command -v sha256sum >/dev/null 2>&1 || command -v shasum >/dev/null 2>&1 || fehler "Weder sha256sum noch shasum gefunden."

QUELL_URL=$(url_fuer_db "$URL_DBNAME_ROH")
info "Datenbank:     $QUELL_URL"
info "Import-Ordner: $IMPORT_DIR"
if ! sql_wert "$QUELL_URL" "SELECT 1" >/dev/null; then
  fehler "Datenbank nicht erreichbar (siehe Meldung oben). Läuft sie? Lokal: scripts/devdb.sh start, Docker: docker compose up -d db."
fi

mkdir -p "$ZIEL" || fehler "Zielordner $ZIEL kann nicht angelegt werden."
[ -w "$ZIEL" ] || fehler "Zielordner $ZIEL ist nicht beschreibbar."
ZIEL=$(cd "$ZIEL" && pwd)

# Zeitstempel für alle drei Dateien. Gibt es ihn schon (zweiter Lauf in derselben Sekunde), wird
# kurz auf die nächste Sekunde gewartet, statt eine bestehende Sicherung zu überschreiben.
for _ in 1 2 3; do
  TS=$(date +%Y%m%d-%H%M%S)
  DUMP_NAME=finanzplaner_$TS.dump
  TAR_NAME=imports_$TS.tar.gz
  SHA_NAME=finanzplaner_$TS.sha256
  if [ ! -e "$ZIEL/$DUMP_NAME" ] && [ ! -e "$ZIEL/$TAR_NAME" ] && [ ! -e "$ZIEL/$SHA_NAME" ]; then break; fi
  sleep 1
done
for n in "$DUMP_NAME" "$TAR_NAME" "$SHA_NAME"; do
  [ ! -e "$ZIEL/$n" ] || fehler "$ZIEL/$n existiert bereits."
done
TMP=$(mktemp -d "$ZIEL/.backup-tmp.XXXXXX") || fehler "Temporärer Ordner in $ZIEL kann nicht angelegt werden."

# ---- 1. Datenbank -----------------------------------------------------------------------------
# Erst die Datenbank, dann die Dateien: Das Archiv ist damit mindestens so aktuell wie der Dump.
info "Sichere Datenbank (pg_dump -Fc) ..."
if ! werkzeug pg_dump -Fc -w -d "$QUELL_URL" -f "$TMP/$DUMP_NAME"; then
  fehler "pg_dump ist fehlgeschlagen (siehe Meldung oben). Es wurde nichts gespeichert."
fi
# Gegenprobe: den fertigen Dump einmal komplett einlesen (Ausgabe nach /dev/null, keine Datenbank beteiligt).
werkzeug pg_restore -f /dev/null "$TMP/$DUMP_NAME" >/dev/null 2>&1 \
  || fehler "Der erzeugte Dump ist nicht lesbar (Probelauf mit pg_restore schlägt fehl). Es wurde nichts gespeichert."
REVISION=$(alembic_revision "$QUELL_URL")
ZAHLEN=$(zeilenzahlen "$QUELL_URL")

# ---- 2. Import-Ordner -------------------------------------------------------------------------
# Reihenfolge inbox -> processing -> failed -> archive entspricht dem Weg einer Datei im Worker.
# So geht keine Datei verloren, die während der Sicherung weitergeschoben wird (höchstens liegt sie
# doppelt im Archiv).
UNTERORDNER=()
for d in inbox processing failed archive; do
  if [ -d "$IMPORT_DIR/$d" ]; then UNTERORDNER+=("$d"); fi
done
info "Sichere Import-Dateien (tar.gz) ..."
if [ "${#UNTERORDNER[@]}" -eq 0 ]; then
  warnung "Import-Ordner '$IMPORT_DIR' enthält keinen der Ordner inbox/processing/failed/archive: $TAR_NAME bleibt leer (IMPORT_DIR prüfen)."
  tar -czf "$TMP/$TAR_NAME" -T /dev/null || fehler "tar ist fehlgeschlagen. Es wurde nichts gespeichert."
else
  # -h: Symlinks werden aufgelöst. Sonst würde ein per Symlink eingebundener Ordner (z. B. archive/ auf
  # einer anderen Platte) nur als Verweis ins Archiv kommen und die Originale fehlten still.
  tar_rc=0
  # Belege und Verträge (DOCUMENT_DIR) kommen als Ordner "documents/" mit ins Archiv
  BELEGE=()
  if [ -d "$DOCUMENT_DIR" ]; then
    BELEGE=(-C "$(dirname "$DOCUMENT_DIR")" --transform "s,^$(basename "$DOCUMENT_DIR"),documents," "$(basename "$DOCUMENT_DIR")")
  fi
  tar -czhf "$TMP/$TAR_NAME" -C "$IMPORT_DIR" "${UNTERORDNER[@]}" "${BELEGE[@]}" || tar_rc=$?
  tar_gnu=0
  case $(tar --version 2>/dev/null || true) in *"GNU tar"*) tar_gnu=1 ;; esac
  if [ "$tar_rc" -eq 1 ] && [ "$tar_gnu" -eq 1 ]; then
    # GNU tar meldet mit Status 1 nur "Datei hat sich geändert/verschwunden" (z. B. Worker aktiv).
    warnung "Dateien im Import-Ordner haben sich während der Sicherung geändert (läuft der Worker?). Das Archiv wurde trotzdem erstellt."
  elif [ "$tar_rc" -ne 0 ]; then
    fehler "tar ist fehlgeschlagen (Status $tar_rc, siehe Meldung oben). Es wurde nichts gespeichert."
  fi
fi
tar -tzf "$TMP/$TAR_NAME" >/dev/null 2>&1 \
  || fehler "Das erzeugte Archiv ist nicht lesbar. Es wurde nichts gespeichert."
ANZAHL_DATEIEN=$(tar -tzf "$TMP/$TAR_NAME" | grep -vc '/$' || true)

# ---- 3. Prüfsummen und Umbenennen --------------------------------------------------------------
# Namen in der .sha256-Datei sind relativ, daher funktioniert "cd <ziel> && sha256sum -c <datei>".
( cd "$TMP" && sha256_zeilen "$DUMP_NAME" "$TAR_NAME" > "$SHA_NAME" ) \
  || fehler "Prüfsummen konnten nicht berechnet werden. Es wurde nichts gespeichert."
for n in "$DUMP_NAME" "$TAR_NAME" "$SHA_NAME"; do   # die .sha256 zuletzt: Sie zeigt einen vollständigen Satz an
  [ ! -e "$ZIEL/$n" ] || fehler "$ZIEL/$n existiert bereits."
  mv "$TMP/$n" "$ZIEL/$n" || fehler "$n konnte nicht nach $ZIEL verschoben werden."
  VERSCHOBEN+=("$ZIEL/$n")
done

# ---- Zusammenfassung --------------------------------------------------------------------------
echo
echo "Sicherung abgeschlossen ($TS)"
echo "  Datenbank:         $QUELL_URL"
echo "  Alembic-Revision:  $REVISION"
echo "  Zeilen:            $ZAHLEN"
echo "  Import-Dateien:    $ANZAHL_DATEIEN in ${UNTERORDNER[*]:-(keine Ordner)}"
echo "  Dateien in $ZIEL:"
printf '    %-42s %10s\n' "$DUMP_NAME" "$(groesse "$ZIEL/$DUMP_NAME")"
printf '    %-42s %10s\n' "$TAR_NAME" "$(groesse "$ZIEL/$TAR_NAME")"
printf '    %-42s %10s\n' "$SHA_NAME" "$(groesse "$ZIEL/$SHA_NAME")"
echo "  Prüfen:            cd '$ZIEL' && sha256sum -c $SHA_NAME"
