# ??? Ecowitt Weather Hub & Live Smart Dashboard

Hub autonomo, moderno e open-source per stazioni meteo **Ecowitt** e **Sainlogic** (supporto per sensori 7-in-1, sensori suolo **WH51**, rilevatore fulmini **WH57**, qualità dell'aria e gateway **GW1000 / GW1100 / GW2000 / GW3000** o console Wi-Fi).

Include una dashboard web reattiva in tempo reale, **Progressive Web App (PWA)** con notifiche **Web Push su iOS, Android e Desktop**, motore di allarmi scientifici, previsioni orarie avanzate, tracciamento anomalie e **Albo dei Record** con storico completo.

---

## ? Caratteristiche Principali

- ?? **Live Data & Auto-Refresh**: Ricezione in locale dei pacchetti HTTP inviati dalla stazione (protocollo Ecowitt) ogni 16–60 secondi.
- ?? **Database SQLite Indicizzato Locale**: Nessun cloud esterno obbligatorio; storico continuo salvato in un file SQLite autonomo (/data/weather_history.db).
- ?? **Notifiche Push Native (PWA Web Push & ntfy)**:
  - **PWA Web Push**: Ricevi notifiche istantanee direttamente su iPhone (iOS 16.4+ aggiungendo l'app alla Home), Android e PC senza app di terze parti.
  - **ntfy.sh (Opzionale)**: Canale parallelo per notifiche push tramite app ntfy.
- ? **Motore di Allarmi Intelligente con Anti-Spam Cooldown**:
  - ? **Fulmini (WH57)**: Allerta temporale con distanza stimata in km e orario dell'ultima scarica.
  - ?? **Umidità Suolo (WH51)**: Avviso "Annaffia le piante" multicanale (fino a 8 sensori).
  - ?? **Gelo / Caldo Estremo**: Notifiche su soglie critiche di temperatura.
  - ??? **Nubifragi e Pioggia Intensa**: Monitoraggio del tasso di pioggia orario (mm/h).
  - ?? **Variazioni Brusche & Burrasche**: Calcolo caduta pressione in 3h ($\Delta \ge 2\text{ hPa}$), crollo/impennata termica in 1h ($\Delta \ge 4^\circ\text{C}$).
- ?? **Albo dei Record Storici**: Tracciamento dei massimi e minimi storici (temperatura max/min, punto di rugiada, raffica vento, pioggia giornaliera/oraria, pressione max/min, UV, fulmine più vicino) con cronologia di quando sono stati battuti.
- ?? **Calcoli Scientifici Meteo**:
  - Punto di rugiada (Formula di Magnus-Tetens)
  - VPD (*Vapour Pressure Deficit*) per monitoraggio traspirazione piante
  - Tendenza barometrica e previsione locale basata sull'algoritmo barometrico di Zambretti
  - Analisi delle effemeridi (Alba, Tramonto, durata del giorno, culmine solare)
- ?? **Buongiorno Meteo (Daily Digest)**: Notifica mattutina automatica configurabile con riassunto delle minime della notte e previsioni per la giornata.

---

## ??? Architettura & Stack Tecnologico

- **Backend**: Python 3.11, [FastAPI](https://fastapi.tiangolo.com/), Uvicorn, SQLite3, pywebpush.
- **Frontend**: HTML5 moderno / Tailwind-inspired CSS scuro / JavaScript ES6 (Zero framework pesanti, caricamento fulmineo).
- **Deployment**: Docker & Docker Compose, compatibile con qualsiasi NAS (QNAP Container Station, Synology), Raspberry Pi o server Linux/Windows.

---

## ?? Guida all'Installazione con Docker

### 1. Clona il repository
`ash
git clone https://github.com/tuo-username/ecowitt-weather-hub.git
cd ecowitt-weather-hub
`

### 2. Configura le variabili d'ambiente
Copia il file di esempio .env.example in .env:
`ash
cp .env.example .env
`
Modifica il file .env impostando le tue coordinate e parametri:
`env
PORT=8090
TZ=Europe/Rome
TIMEZONE=Europe/Rome

# Coordinate della tua stazione meteo
LATITUDE=41.9028
LONGITUDE=12.4964

# (Opzionale) Canale ntfy se desideri usarlo in parallelo
NTFY_TOPIC=mio_canale_meteo

# (Opzionale) Token Cloudflare Tunnel per accesso remoto sicuro
CLOUDFLARE_TUNNEL_TOKEN=
`

### 3. Avvia l'applicazione con Docker Compose
`ash
docker compose up -d
`
L'interfaccia web sarà immediatamente accessibile su:
?? **http://IP_DEL_TUO_SERVER:8090**

---

## ?? Configurazione della Stazione Meteo (Ecowitt / Sainlogic)

1. Apri l'app **WS View Plus** o **Ecowitt** sul tuo smartphone (connessa alla stessa rete Wi-Fi della stazione).
2. Seleziona il tuo gateway/console (es. GW3000, GW1100, HP2550, WS3900, ecc.).
3. Vai su **Device / Station Settings** -> **Customized Server Upload** (o *Weather Services* -> *Customized*).
4. Imposta i seguenti parametri:
   - **Enable**: Enabled (ON)
   - **Protocol type**: Ecowitt (consigliato) o Wunderground
   - **Server IP / Hostname**: Inserisci l'IP locale del server o NAS (es. 192.168.1.250)
   - **Path**: /api/ecowitt
   - **Port**: 8090 (o la porta configurata nel tuo file .env)
   - **Upload Interval**: 16 - 60 secondi
5. Clicca su **Save**. La stazione inizierà a trasmettere i dati al tuo Hub locale!

---

## ?? Installazione come PWA e Notifiche Push

1. **iPhone / iPad (iOS 16.4+)**:
   - Apri l'indirizzo della dashboard in **Safari**.
   - Tocca l'icona di condivisione (quadrato con freccia verso l'alto) e seleziona **"Aggiungi alla schermata Home"**.
   - Apri l'app dall'icona creata e vai nella sezione **Allarmi & Notifiche** -> Clicca su **"Attiva Notifiche Push PWA"**.
2. **Android**:
   - Apri l'indirizzo in Chrome/Edge e tocca **"Installa app"** o seleziona **"Attiva Notifiche Push"** dalla sezione allarmi.
3. **PC / Mac / Linux**:
   - Installa come desktop app tramite l'icona nella barra degli indirizzi del browser.

---

## ?? Backup dei Dati

Tutti i dati storici, l'albo dei record e le registrazioni push sono conservati nel database SQLite montato sul volume /data:
* File database: /data/weather_history.db
* File chiavi VAPID: /data/vapid_private.pem e /data/vapid_public_b64.txt

Per eseguire un backup completo, è sufficiente salvare la directory o il volume /data (tramite snapshot, rsync o strumenti di backup del NAS come HBS3 su QNAP / HyperBackup su Synology).

---

## ?? Licenza

Questo progetto è rilasciato sotto la licenza **PolyForm Noncommercial License 1.0.0**.

- ? **Uso personale, di studio e hobbistico:** Libero e gratuito per chiunque.
- ? **Uso commerciale / A scopo di lucro:** È severamente vietata la rivendita, l'inclusione in prodotti commerciali o la monetizzazione del software senza esplicita autorizzazione dell'autore.

Per maggiori dettagli consultare il file [LICENSE](LICENSE).
