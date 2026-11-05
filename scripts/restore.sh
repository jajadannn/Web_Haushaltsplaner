#!/usr/bin/env bash
# Wiederherstellung aus einer Sicherung von scripts/backup.sh.
#
# Nutzung: scripts/restore.sh <DUMP> [IMPORT_TAR] [--target-db NAME] [--yes]
#   DUMP         finanzplaner_<ts>.dump aus backup.sh
#   IMPORT_TAR   imports_<ts>.tar.gz aus backup.sh; wird in IMPORT_DIR entpackt
#   --target-db  Ziel-Datenbank (Standard: die Datenbank aus DATABASE_URL)
#   --yes        keine Rückfrage vor dem Überschreiben einer nicht leeren Datenbank und
#                vor dem Überschreiben bestehender Import-Dateien und Belege
#
# Ablauf: Prüfsummen prüfen (.sha256 neben dem Dump), Dump und Archiv auf Lesbarkeit prüfen,
# Ziel-DB löschen und leer neu anlegen, mit pg_restore einspielen, Import-Archiv entpacken,
# Revision und Zeilenzahlen ausgeben. Bis zur Rückfrage wird nichts verändert.
#
# Konfiguration (Umgebungsvariable vor .env vor Standard):
#   DATABASE_URL  postgresql+psycopg://user[:pass]@host:port/db   (wie in .env)
#   IMPORT_DIR    Zielordner für das Import-Archiv   (Standard: imports)
#   DOCUMENT_DIR  Zielordner für Belege (documents/ im Archiv)   (Standard: documents)
#   PG_BIN        Ordner mit pg_restore/psql/...   (Standard: .pg/bin, falls vorhanden, sonst PATH)
# Relative Werte von DATABASE_URL/IMPORT_DIR/PG_BIN gelten ab der Projektwurzel, relative Pfade der
# Argumente (DUMP, IMPORT_TAR) ab dem aktuellen Ordner. Das Passwort aus DATABASE_URL wird nie ausgegeben.
#
# Gemeinsame Funktionen mit backup.sh: scripts/lib.sh (muss neben diesem Skript liegen).
set -euo pipefail
AUFRUFER_PWD=$PWD
# Gemeinsame Funktionen (Konfiguration, Datenbankzugriff). Vor dem cd einbinden:
# $0 kann relativ zum aktuellen Ordner sein.
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"
cd "$(dirname "$0")/.."

usage() {
  cat <<'EOF'
Nutzung: scripts/restore.sh <DUMP> [IMPORT_TAR] [--target-db NAME] [--yes]
  DUMP         Dump aus scripts/backup.sh (finanzplaner_<ts>.dump)
  IMPORT_TAR   Import-Archiv aus scripts/backup.sh (imports_<ts>.tar.gz), wird nach IMPORT_DIR entpackt
  --target-db  Ziel-Datenbank (Standard: Datenbank aus DATABASE_URL)
  --yes        keine Rückfragen (nicht leere Ziel-DB, bestehende Import-Dateien überschreiben)
Konfiguration über DATABASE_URL, IMPORT_DIR und PG_BIN (Umgebung oder .env), siehe docs/BACKUP.md.
EOF
}

# ---- Argumente --------------------------------------------------------------------------------
usage_fehler() { echo "FEHLER: $*" >&2; usage >&2; exit 2; }
DUMP=""
IMPORT_TAR=""
ZIEL_DB=""
ZIEL_DB_GEGEBEN=0
JA=0
while [ $# -gt 0 ]; do
  case $1 in
    -h|--help) usage; exit 0 ;;
    --yes|-y) JA=1; shift ;;
    --target-db)
      [ $# -ge 2 ] || usage_fehler "--target-db braucht einen Datenbanknamen."
      ZIEL_DB=$2; ZIEL_DB_GEGEBEN=1; shift 2 ;;
    --target-db=*) ZIEL_DB=${1#--target-db=}; ZIEL_DB_GEGEBEN=1; shift ;;
    -*) usage_fehler "Unbekannte Option: $1" ;;
    *)
      if [ -z "$DUMP" ]; then DUMP=$1
      elif [ -z "$IMPORT_TAR" ]; then IMPORT_TAR=$1
      else usage_fehler "Zu viele Argumente: $1"
      fi
      shift ;;
  esac
done
[ -n "$DUMP" ] || usage_fehler "Es fehlt die Dump-Datei."
if [ "$ZIEL_DB_GEGEBEN" -eq 1 ] && [ -z "$ZIEL_DB" ]; then usage_fehler "--target-db braucht einen Datenbanknamen."; fi

konfiguration_laden

