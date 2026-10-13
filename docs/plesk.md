# Installazione su Plesk

Questa guida mette SEA-TV su un server Linux con Plesk Obsidian, con:

- la guida TV aggiornata ogni giorno alle **05:00** da un'attività pianificata di Plesk;
- la pagina web che mostra i **7 giorni da oggi in avanti**;
- l'API raggiungibile da fuori su un dominio con HTTPS, protetta da **chiave API**.

Nell'esempio il dominio è `tv.example.it`, l'abbonamento Plesk è `example.it` con utente di sistema `exampleuser`, e il progetto sta in `/var/www/vhosts/example.it/seatv`, fuori da `httpdocs`, così codice, impostazioni e database non sono scaricabili dal web. Sostituisci questi valori con i tuoi.

Ci sono tre modi di far girare l'applicazione:

| | Docker | A. uvicorn + proxy nginx | B. Phusion Passenger |
|---|---|---|---|
| Serve | l'estensione Docker di Plesk | accesso SSH come root | il componente Passenger di Plesk |
| Python sul server | non serve, è nell'immagine | 3.11 o più recente | 3.11 o più recente |
| Aggiornamento alle 05:00 | dentro il container | attività pianificata di Plesk | attività pianificata di Plesk |

Docker è il più semplice se l'estensione è disponibile: è descritto subito qui sotto. Per A e B si parte dalla sezione 1.

## Con Docker

L'immagine contiene già Python e tutto il necessario. All'avvio scarica la guida e poi la riscarica ogni giorno alle 05:00 ora italiana (`SEATV_REFRESH_AT`), quindi non serve nessuna attività pianificata. Il database sta nel volume `/data` e sopravvive agli aggiornamenti del container.

Installa l'estensione da `Estensioni` > cerca **Docker** > Installa, e crea il dominio con il certificato Let's Encrypt come al punto 1 della sezione successiva.

### Con accesso SSH come root (consigliato)

```bash
cd /opt
git clone https://github.com/Rockets92/seatv.git
cd seatv
cp deploy/env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # o qualunque stringa lunga e casuale
nano .env       # metti la chiave in SEATV_API_KEYS; SEATV_DB_PATH e SEATV_SCHEDULER li imposta già docker-compose.yml
docker compose up -d --build
docker compose logs -f   # attendi le righe "ingestione tivu/sky: N canali", poi Ctrl+C
```

Il container ascolta solo su `127.0.0.1:8000`. Per pubblicarlo sul dominio, in Plesk vai su `tv.example.it` > **Impostazioni Apache e nginx** > **Direttive nginx aggiuntive** e incolla il blocco `location ~ ^/ { ... }` della sezione 3A.

Per aggiornare il codice: `git pull && docker compose up -d --build`. I dati restano nel volume.

### Solo dall'interfaccia di Plesk, senza SSH

1. Sul tuo PC, con Docker Desktop, nella cartella del progetto:

   ```bash
   docker build -t seatv .
   docker save seatv -o seatv.tar
   ```

2. In Plesk: **Docker** > **Immagini** > **Carica** e scegli `seatv.tar`.
3. Sull'immagine `seatv` premi **Esegui** e, nelle impostazioni del container:
   - **Avvio automatico** dopo il riavvio: attivo;
   - **Mappatura porte** manuale: porta del container `8000`, porta esterna `8000`, e lascia attivo "solo locale" (in ascolto su 127.0.0.1);
   - **Volumi**: cartella dell'host, es. `/var/www/vhosts/example.it/seatv-data`, montata su `/data`;
   - **Variabili d'ambiente**: `SEATV_API_KEYS` con la tua chiave (le altre hanno già i valori giusti nell'immagine).
4. Nel dominio vai su **Hosting e DNS** > **Regole proxy Docker** > **Aggiungi regola**: URL `/`, container `seatv`, porta `8000`.

Per aggiornare: ricostruisci e ricarica l'immagine, poi ricrea il container con le stesse impostazioni (il volume conserva i dati).

Le sezioni "Usare l'API da fuori" e "Se qualcosa non va" più sotto valgono anche per Docker; i log si vedono con `docker compose logs` o nella scheda del container in Plesk.

## 1. Preparazione (A e B)

1. In Plesk crea il dominio o sottodominio (`Siti web e domini` > `Aggiungi sottodominio`) e attiva il certificato gratuito **Let's Encrypt** (`SSL/TLS`), con il reindirizzamento da HTTP a HTTPS.
2. Serve **Python 3.11 o più recente**. Controlla con `python3 --version`; se è più vecchio installa `python3.11` o `python3.12` dai pacchetti della distribuzione (su AlmaLinux/Rocky: `dnf install python3.12`; su Ubuntu 22.04: `apt install python3.11 python3.11-venv`) e usa quel comando al posto di `python3` qui sotto.
3. Accedi in SSH come utente dell'abbonamento e installa il progetto. Se l'accesso SSH non è attivo per l'utente, abilitalo in `Siti web e domini` > `Accesso al server web` (shell `/bin/bash`).

   ```bash
   cd /var/www/vhosts/example.it
   git clone https://github.com/Rockets92/seatv.git
   cd seatv
   python3 -m venv .venv
   .venv/bin/pip install -e ".[plesk]"
   ```

4. Crea le impostazioni partendo dall'esempio e genera una chiave:

   ```bash
   cp deploy/env.example .env
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   nano .env   # percorso giusto in SEATV_DB_PATH, la chiave generata in SEATV_API_KEYS
   chmod 600 .env
   ```

