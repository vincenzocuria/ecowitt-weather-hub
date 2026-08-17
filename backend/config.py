import os
from pathlib import Path

# Carica automaticamente il file .env dalla radice del progetto se presente
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    with open(_env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k not in os.environ or os.environ[k] == "":
                    os.environ[k] = v

class Settings:

    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8080"))
    DATA_DIR: str = os.getenv("DATA_DIR", "./data")
    
    # Watchdog Stazione Offline (minuti di assenza dati prima dell'allerta)
    STATION_OFFLINE_TIMEOUT_MIN: int = int(os.getenv("STATION_OFFLINE_TIMEOUT_MIN", "10"))
    
    # Soglie Allarmi Standard
    SOIL_MOISTURE_LOW_THRESHOLD: float = float(os.getenv("SOIL_MOISTURE_LOW_THRESHOLD", "25.0"))
    LIGHTNING_MAX_DISTANCE_KM: float = float(os.getenv("LIGHTNING_MAX_DISTANCE_KM", "30.0"))
    TEMP_FREEZE_THRESHOLD_C: float = float(os.getenv("TEMP_FREEZE_THRESHOLD_C", "1.0"))
    TEMP_HEAT_THRESHOLD_C: float = float(os.getenv("TEMP_HEAT_THRESHOLD_C", "38.0"))
    RAIN_RATE_ALERT_MM_HR: float = float(os.getenv("RAIN_RATE_ALERT_MM_HR", "5.0"))
    
    # Soglie Eventi Anomali
    PRESSURE_DROP_3H_THRESHOLD: float = float(os.getenv("PRESSURE_DROP_3H_THRESHOLD", "2.0"))     # Calo >= 2 hPa in 3h -> burrasca
    TEMP_DROP_1H_THRESHOLD: float = float(os.getenv("TEMP_DROP_1H_THRESHOLD", "4.0"))           # Crollo >= 4°C in 1h
    TEMP_RISE_1H_THRESHOLD: float = float(os.getenv("TEMP_RISE_1H_THRESHOLD", "4.0"))           # Impennata >= 4°C in 1h
    GUST_SPIKE_THRESHOLD_KMH: float = float(os.getenv("GUST_SPIKE_THRESHOLD_KMH", "45.0"))       # Raffica anomala >= 45 km/h
    RAIN_BURST_THRESHOLD_MM_HR: float = float(os.getenv("RAIN_BURST_THRESHOLD_MM_HR", "25.0"))  # Nubifragio >= 25 mm/h
    UV_EXTREME_THRESHOLD: int = int(os.getenv("UV_EXTREME_THRESHOLD", "8"))                      # UV Pericoloso >= 8
    
    # Cooldown (minuti)
    LIGHTNING_COOLDOWN_MIN: int = int(os.getenv("LIGHTNING_COOLDOWN_MIN", "5"))
    SOIL_MOISTURE_COOLDOWN_MIN: int = int(os.getenv("SOIL_MOISTURE_COOLDOWN_MIN", "180"))
    TEMP_ALERT_COOLDOWN_MIN: int = int(os.getenv("TEMP_ALERT_COOLDOWN_MIN", "120"))
    RAIN_ALERT_COOLDOWN_MIN: int = int(os.getenv("RAIN_ALERT_COOLDOWN_MIN", "30"))
    RAIN_START_ALERT_ENABLED: bool = os.getenv("RAIN_START_ALERT_ENABLED", "true").lower() in ("true", "1", "yes")
    RAIN_START_COOLDOWN_MIN: int = int(os.getenv("RAIN_START_COOLDOWN_MIN", "30"))
    RAIN_FORECAST_ALERT_ENABLED: bool = os.getenv("RAIN_FORECAST_ALERT_ENABLED", "true").lower() in ("true", "1", "yes")
    RAIN_FORECAST_PROB_THRESHOLD: int = int(os.getenv("RAIN_FORECAST_PROB_THRESHOLD", "60"))
    RAIN_FORECAST_COOLDOWN_MIN: int = int(os.getenv("RAIN_FORECAST_COOLDOWN_MIN", "180"))
    RECORD_BROKEN_COOLDOWN_MIN: int = int(os.getenv("RECORD_BROKEN_COOLDOWN_MIN", "1"))
    ANOMALY_ALERT_COOLDOWN_MIN: int = int(os.getenv("ANOMALY_ALERT_COOLDOWN_MIN", "60"))
    
    # Nome Stazione & Località
    STATION_NAME: str = os.getenv("STATION_NAME", "Ecowitt Weather Hub")
    LOCATION_NAME: str = os.getenv("LOCATION_NAME", "")
    
    # Coordinate Geografiche (Lat/Lon decimali configurabili da .env)
    LATITUDE: float = float(os.getenv("LATITUDE", "41.9028"))
    LONGITUDE: float = float(os.getenv("LONGITUDE", "12.4964"))
    TIMEZONE: str = os.getenv("TIMEZONE", os.getenv("TZ", "Europe/Rome"))

    def get_tz(self):
        """Restituisce l'oggetto ZoneInfo del fuso orario configurato."""
        from zoneinfo import ZoneInfo
        from datetime import timezone
        try:
            return ZoneInfo(self.TIMEZONE)
        except Exception:
            try:
                return ZoneInfo("Europe/Rome")
            except Exception:
                return timezone.utc

    def now_local(self):
        """Restituisce il datetime corrente timezone-aware nel fuso orario della stazione."""
        from datetime import datetime
        return datetime.now(self.get_tz())
    
    # Notifica Mattutina "Buongiorno Meteo" (Daily Digest)
    DAILY_DIGEST_ENABLED: bool = os.getenv("DAILY_DIGEST_ENABLED", "true").lower() in ("true", "1", "yes")
    DAILY_DIGEST_HOUR: int = int(os.getenv("DAILY_DIGEST_HOUR", "8"))
    DAILY_DIGEST_MINUTE: int = int(os.getenv("DAILY_DIGEST_MINUTE", "0"))

    # Configurazione Accumulatore Aton Green Storage
    ATON_ENABLED: bool = os.getenv("ATON_ENABLED", "true").lower() in ("true", "1", "yes")
    ATON_USERNAME: str = os.getenv("ATON_USERNAME", "Curia")
    ATON_PASSWORD: str = os.getenv("ATON_PASSWORD", "calabro")
    ATON_SN: str = os.getenv("ATON_SN", "R21MY00735F")
    ATON_POLL_INTERVAL_SEC: int = int(os.getenv("ATON_POLL_INTERVAL_SEC", "20"))

    # Soglie Allarmi Energetici
    ENERGY_HIGH_CONSUMPTION_W: float = float(os.getenv("ENERGY_HIGH_CONSUMPTION_W", "3500.0"))
    ENERGY_BATTERY_LOW_PCT: float = float(os.getenv("ENERGY_BATTERY_LOW_PCT", "15.0"))
    ENERGY_BATTERY_FULL_PCT: float = float(os.getenv("ENERGY_BATTERY_FULL_PCT", "98.0"))
    ENERGY_HIGH_CONSUMPTION_COOLDOWN_MIN: int = int(os.getenv("ENERGY_HIGH_CONSUMPTION_COOLDOWN_MIN", "30"))
    ENERGY_BATTERY_COOLDOWN_MIN: int = int(os.getenv("ENERGY_BATTERY_COOLDOWN_MIN", "120"))
    ENERGY_REPORT_HOUR: int = int(os.getenv("ENERGY_REPORT_HOUR", "21")) # Ore 21:00 report serale
    ENERGY_REPORT_ENABLED: bool = os.getenv("ENERGY_REPORT_ENABLED", "true").lower() in ("true", "1", "yes")

    # Configurazione LG ThinQ Climatizzazione Smart
    LG_THINQ_ENABLED: bool = os.getenv("LG_THINQ_ENABLED", "true").lower() in ("true", "1", "yes")
    LG_THINQ_PAT: str = os.getenv("LG_THINQ_PAT", os.getenv("THINQ_PAT", ""))
    LG_THINQ_COUNTRY: str = os.getenv("LG_THINQ_COUNTRY", "IT")
    LG_THINQ_POLL_INTERVAL_SEC: int = int(os.getenv("LG_THINQ_POLL_INTERVAL_SEC", "30"))
    
    # Automazione Clima & Solare Eco
    CLIMATE_SOLAR_ECO_ENABLED: bool = os.getenv("CLIMATE_SOLAR_ECO_ENABLED", "true").lower() in ("true", "1", "yes")
    CLIMATE_SOLAR_SURPLUS_THRESHOLD_W: float = float(os.getenv("CLIMATE_SOLAR_SURPLUS_THRESHOLD_W", "1500.0"))
    CLIMATE_BATTERY_MIN_SOC: float = float(os.getenv("CLIMATE_BATTERY_MIN_SOC", "60.0"))

    # Configurazione Samsung SmartThings
    SMARTTHINGS_ENABLED: bool = os.getenv("SMARTTHINGS_ENABLED", "true").lower() in ("true", "1", "yes")
    SMARTTHINGS_PAT: str = os.getenv("SMARTTHINGS_PAT", os.getenv("SAMSUNG_PAT", ""))
    SMARTTHINGS_POLL_INTERVAL_SEC: int = int(os.getenv("SMARTTHINGS_POLL_INTERVAL_SEC", "30"))

    # Notifiche push (ntfy.sh) & Web Push
    ENABLE_NTFY: bool = True
    NTFY_TOPIC: str = os.getenv("NTFY_TOPIC", "")
    VAPID_CLAIM_EMAIL: str = os.getenv("VAPID_CLAIM_EMAIL", "mailto:admin@example.com")

    # Sicurezza & Accesso Riservato (Persistent Device Token)
    AUTH_TOKEN: str = os.getenv("AUTH_TOKEN", "")
    AUTH_COOKIE_NAME: str = "hub_auth_token"

settings = Settings()





