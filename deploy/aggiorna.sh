#!/bin/sh
# Aggiornamento della guida, da lanciare con un'attività pianificata di Plesk (cron).
# Legge le impostazioni da .env nella cartella del progetto.
set -eu
cd "$(dirname "$0")/.."
if [ -f .env ]; then
    set -a
    . ./.env
    set +a
fi
exec .venv/bin/python -m seatv.ingest
