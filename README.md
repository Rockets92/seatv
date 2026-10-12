# SEA-TV API

API web con la guida TV (EPG) dei canali italiani del digitale terrestre (`dtt`) e del satellite (`sat`).

Il servizio scarica periodicamente i palinsesti da una o più fonti, li salva in SQLite e li espone in JSON con FastAPI.

## Avvio rapido

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Scarica subito i palinsesti (facoltativo: il server lo fa anche all'avvio)
python -m seatv.ingest

# Avvia l'API su http://localhost:8000 (documentazione interattiva su /docs)
uvicorn seatv.main:create_app --factory
```

## Endpoint

| Metodo e percorso | Cosa restituisce |
|---|---|
| `GET /channels?platform=dtt\|sat` | Elenco canali. Con `platform`, solo quelli numerati su quella piattaforma, ordinati per numero (LCN). |
| `GET /channels/{id}` | Un canale, es. `/channels/rai-1`. |
| `GET /channels/{id}/schedule?date=AAAA-MM-GG` | Palinsesto del giorno (ora italiana, default oggi): i programmi che iniziano in quel giorno. |
| `GET /channels/{id}/now?at=...` | Programma in onda e successivo su un canale. |
| `GET /now?platform=dtt\|sat&at=...` | In onda ora e a seguire su tutti i canali. `at` è facoltativo; senza fuso orario si intende ora italiana. |
| `GET /health` | Esito dell'ultima ingestione per ogni fonte; `degraded` se una fonte è fallita o non è ancora stata letta. |

Esempio di canale:

```json
{"id": "rai-1", "name": "Rai 1", "logo": "https://services.tivulaguida.it/uploads/channel/....png", "numbers": {"dtt": 1, "sat": 1}}
```

Gli orari dei programmi sono restituiti in ora italiana con offset, es. `2026-10-12T20:00:00+02:00`.

## Fonti

Le fonti sono intercambiabili (`seatv/sources/`): ognuna restituisce canali e programmi in un formato comune.

- **`tivu`** (predefinita): API di Tivù La Guida, che copre DTT nazionale e Tivùsat e riporta anche i numeri di canale. Endpoint ricavati dal grabber `sites/tivu.tv` di [iptv-org/epg](https://github.com/iptv-org/epg).
- **`xmltv`**: qualsiasi feed XMLTV, anche compresso `.gz`, indicato con `SEATV_XMLTV_URL`. Se il feed contiene `<lcn>`, il numero viene assegnato al DTT.

Le varianti SD e HD dello stesso canale ("Rai 1" e "Rai 1 HD") vengono unite in un solo canale con id `rai-1`; per ogni piattaforma si tiene il numero più basso.

A ogni aggiornamento, i programmi di un canale nell'intervallo coperto dai dati nuovi vengono sostituiti, così un programma spostato di orario non resta duplicato. Se si usano più fonti, quella elencata per ultima prevale negli intervalli che copre.

**Attenzione ai diritti:** nessuna di queste fonti concede in licenza i dati. Va bene per un prototipo o un uso personale; prima di aprire l'API al pubblico serve un accordo con gli editori o un fornitore licenziato (vedi la ricerca sulle fonti del progetto).

## Configurazione

Tutto tramite variabili d'ambiente:

| Variabile | Default | Significato |
|---|---|---|
| `SEATV_DB_PATH` | `data/seatv.sqlite3` | File SQLite |
| `SEATV_SOURCES` | `tivu` | Fonti separate da virgola: `tivu`, `xmltv` |
| `SEATV_XMLTV_URL` | | URL del feed XMLTV (necessario con `xmltv`) |
| `SEATV_DAYS_AHEAD` | `2` | Giorni di palinsesto da scaricare, a partire da oggi |
| `SEATV_RETENTION_DAYS` | `7` | Giorni di palinsesto passato da conservare |
| `SEATV_REFRESH_HOURS` | `12` | Ogni quante ore aggiornare |
| `SEATV_SCHEDULER` | `true` | `false` per disattivare l'aggiornamento automatico nel server (es. se si usa cron con `python -m seatv.ingest`) |
| `SEATV_HTTP_TIMEOUT` | `20` | Timeout delle richieste in secondi |
| `SEATV_HTTP_CONCURRENCY` | `4` | Richieste contemporanee verso Tivù |

## Test

```bash
pytest
```

I test non usano la rete: le risposte delle fonti sono simulate con i file in `tests/fixtures/`, costruiti sul formato reale dell'API Tivù.

## Struttura

```
seatv/
  config.py        configurazione da variabili d'ambiente
  db.py            schema SQLite e query
  ingest.py        scaricamento e salvataggio (anche da riga di comando)
  main.py          app FastAPI e aggiornamento periodico
  sources/
    tivu.py        fonte Tivù La Guida
    xmltv.py       fonte XMLTV generica
tests/
```
