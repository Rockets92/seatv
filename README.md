<p align="center"><img src="seatv/web/logo.png" alt="SEA-TV, Simple EPG API" width="520"></p>

# SEA-TV

Guida TV (EPG) dei canali italiani del digitale terrestre e del satellite, pubblicata come sito statico su **Cloudflare Pages** (piano gratuito) e aggiornata ogni mattina da **GitHub Actions**.

Ogni aggiornamento produce:

- un **feed XMLTV** (`epg.xml` e `epg.xml.gz`) da incollare nel programma IPTV come EPG esterna;
- la **guida TV web** con loghi, griglia per canale e dettaglio dei programmi;
- un'**API JSON** fatta di file statici (canali, griglia per giorno, palinsesto per canale, stato delle fonti).

Le piattaforme, ognuna con la sua numerazione, sono `dtt` (digitale terrestre), `tivusat` (satellite gratuito Tivùsat) e `sky` (satellite Sky Italia).

## Come funziona

```
GitHub Actions, ogni giorno alle 05:00 ora italiana
  └─ python -m seatv.build
       ├─ scarica canali e palinsesti da Tivù e Sky (7 giorni)
       ├─ scarica i loghi (tenuti in cache tra un giorno e l'altro)
       └─ scrive dist/: feed XMLTV, API JSON, pagina web
  └─ wrangler pages deploy dist  →  https://<progetto>.pages.dev/<token>/
```

Perché così e non un Worker con Cron Trigger: un aggiornamento fa circa 1.500 richieste alle fonti (circa 230 canali per 7 giorni), mentre un Worker gratuito può farne al massimo 50 per esecuzione; le fonti poi rispondono a client "normali" e un runner di GitHub lo è più di un Worker. Cloudflare serve solo file statici, senza limiti di richieste sul piano gratuito.

**Riservatezza.** Il sito sta in una cartella dal nome segreto (`SEATV_FEED_TOKEN`): chi non conosce l'indirizzo trova solo una pagina vuota. Tutte le risposte hanno `X-Robots-Tag: noindex`, `robots.txt` blocca i motori di ricerca e la pagina non invia il proprio indirizzo ad altri siti (`Referrer-Policy: no-referrer`). Il token nel percorso funziona con qualsiasi programma IPTV, perché è un normale URL.

**Attenzione ai diritti:** nessuna delle fonti concede in licenza i dati. Va bene per un uso personale e di prova; per un servizio pubblico serve un accordo con gli editori o un fornitore licenziato.

## Pubblicazione su Cloudflare

La guida passo passo, con i segreti da aggiungere su GitHub, è in [docs/cloudflare.md](docs/cloudflare.md).

## Uso nel programma IPTV

Nel programma IPTV (TiviMate, IPTV Smarters, Kodi IPTV Simple, Jellyfin, Plex, OTT Navigator...) aggiungi come EPG esterna:

```
https://<progetto>.pages.dev/<token>/epg.xml.gz
```

Se il programma non legge i file compressi usa `epg.xml`. L'indirizzo esatto, con il pulsante per copiarlo, è anche nella guida web sotto **Feed e fonti**.

Il programma IPTV abbina i canali della playlist M3U alla guida tramite il `tvg-id`, che deve essere uguale all'id del canale nel feed. Siccome le liste in circolazione usano schemi diversi, SEA-TV pubblica un feed per schema: scegli quello che corrisponde ai `tvg-id` della tua playlist.

