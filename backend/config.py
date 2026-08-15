import os

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

    # Notifiche push (ntfy.sh)
    ENABLE_NTFY: bool = True
    NTFY_TOPIC: str = os.getenv("NTFY_TOPIC", "")
    VAPID_CLAIM_EMAIL: str = os.getenv("VAPID_CLAIM_EMAIL", "mailto:admin@example.com")

settings = Settings()


