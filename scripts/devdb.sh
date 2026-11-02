#!/usr/bin/env bash
# Lokale PostgreSQL-16-Instanz ohne Docker/sudo (Binärdateien in .pg/, Port 5433).
# Nutzung: scripts/devdb.sh start|stop|status|psql
set -euo pipefail
cd "$(dirname "$0")/.."
PG=.pg/bin
DATA=.pg/data
PORT=5433

case "${1:-status}" in
  start)
    mkdir -p .pg/run
    "$PG/pg_ctl" -D "$DATA" -o "-p $PORT -k $PWD/.pg/run -c listen_addresses=127.0.0.1" -l .pg/pg.log -w start
    ;;
  stop) "$PG/pg_ctl" -D "$DATA" -w stop ;;
  status) "$PG/pg_ctl" -D "$DATA" status ;;
  psql) shift; "$PG/psql" -h 127.0.0.1 -p "$PORT" -U postgres "${@:-finanzplaner}" ;;
  *) echo "Nutzung: $0 start|stop|status|psql [db]"; exit 1 ;;
esac