abs_pfad() { case $1 in /*) printf '%s' "$1" ;; *) printf '%s/%s' "$AUFRUFER_PWD" "$1" ;; esac; }
DUMP=$(abs_pfad "$DUMP")
if [ ! -f "$DUMP" ] || [ ! -r "$DUMP" ]; then fehler "Dump-Datei nicht gefunden oder nicht lesbar: $DUMP"; fi
if [ -n "$IMPORT_TAR" ]; then
  IMPORT_TAR=$(abs_pfad "$IMPORT_TAR")
  if [ ! -f "$IMPORT_TAR" ] || [ ! -r "$IMPORT_TAR" ]; then fehler "Import-Archiv nicht gefunden oder nicht lesbar: $IMPORT_TAR"; fi
fi

ZIEL_DB=${ZIEL_DB:-$URL_DBNAME}
[ -n "$ZIEL_DB" ] || fehler "Keine Ziel-Datenbank: DATABASE_URL enthält keinen Namen und --target-db fehlt."
[[ $ZIEL_DB =~ ^[A-Za-z0-9_-]{1,63}$ ]] \
  || fehler "Ungültiger Datenbankname '$ZIEL_DB' (erlaubt: Buchstaben, Ziffern, _ und -, höchstens 63 Zeichen)."
case $ZIEL_DB in
  postgres|template0|template1) fehler "'$ZIEL_DB' ist eine Systemdatenbank und kein zulässiges Ziel." ;;
esac

# ---- Vorbedingungen ---------------------------------------------------------------------------
werkzeug_pruefen pg_restore psql dropdb createdb
command -v tar >/dev/null 2>&1 || fehler "tar nicht gefunden."
command -v sha256sum >/dev/null 2>&1 || command -v shasum >/dev/null 2>&1 || fehler "Weder sha256sum noch shasum gefunden."

ZIEL_URL=$(url_fuer_db "$ZIEL_DB")
WARTUNG_URL=$(url_fuer_db postgres)   # Verwaltungs-DB für DROP/CREATE DATABASE
info "Dump:          $DUMP"
if [ -n "$IMPORT_TAR" ]; then info "Import-Archiv: $IMPORT_TAR (-> $IMPORT_DIR)"; fi
info "Ziel:          $ZIEL_URL"

# ---- 1. Prüfsummen ----------------------------------------------------------------------------
case $DUMP in *.dump) SHA_DATEI=${DUMP%.dump}.sha256 ;; *) SHA_DATEI=$DUMP.sha256 ;; esac

# pruefsumme_pruefen DATEI -> 0 = stimmt, 1 = weicht ab, 2 = kein Eintrag in der .sha256-Datei
pruefsumme_pruefen() {
  local datei=$1 name erwartet ist
  name=$(basename "$datei")
  erwartet=$(awk -v n="$name" '{ f = $2; sub(/^\*/, "", f); if (f == n) { print $1; exit } }' "$SHA_DATEI" | tr -d '\r')
  [ -n "$erwartet" ] || return 2
  ist=$(sha256_zeilen "$datei" | awk '{ print $1 }')
  [ "$erwartet" = "$ist" ]
}

if [ -f "$SHA_DATEI" ]; then
  for datei in "$DUMP" ${IMPORT_TAR:+"$IMPORT_TAR"}; do
    rc=0
    pruefsumme_pruefen "$datei" || rc=$?
    case $rc in
      0) info "Prüfsumme OK:  $(basename "$datei")" ;;
      2) warnung "Kein Eintrag für $(basename "$datei") in $(basename "$SHA_DATEI") - Integrität nicht geprüft." ;;
      *) fehler "Prüfsumme stimmt nicht: $(basename "$datei") ist beschädigt oder verändert (Vergleich mit $SHA_DATEI). Es wurde nichts verändert." ;;
    esac
  done
else
  warnung "Keine Prüfsummendatei gefunden ($SHA_DATEI) - Integrität von Dump und Archiv wird nicht geprüft."
fi

# ---- 2. Dump und Archiv auf Lesbarkeit prüfen ---------------------------------------------------
# Alles hier geschieht, bevor die Ziel-DB angetastet wird: Ein kaputter Dump darf nie zum Löschen führen.
TOC=$(werkzeug pg_restore --list "$DUMP" 2>&1) \
  || fehler "Der Dump ist nicht lesbar (pg_restore --list): $TOC"
# Probelauf: liest und entpackt den ganzen Dump, schreibt aber nur nach /dev/null (keine Datenbank beteiligt).
PROBE=$(werkzeug pg_restore -f /dev/null "$DUMP" 2>&1 >/dev/null) \
  || fehler "Der Dump ist beschädigt (Probelauf mit pg_restore schlägt fehl)${PROBE:+: $PROBE}"