5. Scarica subito la guida la prima volta (ci vuole qualche minuto: sono 7 giorni per tutti i canali):

   ```bash
   deploy/aggiorna.sh
   ```

   Alla fine il log riporta, per ogni fonte, quanti canali e programmi ha salvato.

## 2. Aggiornamento quotidiano alle 05:00

In Plesk: `Siti web e domini` > `example.it` > **Attività pianificate** > `Aggiungi attività`.

- Tipo: **Esegui un comando**
- Comando: `/var/www/vhosts/example.it/seatv/deploy/aggiorna.sh`
- Esegui: **Giornaliero** alle `05:00` (in formato cron: `0 5 * * *`)
- Notifica: "in caso di errore", così ricevi una mail se una fonte non risponde.

Plesk usa il fuso orario del server: verifica in `Strumenti e impostazioni` > `Impostazioni di sistema` che sia `Europe/Rome`, altrimenti sposta l'ora di conseguenza.

Ogni giorno lo script scarica i 7 giorni da oggi in avanti (`SEATV_DAYS_AHEAD`), sostituisce i programmi cambiati e cancella quelli più vecchi di 7 giorni (`SEATV_RETENTION_DAYS`). L'applicazione legge lo stesso database, quindi non va riavviata.

## 3A. uvicorn dietro il proxy nginx (consigliato)

1. Come root installa il servizio, mettendo nel file l'utente e i percorsi giusti:

   ```bash
   cp /var/www/vhosts/example.it/seatv/deploy/seatv.service /etc/systemd/system/seatv.service
   nano /etc/systemd/system/seatv.service
   systemctl daemon-reload
   systemctl enable --now seatv
   curl -H "X-API-Key: LA_TUA_CHIAVE" http://127.0.0.1:8000/health
   ```

2. In Plesk: `Siti web e domini` > `tv.example.it` > **Impostazioni Apache e nginx** > **Direttive nginx aggiuntive**, incolla:

   ```nginx
   location ~ ^/ {
       proxy_pass http://127.0.0.1:8000;
       proxy_set_header Host $host;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
   }
   ```

   La forma `location ~ ^/` evita l'errore "duplicate location /" che Plesk dà con `location /`.

3. Apri `https://tv.example.it/`: la pagina chiede la chiave una volta e la ricorda in quel browser.

Per aggiornare il codice in futuro: `git pull && .venv/bin/pip install -e ".[plesk]"` come utente dell'abbonamento, poi `systemctl restart seatv` come root.

## 3B. Phusion Passenger

Serve il componente **Phusion Passenger** di Plesk (`Strumenti e impostazioni` > `Aggiornamenti` > `Aggiungi/Rimuovi componenti` > `Supporto per le applicazioni web`). Se il server è di un provider e non vedi questa voce, chiedi a loro di attivarlo.

1. Crea una cartella vuota `public` nel progetto (`mkdir /var/www/vhosts/example.it/seatv/public`) e in `Hosting e DNS` > **Hosting** del dominio imposta la radice dei documenti su `seatv/public`. Così dal web non si raggiunge nessun file del progetto, `.env` compreso.
2. In **Impostazioni Apache e nginx** > **Direttive aggiuntive per HTTP e HTTPS** di Apache incolla:

   ```apache
   PassengerEnabled on
   PassengerAppType wsgi
   PassengerStartupFile passenger_wsgi.py
   PassengerAppRoot /var/www/vhosts/example.it/seatv
   PassengerPython /var/www/vhosts/example.it/seatv/.venv/bin/python
   ```

3. Apri `https://tv.example.it/`. Il file `passenger_wsgi.py` legge `.env`, usa il Python del virtualenv e collega FastAPI a Passenger tramite `a2wsgi`.

Per aggiornare il codice: `git pull && .venv/bin/pip install -e ".[plesk]"`, poi `mkdir -p tmp && touch tmp/restart.txt` per far ripartire l'app.

## Usare l'API da fuori

Ogni richiesta ai dati porta la chiave nell'header `X-API-Key` (oppure, dove non si possono mettere header, nel parametro `?api_key=`):

```bash
curl -H "X-API-Key: LA_TUA_CHIAVE" "https://tv.example.it/now?platform=dtt"
curl -H "X-API-Key: LA_TUA_CHIAVE" "https://tv.example.it/channels/rai1/schedule?date=2026-10-14"
```

La documentazione interattiva è su `https://tv.example.it/docs`: con il pulsante **Authorize** si inserisce la chiave e si provano gli endpoint. La pagina web, `/docs` e i loghi restano aperti; tutti gli endpoint con palinsesti, canali e stato richiedono la chiave.

Per dare l'accesso a più persone o applicazioni metti più chiavi separate da virgola in `SEATV_API_KEYS`; per revocarne una toglila e riavvia l'applicazione (3A: `systemctl restart seatv`; 3B: `touch tmp/restart.txt`). Lasciando `SEATV_API_KEYS` vuota l'API diventa pubblica: prima di farlo ricorda che le fonti non concedono in licenza i dati (vedi la sezione Fonti del README).

## Se qualcosa non va

- **La pagina dice "Nessun canale nel database"**: lancia `deploy/aggiorna.sh` a mano e leggi gli errori.
- **Una fonte risulta in errore in "Fonti"**: spesso è il DNS del server; prova `curl -I https://services.tivulaguida.it` e `curl -I https://apid.sky.it` dal server.
- **502 Bad Gateway (3A)**: il servizio non gira, guarda `journalctl -u seatv -n 50`.
- **Errore di Passenger (3B)**: il log è in `/var/www/vhosts/example.it/logs/error_log`.
