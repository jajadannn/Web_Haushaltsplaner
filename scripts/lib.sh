# shellcheck shell=bash
# Gemeinsame Funktionen von scripts/backup.sh und scripts/restore.sh: .env lesen, DATABASE_URL in eine
# libpq-URL ohne Passwort zerlegen, PostgreSQL-Werkzeuge aufrufen, Revision und Zeilenzahlen abfragen.
# Wird per "source" eingebunden und ist nicht ausführbar. Beim Einbinden passiert nichts und es werden
# keine Shell-Optionen gesetzt; die Skripte rufen nach dem Wechsel in die Projektwurzel
# konfiguration_laden auf. Variablen wie IMPORT_DIR oder URL_DBNAME benutzen erst die einbindenden Skripte:
# shellcheck disable=SC2034

fehler()  { echo "FEHLER: $*" >&2; exit 1; }
warnung() { echo "WARNUNG: $*" >&2; }
info()    { echo "$*"; }

# Liest einen Wert aus .env (letzter Eintrag gewinnt). Die Datei wird bewusst nicht mit "source"
# geladen: Sie enthält auch Werte wie CORS_ORIGINS=["..."], die keine gültige Shell-Syntax sind.
env_aus_datei() {
  local key=$1 zeile wert
  [ -f .env ] || return 0
  zeile=$(grep -E "^[[:space:]]*(export[[:space:]]+)?$key[[:space:]]*=" .env | tail -n 1 || true)
  [ -n "$zeile" ] || return 0
  wert=$(printf '%s' "${zeile#*=}" | tr -d '\r' | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')
  case $wert in
    \"*\") wert=${wert#\"}; wert=${wert%\"} ;;
    \'*\') wert=${wert#\'}; wert=${wert%\'} ;;
    *) wert=$(printf '%s' "$wert" | sed -E 's/[[:space:]]+#.*$//') ;;
  esac
  printf '%s' "$wert"
}

# Prozent-Kodierung auflösen (z. B. %40 -> @), nur für das Passwort und den DB-Namen.
urldecode() {
  local rest=$1 out="" hex
  while [[ $rest =~ ^([^%]*)%([0-9A-Fa-f]{2})(.*)$ ]]; do
    printf -v hex '\\x%s' "${BASH_REMATCH[2]}"
    # hex besteht nur aus \xHH, die Formatzeichenfolge ist also unbedenklich
    # shellcheck disable=SC2059
    printf -v hex "$hex"
    out+=${BASH_REMATCH[1]}$hex
    rest=${BASH_REMATCH[3]}
  done
  printf '%s' "$out$rest"
}

# SQLAlchemy-URL (postgresql+psycopg://...) in eine libpq-URL ohne Passwort zerlegen. Das Passwort
# geht über PGPASSWORD an die Werkzeuge: So steht es weder in der Prozessliste noch in Ausgaben.
# Setzt URL_BASIS (ohne Datenbank und Passwort), URL_QUERY, URL_DBNAME_ROH, URL_DBNAME, PGPASSWORD.
db_url_zerlegen() {
  local url re passwort
  url=$(printf '%s' "$1" | sed -E 's#^(postgres(ql)?)\+[A-Za-z0-9_]+://#\1://#')
  re='^(postgres(ql)?://)(([^:/@]*)(:([^@/]*))?@)?([^/?]*)(/([^?]*))?(\?(.*))?$'
  [[ $url =~ $re ]] || fehler "DATABASE_URL hat kein erkennbares Format (erwartet: postgresql+psycopg://user[:passwort]@host:port/datenbank)."
  URL_BASIS=${BASH_REMATCH[1]}${BASH_REMATCH[4]:+${BASH_REMATCH[4]}@}${BASH_REMATCH[7]}
  URL_DBNAME_ROH=${BASH_REMATCH[9]}
  URL_QUERY=${BASH_REMATCH[11]}
  passwort=${BASH_REMATCH[6]}
  if [ -n "$passwort" ]; then
    PGPASSWORD=$(urldecode "$passwort")
    export PGPASSWORD
  fi
  URL_DBNAME=$(urldecode "$URL_DBNAME_ROH")
}

