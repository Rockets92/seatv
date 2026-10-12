# SEA-TV API

API web con la guida TV (EPG) dei canali italiani del digitale terrestre e del satellite.

Le piattaforme, ognuna con la sua numerazione, sono:

- `dtt`: digitale terrestre
- `tivusat`: satellite gratuito Tivùsat
- `sky`: satellite Sky Italia

Il servizio scarica periodicamente i palinsesti da una o più fonti, li salva in SQLite e li espone in JSON con FastAPI.

## Avvio rapido

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Scarica subito i palinsesti (facoltativo: il server lo fa anche all'avvio)
python -m seatv.ingest

# Avvia su http://localhost:8000: guida TV su /, documentazione dell'API su /docs
uvicorn seatv.main:create_app --factory
```

## Guida TV web

Aprendo http://localhost:8000/ si vede una guida TV interattiva: una riga per canale, gli orari in orizzontale e una linea rossa sull'ora attuale.

- In alto si sceglie il giorno; il pulsante **Adesso** riporta all'ora attuale.
- Le schede filtrano per piattaforma (digitale terrestre, Tivùsat, Sky) e mostrano i numeri di quella piattaforma.
- Il menu **Fonte** mostra solo i canali di una fonte; il pulsante **Fonti** apre lo stato dell'ultimo aggiornamento di ciascuna.
- Cliccando un programma si aprono orari, durata, genere, descrizione, immagine e fonte da cui arriva.

La pagina è fatta di file statici (`seatv/static/`) che leggono `GET /guide` e `GET /health`.

## Endpoint

| Metodo e percorso | Cosa restituisce |
|---|---|
| `GET /channels?platform=dtt\|tivusat\|sky` | Elenco canali. Con `platform`, solo quelli numerati su quella piattaforma, ordinati per numero (LCN). |
| `GET /channels/{id}` | Un canale, es. `/channels/rai1`. |
| `GET /channels/{id}/schedule?date=AAAA-MM-GG` | Palinsesto del giorno (ora italiana, default oggi): i programmi che iniziano in quel giorno. |
| `GET /guide?date=AAAA-MM-GG&platform=...` | Tutti i canali con i programmi in onda nel giorno, anche solo in parte: i dati della griglia. |
| `GET /channels/{id}/now?at=...` | Programma in onda e successivo su un canale. |
| `GET /now?platform=dtt\|tivusat\|sky&at=...` | In onda ora e a seguire su tutti i canali. `at` è facoltativo; senza fuso orario si intende ora italiana. |
| `GET /health` | Esito dell'ultima ingestione per ogni fonte; `degraded` se una fonte è fallita o non è ancora stata letta. |

Esempio di canale:

```json
{"id": "rai1", "name": "Rai 1", "logo": "https://services.tivulaguida.it/uploads/channel/....png", "numbers": {"dtt": 1, "tivusat": 1, "sky": 101}, "sources": ["sky", "tivu"]}
```

Gli orari dei programmi sono restituiti in ora italiana con offset, es. `2026-10-12T20:00:00+02:00`. Ogni programma indica anche la fonte (`"source": "tivu"`).

## Fonti

Le fonti sono intercambiabili (`seatv/sources/`): ognuna restituisce canali e programmi in un formato comune.

- **`tivu`** (attiva di default): API di Tivù La Guida, che copre DTT nazionale e Tivùsat e riporta anche i numeri di canale. Endpoint ricavati dal grabber `sites/tivu.tv` di [iptv-org/epg](https://github.com/iptv-org/epg).
- **`sky`** (attiva di default): API della Guida TV Sky, circa 150 canali della piattaforma Sky con i numeri del decoder. Endpoint ricavati dal grabber `sites/guidatv.sky.it` di iptv-org/epg.
- **`xmltv`**: qualsiasi feed XMLTV, anche compresso `.gz`, indicato con `SEATV_XMLTV_URL`. Se il feed contiene `<lcn>`, il numero viene assegnato al DTT.

I canali delle diverse fonti vengono uniti per nome normalizzato: "Rai 1" e "Rai 1 HD" di Tivù e "Rai 1 HD" di Sky diventano un solo canale con id `rai1` e i numeri di tutte le piattaforme. Per i nomi scritti in modo diverso c'è una piccola tabella di alias in `seatv/sources/__init__.py`. Se una piattaforma elenca più varianti dello stesso canale, si tiene il numero più basso.

Se due fonti coprono lo stesso canale vince la prima di `SEATV_SOURCES`: nome, logo e palinsesto di Rai 1 arrivano da Tivù, e Sky viene interrogata solo per i canali che Tivù non ha fornito.

A ogni aggiornamento, i programmi di un canale nell'intervallo coperto dai dati nuovi vengono sostituiti, così un programma spostato di orario non resta duplicato.

**Attenzione ai diritti:** nessuna di queste fonti concede in licenza i dati. Va bene per un prototipo o un uso personale; prima di aprire l'API al pubblico serve un accordo con gli editori o un fornitore licenziato (vedi la ricerca sulle fonti del progetto).

## Configurazione

Tutto tramite variabili d'ambiente:

| Variabile | Default | Significato |
|---|---|---|
| `SEATV_DB_PATH` | `data/seatv.sqlite3` | File SQLite |
| `SEATV_SOURCES` | `tivu,sky` | Fonti separate da virgola, in ordine di priorità: `tivu`, `sky`, `xmltv` |
| `SEATV_XMLTV_URL` | | URL del feed XMLTV (necessario con `xmltv`) |
| `SEATV_DAYS_AHEAD` | `2` | Giorni di palinsesto da scaricare, a partire da oggi |
| `SEATV_RETENTION_DAYS` | `7` | Giorni di palinsesto passato da conservare |
| `SEATV_REFRESH_HOURS` | `12` | Ogni quante ore aggiornare |
| `SEATV_SCHEDULER` | `true` | `false` per disattivare l'aggiornamento automatico nel server (es. se si usa cron con `python -m seatv.ingest`) |
| `SEATV_HTTP_TIMEOUT` | `20` | Timeout delle richieste in secondi |
| `SEATV_HTTP_CONCURRENCY` | `4` | Richieste contemporanee verso ciascuna fonte |

## Test

```bash
pytest
```

I test non usano la rete: le risposte delle fonti sono simulate con i file in `tests/fixtures/`, costruiti sul formato reale delle API Tivù e Sky.

## Struttura

```
seatv/
  config.py        configurazione da variabili d'ambiente
  db.py            schema SQLite e query
  ingest.py        scaricamento e salvataggio (anche da riga di comando)
  main.py          app FastAPI e aggiornamento periodico
  static/          pagina web della guida TV
  sources/
    tivu.py        fonte Tivù La Guida
    sky.py         fonte Sky Guida TV
    xmltv.py       fonte XMLTV generica
tests/
```
