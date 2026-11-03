#!/bin/sh
# serve   – Datenbank migrieren, dann Oberfläche und API auf Port 8000 starten (Standard)
# worker  – Import-Worker starten (genau EIN Prozess, siehe README)
# migrate – nur die Migrationen ausführen
# alles andere wird unverändert ausgeführt (z. B. „python -m …“)
set -e

case "$1" in
  serve)
    alembic upgrade head
    exec uvicorn app.server:app --host 0.0.0.0 --port 8000
    ;;
  worker)
    exec python -m app.worker
    ;;
  migrate)
    exec alembic upgrade head
    ;;
  *)
    exec "$@"
    ;;
esac