DUMP_ERSTELLT=$(printf '%s\n' "$TOC" | sed -n 's/^; Archive created at //p')
DUMP_QUELLE=$(printf '%s\n' "$TOC" | sed -n 's/^; *dbname: //p')
info "Dump enthält:  Datenbank '${DUMP_QUELLE:-?}', erstellt ${DUMP_ERSTELLT:-?}"

TAR_ANZAHL=0
if [ -n "$IMPORT_TAR" ]; then
  TAR_LISTE=$(tar -tf "$IMPORT_TAR") || fehler "Das Import-Archiv ist nicht lesbar: $IMPORT_TAR"
  # Erwartet wird ein Archiv von backup.sh: nur inbox/, processing/, failed/, archive/ (ohne "./" davor),
  # keine absoluten Pfade und kein "..".
  FREMD=$(printf '%s\n' "$TAR_LISTE" | grep -v -E '^(inbox|processing|failed|archive|documents)(/|$)' || true)
  UNSICHER=$(printf '%s\n' "$TAR_LISTE" | grep -E '^/|(^|/)\.\.(/|$)' || true)
  if [ -n "$FREMD" ] || [ -n "$UNSICHER" ]; then
    fehler "Das Import-Archiv stammt nicht von backup.sh (unerwarteter Pfad: '$(printf '%s\n%s\n' "$FREMD" "$UNSICHER" | grep -v '^$' | head -n 1)'). Es wurde nichts verändert."
  fi
  KONFLIKTE=()
  while IFS= read -r eintrag; do
    case $eintrag in ''|*/) continue ;; esac
    TAR_ANZAHL=$((TAR_ANZAHL + 1))
    # Archivpfad auf den tatsächlichen Zielordner abbilden: documents/ landet in DOCUMENT_DIR
    case $eintrag in
      documents/*) ziel="$DOCUMENT_DIR/${eintrag#documents/}" ;;
      *) ziel="$IMPORT_DIR/$eintrag" ;;
    esac
    if [ -e "$ziel" ] || [ -L "$ziel" ]; then KONFLIKTE+=("$ziel"); fi
  done <<<"$TAR_LISTE"
  if [ "${#KONFLIKTE[@]}" -gt 0 ]; then
    if [ "$JA" -ne 1 ]; then
      {
        echo "FEHLER: ${#KONFLIKTE[@]} vorhandene Datei(en) würden überschrieben (Import-Ordner '$IMPORT_DIR', Belege '$DOCUMENT_DIR'), z. B.:"
        printf '  %s\n' "${KONFLIKTE[@]:0:5}"
        echo "Abbruch, es wurde nichts verändert. Mit --yes überschreiben, oder IMPORT_DIR/DOCUMENT_DIR auf einen anderen Ordner setzen."
      } >&2
      exit 1
    fi
    warnung "${#KONFLIKTE[@]} bestehende Datei(en) in '$IMPORT_DIR' bzw. '$DOCUMENT_DIR' werden überschrieben (--yes)."
  fi
fi

# ---- 3. Zustand der Ziel-Datenbank, Rückfrage ----------------------------------------------------
if ! sql_wert "$WARTUNG_URL" "SELECT 1" >/dev/null; then
  fehler "Datenbankserver nicht erreichbar (siehe Meldung oben). Läuft er? Lokal: scripts/devdb.sh start, Docker: docker compose up -d db."
fi
EXISTIERT=$(sql_wert "$WARTUNG_URL" "SELECT count(*) FROM pg_database WHERE datname = '$ZIEL_DB'") \
  || fehler "Die Datenbankabfrage ist fehlgeschlagen (siehe Meldung oben)."
NICHT_LEER=0
if [ "$EXISTIERT" -gt 0 ]; then
  OBJEKTE=$(sql_wert "$ZIEL_URL" "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relkind IN ('r','p','v','m','f','S') AND n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'") \
    || fehler "Die vorhandene Ziel-Datenbank '$ZIEL_DB' kann nicht geprüft werden (siehe Meldung oben)."
  if [ "$OBJEKTE" -gt 0 ]; then NICHT_LEER=1; fi
fi

if [ "$NICHT_LEER" -eq 1 ]; then
  if [ "$JA" -ne 1 ]; then
    {
      echo
      echo "ACHTUNG: Die Ziel-Datenbank '$ZIEL_DB' ist NICHT leer:"
      echo "  $(zeilenzahlen "$ZIEL_URL")"
      echo "Sie wird gelöscht und durch den Inhalt von $(basename "$DUMP") ersetzt. Das lässt sich nicht rückgängig machen."
      echo "App und Worker vorher stoppen. Tipp: erst mit scripts/backup.sh den jetzigen Stand sichern."
      printf 'Fortfahren? [j/N] '
    } >&2
    antwort=""
    read -r antwort || true
    if [ ! -t 0 ]; then echo >&2; fi   # Eingabe kam aus einer Pipe: Zeilenumbruch nach der Frage
    case $antwort in
      j|J|ja|Ja|JA|y|Y|yes|Yes|YES) ;;
      *) echo "Abgebrochen. Es wurde nichts verändert." >&2; exit 1 ;;
    esac
  fi
  info "Ziel-Datenbank '$ZIEL_DB' ist nicht leer - wird ersetzt."
elif [ "$EXISTIERT" -gt 0 ]; then
  info "Ziel-Datenbank '$ZIEL_DB' existiert und ist leer - wird neu angelegt."
else
  info "Ziel-Datenbank '$ZIEL_DB' existiert nicht - wird angelegt."
fi

# ---- 4. Datenbank neu anlegen und einspielen -----------------------------------------------------
if [ "$EXISTIERT" -gt 0 ]; then
  info "Lösche Datenbank '$ZIEL_DB' ..."
  werkzeug dropdb -w --if-exists --maintenance-db="$WARTUNG_URL" "$ZIEL_DB" \
    || fehler "Datenbank '$ZIEL_DB' konnte nicht gelöscht werden (siehe Meldung oben). Greifen App oder Worker noch zu? Dann stoppen und erneut versuchen."
fi
info "Lege Datenbank '$ZIEL_DB' leer an ..."
werkzeug createdb -w --maintenance-db="$WARTUNG_URL" --template=template0 --encoding=UTF8 "$ZIEL_DB" \
  || fehler "Datenbank '$ZIEL_DB' konnte nicht angelegt werden (siehe Meldung oben)."
info "Spiele den Dump ein (pg_restore) ..."
if ! werkzeug pg_restore -w --no-owner --exit-on-error --single-transaction -d "$ZIEL_URL" "$DUMP"; then
  fehler "pg_restore ist fehlgeschlagen (siehe Meldung oben). Die Datenbank '$ZIEL_DB' ist leer oder unvollständig und darf nicht verwendet werden. Ursache beheben und das Skript erneut ausführen."
fi

# ---- 5. Import-Archiv entpacken ------------------------------------------------------------------
if [ -n "$IMPORT_TAR" ]; then
  if [ -z "$TAR_LISTE" ]; then
    info "Das Import-Archiv ist leer."
  else
    info "Entpacke $TAR_ANZAHL Import-Datei(en) nach '$IMPORT_DIR' ..."
    # Jeder Ordner wird einzeln entpackt (-C <ordner> --strip-components=1). So funktioniert es auch, wenn
    # z. B. archive/ im Ziel ein Symlink auf eine andere Platte ist (tar ersetzt ihn dann nicht).
    if grep -q -E "^documents(/|\$)" <<<"$TAR_LISTE"; then
      info "Entpacke Belege nach '$DOCUMENT_DIR' ..."
      { mkdir -p "$DOCUMENT_DIR" && tar -xf "$IMPORT_TAR" -C "$DOCUMENT_DIR" --strip-components=1 --no-same-owner documents; } \
        || fehler "Entpacken der Belege nach '$DOCUMENT_DIR' ist fehlgeschlagen. Die Datenbank wurde bereits wiederhergestellt; das Archiv erneut entpacken."
    fi
    for d in inbox processing failed archive; do
      if grep -q -E "^$d(/|\$)" <<<"$TAR_LISTE"; then
        { mkdir -p "$IMPORT_DIR/$d" && tar -xf "$IMPORT_TAR" -C "$IMPORT_DIR/$d" --strip-components=1 --no-same-owner "$d"; } \
          || fehler "Entpacken von $d/ nach '$IMPORT_DIR' ist fehlgeschlagen. Die Datenbank wurde bereits wiederhergestellt; das Archiv erneut entpacken."
      fi
    done
  fi
fi

# ---- Zusammenfassung ----------------------------------------------------------------------------
echo
echo "Wiederherstellung abgeschlossen."
echo "  Ziel-Datenbank:    $ZIEL_URL"
echo "  Alembic-Revision:  $(alembic_revision "$ZIEL_URL")"
echo "  Zeilen:            $(zeilenzahlen "$ZIEL_URL")"
if [ -n "$IMPORT_TAR" ]; then echo "  Import-Dateien:    $TAR_ANZAHL nach $IMPORT_DIR"; fi
echo "Hinweis: Hat der Code neuere Migrationen als diese Revision, jetzt 'uv run alembic upgrade head' ausführen."