| Feed | `tvg-id` nella playlist | Esempi |
|---|---|---|
| `epg.xml.gz` | id SEA-TV | `rai1`, `canale5`, `skyunoplus1` |
| `epg-iptvorg.xml.gz` | database e playlist di [iptv-org](https://github.com/iptv-org/iptv) | `Rai2.it`, `Rai2.it@SD`, `Rai2.it@HD`, `SkyUno.it@Plus1` |
| `epg-epgshare.xml.gz` | feed di [epgshare01](https://epgshare01.online) e liste costruite su di esso | `Rai.2.HD.it`, `La.5.it` |

Gli id esterni si scaricano a ogni aggiornamento (database di iptv-org e feed italiano di epgshare01) e si abbinano ai canali SEA-TV per nome; se una lista non risponde si usano gli id del giorno prima. Un canale senza corrispondenza resta con l'id SEA-TV. Nei feed iptv-org ed epgshare01 lo stesso canale compare con ciascuno dei suoi id, con il palinsesto ripetuto. Nella guida web il dettaglio di ogni programma mostra tutti i `tvg-id` del canale e **Feed e fonti** dice quanti canali hanno un id per ogni lista.

Esempio con gli id SEA-TV:

```
#EXTINF:-1 tvg-id="rai1" tvg-chno="1",Rai 1
```

Gli id SEA-TV sono il nome in minuscolo senza spazi e senza "HD" (il `+` diventa `plus`). L'elenco completo è in `api/channels.json`, dove ogni canale ha anche gli id delle altre liste (`"ids"`). Per i programmi che abbinano per nome, ogni canale del feed elenca anche i nomi usati dalle fonti (es. "Rai 1" e "Rai 1 HD").

Gli orari del feed sono in ora italiana con offset (`20261013210000 +0200`), quindi il cambio dell'ora legale è gestito.

## API JSON

Tutti i percorsi sono relativi a `https://<progetto>.pages.dev/<token>/`:

| Percorso | Contenuto |
|---|---|
| `epg.xml.gz`, `epg.xml` | Feed XMLTV di tutti i canali, da oggi per 7 giorni. Se un file `.xml` superasse i 25 MiB per file di Cloudflare si pubblica solo la versione compressa. |
| `epg-iptvorg.xml.gz`, `epg-epgshare.xml.gz` | Lo stesso feed con gli id dei canali di iptv-org e di epgshare01 (anche senza `.gz`). |
| `api/health.json` | Data dell'aggiornamento, giorni disponibili, esito di ogni fonte, nomi dei feed. `status` è `degraded` se una fonte è fallita. |
| `api/channels.json` | Elenco canali con numeri per piattaforma, fonti e logo. |
| `api/channels/{id}.json` | Un canale con tutti i suoi programmi. |
| `api/guide/AAAA-MM-GG.json` | Tutti i canali con i programmi in onda in quel giorno, anche solo in parte: i dati della griglia. |
| `logos/{id}.png` | Logo del canale (PNG, JPEG, GIF o WebP). |

Esempio di canale:

```json
{"id": "rai1", "name": "Rai 1", "logo": "logos/rai1.png", "numbers": {"dtt": 1, "tivusat": 1, "sky": 101}, "sources": ["sky", "tivu"]}
```

Gli orari dei programmi sono in ora italiana con offset, es. `2026-10-12T20:00:00+02:00`, e ogni programma indica la fonte (`"source": "tivu"`).

## Guida TV web

Tre viste: **Griglia** (una riga per canale, gli orari in orizzontale e una linea azzurra sull'ora attuale; toccandola di nuovo torna all'ora attuale), **Adesso** (per ogni canale il programma in onda e il successivo) e **Serata** (prima e seconda serata del giorno scelto). Il pulsante **Guida** in alto apre questa documentazione (README e guida Cloudflare) dentro il sito, in `guida.html`. La ricerca accetta il nome o il numero del canale; vista e piattaforma restano scelte alla prossima apertura. Da computer, sopra la griglia, ci sono anche le schede di ciò che è in onda ora. Le schede filtrano per piattaforma (con i numeri di quella piattaforma), il menu **Fonte** mostra i canali di una fonte, **Feed e fonti** mostra gli indirizzi del feed e l'esito dell'ultimo aggiornamento. Cliccando un programma si aprono orari, durata, genere, descrizione, immagine, fonte e `tvg-id`. Da telefono la colonna dei canali mostra solo logo e numero.

**Come app sul telefono.** La guida si installa come app a schermo intero, con la sua icona:

- **Android** (Chrome): pulsante **Installa** in alto, oppure menu ⋮ → **Installa app** / **Aggiungi a schermata Home**;
- **iPhone e iPad** (Safari): **Condividi** → **Aggiungi alla schermata Home** (il pulsante **Installa** lo ricorda).

L'app si apre senza barre del browser e rispetta notch e barre di sistema. Pagina, loghi e guide già viste restano salvate sul telefono (service worker `sw.js`), quindi si apre anche senza rete; a ogni aggiornamento del sito scarica la versione nuova.

## Fonti

Le fonti sono intercambiabili (`seatv/sources/`): ognuna restituisce canali e programmi in un formato comune.

- **`tivu`** (attiva di default): API di Tivù La Guida, che copre DTT nazionale e Tivùsat con i numeri di canale. Endpoint ricavati dal grabber `sites/tivu.tv` di [iptv-org/epg](https://github.com/iptv-org/epg).
- **`sky`** (attiva di default): API della Guida TV Sky, circa 150 canali con i numeri del decoder. Endpoint ricavati dal grabber `sites/guidatv.sky.it` di iptv-org/epg.
- **`xmltv`**: qualsiasi feed XMLTV, anche `.gz`, indicato con `SEATV_XMLTV_URL`.

I canali delle diverse fonti vengono uniti per nome normalizzato: "Rai 1" e "Rai 1 HD" di Tivù e "Rai 1 HD" di Sky diventano un solo canale `rai1` con i numeri di tutte le piattaforme. Per i nomi scritti in modo diverso c'è una tabella di alias in `seatv/sources/__init__.py`. Se due fonti coprono lo stesso canale vince la prima di `SEATV_SOURCES`, e Sky viene interrogata solo per i canali che Tivù non ha fornito.

**Se una fonte non risponde** le altre vanno avanti e `api/health.json` riporta l'errore. I canali di quella fonte tengono i programmi dell'aggiornamento precedente non ancora finiti (la guida precedente resta nella cache di GitHub Actions). Se manca Tivù, i palinsesti nazionali arrivano da Sky e i numeri del digitale terrestre da una tabella di riserva (`seatv/lcn.py`). Se non risponde nessuna fonte e non c'è niente da riprendere, il sito pubblicato resta quello del giorno prima.

## Generare il sito sul proprio computer

```bash
python -m venv .venv && source .venv/bin/activate    # su Windows: .venv\Scripts\activate
pip install -e ".[dev]"

python -m seatv.build                 # genera dist/
python -m http.server -d dist 8000    # guida su http://localhost:8000/
```

Con `SEATV_FEED_TOKEN` impostato il sito va in `dist/<token>/`. Da lì si può anche pubblicare a mano con `npx wrangler pages deploy dist --project-name=seatv` (vedi la guida Cloudflare).

## Configurazione

Variabili d'ambiente, tutte facoltative:

| Variabile | Default | Significato |
|---|---|---|
| `SEATV_FEED_TOKEN` | | Parte segreta del percorso (16-128 caratteri tra lettere, cifre, `-` e `_`); vuoto = sito nella radice |
| `SEATV_PUBLIC_URL` | | Indirizzo del sito, es. `https://seatv.pages.dev`, per i link assoluti ai loghi nel feed |
| `SEATV_SOURCES` | `tivu,sky` | Fonti in ordine di priorità: `tivu`, `sky`, `xmltv` |
| `SEATV_XMLTV_URL` | | URL del feed XMLTV (necessario con `xmltv`) |
| `SEATV_TIVU_URL` | `https://services.tivulaguida.it` | Indirizzo dell'API Tivù, se il servizio si sposta |
| `SEATV_DAYS_AHEAD` | `7` | Giorni di palinsesto, a partire da oggi |
| `SEATV_LOGO_INDEX_URL` | elenco `logos.csv` di iptv-org | Loghi di riserva; vuoto per non usarli |
| `SEATV_EXTERNAL_IDS` | `iptvorg,epgshare` | Liste di cui pubblicare il feed con i loro id; vuoto per pubblicare solo `epg.xml` |
| `SEATV_OUT_DIR` | `dist` | Cartella del sito generato |
| `SEATV_CACHE_DIR` | `.cache` | Loghi scaricati e guida precedente |
| `SEATV_HTTP_TIMEOUT` | `20` | Timeout delle richieste in secondi |
| `SEATV_HTTP_CONCURRENCY` | `4` | Richieste contemporanee verso ciascuna fonte |

## Test

```bash
pytest
```

I test non usano la rete: le risposte delle fonti sono simulate con i file in `tests/fixtures/`, costruiti sul formato reale delle API Tivù e Sky.

## Struttura

```
.github/workflows/pubblica.yml  aggiornamento quotidiano e pubblicazione su Cloudflare Pages
docs/cloudflare.md              messa in linea passo passo
seatv/
  build.py        aggiornamento completo (python -m seatv.build)
  collect.py      scaricamento dalle fonti e unione dei canali
  model.py        la guida in memoria e la sua istantanea
  logos.py        download e cache dei loghi
  external_ids.py id dei canali nelle liste iptv-org ed epgshare01
  export/
    xmltv.py      feed XMLTV
    site.py       API JSON, pagina web e regole per Cloudflare Pages
  sources/        tivu.py, sky.py, xmltv.py
  web/            pagina della guida TV
tests/
```
