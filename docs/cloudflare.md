# Messa in linea su Cloudflare Pages

Tutto gira gratis: GitHub Actions scarica la guida ogni mattina alle 05:00 (ora italiana) e la pubblica su Cloudflare Pages. Servono un account Cloudflare (piano Free) e tre segreti nel repository GitHub.

## 1. Account ID di Cloudflare

1. Entra su <https://dash.cloudflare.com> (crea l'account se non ce l'hai, il piano Free basta).
2. Apri **Workers & Pages**: l'**Account ID** è nella colonna a destra (oppure è il codice esadecimale nell'indirizzo della pagina, `dash.cloudflare.com/<account-id>/...`).
3. Copialo: è il segreto `CLOUDFLARE_ACCOUNT_ID`.

Non serve creare il progetto Pages a mano: lo crea il primo aggiornamento, con il nome `seatv`.

## 2. Token API di Cloudflare

1. In alto a destra: icona del profilo → **My Profile** → **API Tokens** → **Create Token**.
2. In fondo scegli **Create Custom Token** → **Get started**.
3. Nome: `seatv-github`. In **Permissions** aggiungi una sola riga: **Account** · **Cloudflare Pages** · **Edit**.
4. In **Account Resources**: **Include** · il tuo account.
5. **Continue to summary** → **Create Token** e copia il token (si vede una volta sola): è il segreto `CLOUDFLARE_API_TOKEN`.

Il token può solo gestire i progetti Pages, niente altro dell'account.

## 3. Token del feed

È la parte segreta dell'indirizzo: `https://seatv.pages.dev/<token>/epg.xml.gz`. Generane uno casuale, per esempio in PowerShell o nel terminale:

```bash
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

Deve avere da 16 a 128 caratteri tra lettere, cifre, `-` e `_` (quello generato così va bene). È il segreto `SEATV_FEED_TOKEN`. Se un giorno l'indirizzo finisce in mani sbagliate, basta cambiare il segreto: al giro dopo il vecchio indirizzo smette di funzionare.

## 4. Segreti su GitHub

Nel repository: **Settings** → **Secrets and variables** → **Actions** → scheda **Secrets** → **New repository secret**, tre volte:

| Nome | Valore |
|---|---|
| `CLOUDFLARE_API_TOKEN` | token del punto 2 |
| `CLOUDFLARE_ACCOUNT_ID` | id del punto 1 |
| `SEATV_FEED_TOKEN` | token del punto 3 |

Facoltative, nella scheda **Variables** della stessa pagina:

| Nome | Quando serve |
|---|---|
| `CLOUDFLARE_PAGES_PROJECT` | per un nome di progetto diverso da `seatv` |
| `SEATV_PUBLIC_URL` | se l'indirizzo del sito non è `https://<progetto>.pages.dev` (vedi il punto 6) |

## 5. Primo aggiornamento

Apri la scheda **Actions** del repository → workflow **Aggiorna e pubblica la guida**:

- se il workflow è già su `main`: **Run workflow**;
- finché è solo nel branch di prova: apri l'ultima esecuzione del branch e premi **Re-run all jobs** (la nuova esecuzione usa i segreti appena aggiunti).

Il riepilogo dell'esecuzione mostra canali e programmi scaricati e l'esito di ogni fonte. Poi l'aggiornamento parte da solo ogni giorno alle 05:00.

## 6. Indirizzo del feed

Il sito è su `https://seatv.pages.dev`. Se il nome `seatv` era già preso da qualcun altro, Cloudflare aggiunge un suffisso (es. `seatv-abc.pages.dev`): lo vedi in **Workers & Pages** → **seatv**. In quel caso imposta la variabile `SEATV_PUBLIC_URL` con l'indirizzo giusto, così i loghi nel feed puntano al sito corretto.

Gli indirizzi da usare sono:

```
https://seatv.pages.dev/<token>/              guida TV web
https://seatv.pages.dev/<token>/epg.xml.gz    feed XMLTV compresso (consigliato)
https://seatv.pages.dev/<token>/epg.xml       feed XMLTV
```

Il primo indirizzo, aperto dal browser del telefono, si può installare come app a schermo intero (Android: **Installa**; iPhone: **Condividi** → **Aggiungi alla schermata Home**). Aperto dal browser, mostra anche gli altri due sotto **Feed e fonti**, con il pulsante per copiarli. L'indirizzo `https://seatv.pages.dev/` senza token mostra solo una pagina vuota.

Se i `tvg-id` della tua playlist sono come `Rai2.it` o `Rai2.it@HD` (iptv-org) usa `epg-iptvorg.xml.gz`; se sono come `La.5.it` (epgshare01) usa `epg-epgshare.xml.gz`. Dettagli nel README.

## Da sapere

- **Repository pubblico.** I log di GitHub Actions sono visibili a tutti, ma i segreti vi compaiono sempre come `***`. Il sito generato non viene mai caricato come artefatto.
- **60 giorni.** In un repository pubblico GitHub sospende i workflow pianificati dopo 60 giorni senza attività (nessun commit). Ti avvisa per email; si riattiva dalla scheda Actions con **Enable workflow**.
- **Orario.** GitHub a volte avvia i workflow pianificati con qualche minuto di ritardo.
- **Domini di anteprima.** Ogni pubblicazione ha anche un indirizzo tipo `https://<codice>.seatv.pages.dev`: contiene gli stessi file, sempre sotto il token.
- **Dominio tuo.** Se vuoi un indirizzo tipo `epg.tuodominio.it`: **Workers & Pages** → **seatv** → **Custom domains**, poi imposta `SEATV_PUBLIC_URL`.

## Se le fonti bloccano GitHub

Il riepilogo di ogni esecuzione dice quante richieste a Tivù e Sky sono andate a buon fine. Se una fonte rifiutasse i server di GitHub (che sono negli Stati Uniti), si può generare il sito dal tuo PC e pubblicarlo da lì, con lo stesso risultato:

```powershell
# Una volta: Python 3.11+ e Node.js installati, poi nella cartella del progetto
python -m venv .venv
.venv\Scripts\activate
pip install -e .
npx wrangler login

# Ogni volta (anche da Utilità di pianificazione di Windows)
$env:SEATV_FEED_TOKEN = "<token>"
$env:SEATV_PUBLIC_URL = "https://seatv.pages.dev"
python -m seatv.build
npx wrangler pages deploy dist --project-name=seatv --branch=main
```

Ricorda che sul tuo PC il DNS 1.1.1.1 dà risposte sbagliate per Tivù: usa 8.8.8.8 e 8.8.4.4.
