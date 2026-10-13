#!/bin/sh
# Rende scrivibile la cartella dei dati (anche se montata dall'host, es. da Plesk)
# e avvia il server come utente non privilegiato.
set -eu
if [ "$(id -u)" = 0 ]; then
    mkdir -p "$(dirname "$SEATV_DB_PATH")"
    chown -R seatv:seatv "$(dirname "$SEATV_DB_PATH")"
    exec setpriv --reuid=seatv --regid=seatv --init-groups "$@"
fi
exec "$@"