# Bestimmt DATABASE_URL, IMPORT_DIR und PG_BIN (Umgebungsvariable vor .env vor Standard) und zerlegt
# DATABASE_URL. Muss in der Projektwurzel aufgerufen werden: Dort liegen .env und .pg/.
konfiguration_laden() {
  DATABASE_URL=${DATABASE_URL:-$(env_aus_datei DATABASE_URL)}
  IMPORT_DIR=${IMPORT_DIR:-$(env_aus_datei IMPORT_DIR)}
  IMPORT_DIR=${IMPORT_DIR:-imports}
  DOCUMENT_DIR=${DOCUMENT_DIR:-$(env_aus_datei DOCUMENT_DIR)}
  DOCUMENT_DIR=${DOCUMENT_DIR:-documents}
  if [ -z "${PG_BIN+x}" ]; then   # nicht gesetzt: lokale Werkzeuge nehmen; "PG_BIN=" erzwingt PATH
    if [ -x .pg/bin/pg_dump ]; then PG_BIN=.pg/bin; else PG_BIN=""; fi
  fi
  [ -n "$DATABASE_URL" ] || fehler "DATABASE_URL fehlt (weder in der Umgebung noch in .env). Vorlage: .env.example"
  db_url_zerlegen "$DATABASE_URL"
}

# libpq-URL (ohne Passwort, daher unbedenklich für Ausgaben) für die Datenbank $1 auf demselben Server.
url_fuer_db() { printf '%s/%s%s' "$URL_BASIS" "$1" "${URL_QUERY:+?$URL_QUERY}"; }

werkzeug() {   # werkzeug NAME ARGS... : Programm aus PG_BIN, sonst aus dem PATH
  local name=$1
  shift
  if [ -n "$PG_BIN" ]; then "$PG_BIN/$name" "$@"; else "$name" "$@"; fi
}

werkzeug_pruefen() {
  local name
  for name in "$@"; do
    if [ -n "$PG_BIN" ]; then
      [ -x "$PG_BIN/$name" ] || fehler "$name nicht gefunden: $PG_BIN/$name (PG_BIN prüfen)."
    elif ! command -v "$name" >/dev/null 2>&1; then
      fehler "$name nicht im PATH. PostgreSQL-16-Clientprogramme installieren oder PG_BIN auf deren bin-Ordner setzen (lokal: .pg/bin)."
    fi
  done
}

sql_wert() { werkzeug psql -X -q -w -A -t -v ON_ERROR_STOP=1 -d "$1" -c "$2"; }   # sql_wert URL SQL

alembic_revision() {   # alembic_revision URL
  local rev
  rev=$(sql_wert "$1" "SELECT string_agg(version_num, ', ' ORDER BY version_num) FROM alembic_version" 2>/dev/null) || rev=""
  if [ -n "$rev" ]; then printf '%s' "$rev"; else printf '%s' "(unbekannt: Tabelle alembic_version fehlt oder ist leer)"; fi
}

zeilenzahlen() {   # zeilenzahlen URL -> "app_user=1 account=2 ..." ("-" = Tabelle fehlt)
  local url=$1 t n out=""
  for t in app_user account transaction category mapping_rule import_batch; do
    n=$(sql_wert "$url" "SELECT count(*) FROM public.\"$t\"" 2>/dev/null) || n="-"
    out+="$t=$n "
  done
  printf '%s' "${out% }"
}

sha256_zeilen() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }

groesse() {   # Dateigröße lesbar (B/KiB/MiB/GiB)
  wc -c < "$1" | awk '{ b = $1
    if (b < 1024) printf "%d B", b
    else if (b < 1048576) printf "%.1f KiB", b / 1024
    else if (b < 1073741824) printf "%.1f MiB", b / 1048576
    else printf "%.2f GiB", b / 1073741824 }'
}
