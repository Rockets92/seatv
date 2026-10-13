"""Avvio sotto Phusion Passenger (Plesk): Passenger parla WSGI, a2wsgi lo traduce per FastAPI.

Richiede `pip install -e ".[plesk]"` nel virtualenv `.venv` accanto a questo file.
Le impostazioni si leggono dal file `.env` nella stessa cartella.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Se Passenger usa il Python di sistema, si riparte con quello del virtualenv.
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
if VENV_PYTHON.exists() and sys.executable != str(VENV_PYTHON):
    os.execl(str(VENV_PYTHON), str(VENV_PYTHON), *sys.argv)

os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
# Passenger non esegue il ciclo di aggiornamento interno: ci pensa l'attività pianificata.
os.environ.setdefault("SEATV_SCHEDULER", "false")

from a2wsgi import ASGIMiddleware  # noqa: E402

from seatv.main import create_app  # noqa: E402

application = ASGIMiddleware(create_app())
