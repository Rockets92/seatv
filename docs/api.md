# Guida API

SEA-TV pubblica la guida TV dei canali italiani (digitale terrestre, Tivùsat e Sky) come file statici: feed XMLTV per i programmi IPTV e file JSON per app, script e siti. Non serve nessuna chiave: basta l'indirizzo con il token.

## Indirizzo di base

Tutti i percorsi di questa guida sono relativi a:

```
https://seatv.pages.dev/<token>/
```

Per esempio l'elenco dei canali è `https://seatv.pages.dev/<token>/api/channels.json`. Chi conosce l'indirizzo può leggere tutto, quindi trattalo come una password.

## Come funziona

- I dati si aggiornano **una volta al giorno, alle 05:00** (ora italiana), e coprono **7 giorni** a partire da oggi.
- Sono **file statici**: si leggono con una semplice richiesta `GET`, non ci sono parametri nell'indirizzo, filtri o paginazione. Si scarica il file che serve e si filtra dal proprio lato.
- Le risposte sono in **UTF-8**. Tutte hanno `Access-Control-Allow-Origin: *`, quindi si possono leggere anche da una pagina web di un altro sito.
- **Orari** sempre in ora italiana con il fuso indicato: `2026-10-15T21:30:00+02:00` in JSON, `20261015213000 +0200` in XMLTV. Il cambio dell'ora legale è già gestito.
- **Cache**: i file JSON restano validi 5 minuti, i feed 15, i loghi un giorno (`Cache-Control`).
- Un file che non esiste (per esempio un giorno non ancora pubblicato) risponde `404`.

## Feed XMLTV

Per i programmi IPTV (TiviMate, IPTV Smarters, Kodi, Jellyfin, Plex...): si incolla l'indirizzo come EPG esterna. Il programma abbina i canali della playlist M3U tramite il `tvg-id`, che deve essere uguale all'id del canale nel feed. Ci sono tre feed, uguali tranne che per gli id dei canali: si sceglie quello che usa la propria playlist.

| Feed | `tvg-id` della playlist | Esempi |
|---|---|---|
| `epg.xml.gz` (anche `epg.xml`) | id SEA-TV | `rai1`, `canale5`, `skyunoplus1` |
| `epg-iptvorg.xml.gz` | liste di iptv-org | `Rai1.it`, `Rai1.it@HD`, `SkyUno.it@Plus1` |
| `epg-epgshare.xml.gz` (anche `.xml`) | liste di epgshare01 | `Rai.1.HD.it`, `La.5.it` |

La versione `.gz` è compressa e consigliata; quella senza `.gz` c'è se pesa meno di 25 MB (il limite di Cloudflare). L'elenco dei feed effettivamente pubblicati è in `api/health.json`.

Ogni canale ha i suoi nomi (`display-name`) e il logo; ogni programma ha titolo, descrizione, categorie e immagine quando la fonte li fornisce:

```xml
<channel id="rai1">
  <display-name>Rai 1</display-name>
  <display-name>Rai 1 HD</display-name>
  <icon src="https://seatv.pages.dev/<token>/logos/rai1.png"/>
</channel>
<programme start="20261015213000 +0200" stop="20261015234500 +0200" channel="rai1">
  <title>Titolo del programma</title>
  <desc>Descrizione...</desc>
  <category>Film</category>
</programme>
```

Esempio di riga della playlist M3U con gli id SEA-TV:

```
#EXTINF:-1 tvg-id="rai1" tvg-chno="1",Rai 1
```

## File JSON

| Percorso | Contenuto |
|---|---|
| `api/health.json` | Stato dell'ultimo aggiornamento: data, giorni disponibili, feed, esito di ogni fonte |
| `api/channels.json` | Tutti i canali, con numeri, fonti, logo e id delle liste IPTV |
| `api/channels/{id}.json` | Un canale con tutti i suoi programmi dei 7 giorni |
| `api/guide/{AAAA-MM-GG}.json` | Tutti i canali con i programmi di quel giorno |
| `logos/{id}.png` | Logo del canale (può essere anche `.jpg`, `.gif` o `.webp`: usa il campo `logo`) |

### Canale

Ogni canale, in `channels.json` e negli altri file, ha questa forma:

```json
{
  "id": "rai1",
  "name": "Rai 1",
  "logo": "logos/rai1.png",
  "numbers": {"dtt": 1, "tivusat": 1, "sky": 101},
  "sources": ["tivu", "sky"],
  "ids": {"iptvorg": ["Rai1.it", "Rai1.it@HD"], "epgshare": ["Rai.1.HD.it"]}
}
```

| Campo | Significato |
|---|---|
| `id` | Id SEA-TV del canale: il nome in minuscolo, senza spazi e senza "HD" (`+` diventa `plus`). È anche il `tvg-id` di `epg.xml` |
| `name` | Nome del canale |
| `logo` | Percorso del logo relativo all'indirizzo di base, o indirizzo completo della fonte; `null` se manca |
| `numbers` | Numero del canale per piattaforma: `dtt` (digitale terrestre), `tivusat`, `sky`. Una piattaforma manca se il canale non c'è |
| `sources` | Fonti da cui arrivano i dati: `tivu` (Tivù La Guida), `sky` (Guida TV Sky), `xmltv` |
| `ids` | Id dello stesso canale nelle liste IPTV (`iptvorg`, `epgshare`); vuoto se non trovato |

`channels.json` è in ordine di numero del digitale terrestre; i canali che non sono sul digitale terrestre seguono in ordine di nome.

### Programma

```json
{
  "start": "2026-10-15T21:30:00+02:00",
  "stop": "2026-10-15T23:45:00+02:00",
  "title": "Titolo del programma",
  "description": "Descrizione...",
  "category": "Film",
  "image": "https://...",
  "source": "tivu"
}
```

| Campo | Significato |
|---|---|
| `start`, `stop` | Inizio e fine, in ora italiana con il fuso |
| `title` | Titolo |
| `description` | Descrizione, o `null` |
| `category` | Genere (Sky usa "Genere/Sottogenere"), o `null` |
| `image` | Immagine del programma (indirizzo della fonte), o `null` |
| `source` | Fonte del programma: `tivu`, `sky` o `xmltv` |

### Guida del giorno

`api/guide/2026-10-15.json` contiene tutti i canali, ognuno con i programmi in onda quel giorno anche solo in parte (dalla mezzanotte alla mezzanotte, ora italiana). È il file da usare per una griglia o per sapere cosa c'è stasera:

```json
{
  "date": "2026-10-15",
  "channels": [
    {"channel": {"id": "rai1", "name": "Rai 1", "...": "..."}, "programmes": [{"start": "...", "title": "..."}]}
  ]
}
```

I giorni disponibili sono in `days` di `api/health.json`.

### Un canale

`api/channels/rai1.json` contiene il canale e tutti i suoi programmi pubblicati, in ordine di orario:

```json
{"channel": {"id": "rai1", "name": "Rai 1", "...": "..."}, "programmes": [{"start": "...", "title": "..."}]}
```

### Stato

`api/health.json` dice quando sono stati generati i dati e se le fonti hanno risposto:

```json
{
  "status": "ok",
  "generated_at": "2026-10-15T05:03:12+02:00",
  "days": ["2026-10-15", "2026-10-16", "..."],
  "channels": 156,
  "programmes": 34612,
  "feeds": [{"scheme": "seatv", "gz": "epg.xml.gz", "xml": "epg.xml", "channels": 156}],
  "sources": [{"source": "tivu", "channels": 78, "programmes": 15800, "reused": 0, "error": null, "...": "..."}]
}
```

`status` è `degraded` se una fonte non ha risposto: i suoi canali tengono i programmi dell'aggiornamento precedente (`reused` dice quanti) e `error` spiega cosa è andato storto. In `feeds`, `xml` è `null` se il feed c'è solo compresso e `channels` dice quanti canali hanno un id di quella lista.

## Esempi

Cosa va in onda adesso su ogni canale, in JavaScript:

```js
const base = "https://seatv.pages.dev/<token>/";
const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Rome" }).format(new Date());
const guide = await (await fetch(`${base}api/guide/${today}.json`)).json();
const now = Date.now();
for (const { channel, programmes } of guide.channels) {
  const p = programmes.find((p) => Date.parse(p.start) <= now && now < Date.parse(p.stop));
  if (p) console.log(channel.numbers.dtt ?? "-", channel.name, p.title);
}
```

Palinsesto di un canale in Python:

```python
import json, urllib.request

base = "https://seatv.pages.dev/<token>/"
data = json.load(urllib.request.urlopen(base + "api/channels/canale5.json"))
for p in data["programmes"][:10]:
    print(p["start"][11:16], p["title"])
```

Scaricare il feed da terminale:

```bash
curl -O "https://seatv.pages.dev/<token>/epg.xml.gz"
```

## Limiti

- I dati arrivano dalle guide pubbliche di Tivù e Sky e **non sono concessi in licenza**: vanno bene per uso personale e di prova.
- Gli orari sono quelli delle fonti: possono cambiare all'ultimo momento e due programmi possono sovrapporsi di qualche minuto.
- L'API è in sola lettura e cambia solo con l'aggiornamento delle 05:00.
