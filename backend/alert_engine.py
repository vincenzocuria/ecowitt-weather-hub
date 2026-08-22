import os
import json
import time
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from backend.config import settings
from backend.notifier import notifier
from backend.database import check_and_update_records, get_pressure_trend, get_temp_1h_change, get_station_status


logger = logging.getLogger("ecowitt_alert_engine")

class AlertEngine:
    def __init__(self):
        self._state_file = os.path.join(settings.DATA_DIR, "alert_state.json")
        self.last_lightning_epoch = None
        self.last_lightning_count = 0
        self.last_lightning_alert = 0.0
        self.last_soil_alert: Dict[str, float] = {}
        self.last_soil_wet_alert: Dict[str, float] = {}
        self.last_freeze_alert = 0.0
        self.last_heat_alert = 0.0
        self.last_rain_alert = 0.0
        self.last_rain_start_alert = 0.0
        self.is_raining = False
        self.last_rain_time = 0.0
        self.last_rain_forecast_alert = 0.0
        self.last_record_alert = 0.0
        
        # Anomaly cooldowns
        self.last_storm_alert = 0.0
        self.last_storm_alert_press = None
        self.last_wind_spike_alert = 0.0
        self.last_rain_burst_alert = 0.0
        self.last_uv_alert = 0.0
        self.last_temp_plunge_alert = 0.0
        
        # Offline Watchdog state
        self.is_station_offline = False
        self.last_offline_alert_time = 0.0
        self.last_battery_alert: Dict[str, float] = {}

        # Energy Alert state (Aton Storage)
        self.last_high_consumption_alert = 0.0
        self.last_battery_low_alert = 0.0
        self.last_battery_full_alert = 0.0
        self.last_evening_energy_date: Optional[str] = None
        self._was_battery_full = False

        # Digest & Maintenance state
        self.last_digest_date: Optional[str] = None
        self.last_maintenance_date: Optional[str] = None

        # SmartThings & Leak states
        self._last_presence_is_present: Optional[bool] = None
        self._presence_away_timestamp: Optional[float] = None
        self._last_washer_was_running: bool = False
        self._last_solar_appliance_alert: float = 0.0
        self.last_leak_alert: Dict[str, float] = {}
        self.last_record_alert_by_key: Dict[str, float] = {}

        # Climate & Fridge Automations states (LG ThinQ)
        self.last_climate_away_alert: float = 0.0
        self.last_climate_runtime_alert: Dict[str, float] = {}
        self.last_climate_night_alert: Dict[str, float] = {}
        self.last_climate_solar_alert: Dict[str, float] = {}
        self.last_climate_battery_alert: Dict[str, float] = {}
        self.last_fridge_door_alert: float = 0.0
        self.last_fridge_away_alert: float = 0.0
        self.last_fridge_solar_alert: float = 0.0

        # Carica lo stato persistente da disco o DB
        self._load_state()

    def _save_state(self):
        """Salva lo stato corrente e i cooldown degli allarmi su file JSON persistente."""
        try:
            os.makedirs(settings.DATA_DIR, exist_ok=True)
            state_data = {
                "saved_at": time.time(),
                "last_lightning_epoch": self.last_lightning_epoch,
                "last_lightning_count": self.last_lightning_count,
                "last_lightning_alert": self.last_lightning_alert,
                "last_soil_alert": self.last_soil_alert,
                "last_soil_wet_alert": self.last_soil_wet_alert,
                "last_freeze_alert": self.last_freeze_alert,
                "last_heat_alert": self.last_heat_alert,
                "last_rain_alert": self.last_rain_alert,
                "last_rain_start_alert": self.last_rain_start_alert,
                "is_raining": self.is_raining,
                "last_rain_time": self.last_rain_time,
                "last_rain_forecast_alert": self.last_rain_forecast_alert,
                "last_record_alert": self.last_record_alert,
                "last_storm_alert": self.last_storm_alert,
                "last_storm_alert_press": self.last_storm_alert_press,
                "last_wind_spike_alert": self.last_wind_spike_alert,
                "last_rain_burst_alert": self.last_rain_burst_alert,
                "last_uv_alert": self.last_uv_alert,
                "last_temp_plunge_alert": self.last_temp_plunge_alert,
                "is_station_offline": self.is_station_offline,
                "last_offline_alert_time": self.last_offline_alert_time,
                "last_battery_alert": self.last_battery_alert,
                "last_high_consumption_alert": self.last_high_consumption_alert,
                "last_battery_low_alert": self.last_battery_low_alert,
                "last_battery_full_alert": self.last_battery_full_alert,
                "last_evening_energy_date": self.last_evening_energy_date,
                "last_digest_date": self.last_digest_date,
                "last_maintenance_date": self.last_maintenance_date,
                "_was_battery_full": self._was_battery_full,
                "_last_presence_is_present": self._last_presence_is_present,
                "_presence_away_timestamp": self._presence_away_timestamp,
                "_last_washer_was_running": self._last_washer_was_running,
                "_last_solar_appliance_alert": self._last_solar_appliance_alert,
                "last_leak_alert": self.last_leak_alert,
                "last_record_alert_by_key": self.last_record_alert_by_key,
                "last_climate_away_alert": self.last_climate_away_alert,
                "last_climate_runtime_alert": self.last_climate_runtime_alert,
                "last_climate_night_alert": self.last_climate_night_alert,
                "last_climate_solar_alert": self.last_climate_solar_alert,
                "last_climate_battery_alert": self.last_climate_battery_alert,
                "last_fridge_door_alert": self.last_fridge_door_alert,
                "last_fridge_away_alert": self.last_fridge_away_alert,
                "last_fridge_solar_alert": self.last_fridge_solar_alert,
            }
            tmp_path = self._state_file + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(state_data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._state_file)
        except Exception as e:
            logger.warning(f"[ALERT-STATE] Impossibile salvare cache stato allarmi: {e}")

    def _load_state(self):
        """Carica lo stato da disk cache o ricostruisce lo stato dal DB."""
        loaded_from_disk = False
        if os.path.exists(self._state_file):
            try:
                with open(self._state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.last_lightning_epoch = data.get("last_lightning_epoch", self.last_lightning_epoch)
                self.last_lightning_count = data.get("last_lightning_count", self.last_lightning_count)
                self.last_lightning_alert = data.get("last_lightning_alert", self.last_lightning_alert)
                self.last_soil_alert = data.get("last_soil_alert", self.last_soil_alert)
                self.last_soil_wet_alert = data.get("last_soil_wet_alert", self.last_soil_wet_alert)
                self.last_freeze_alert = data.get("last_freeze_alert", self.last_freeze_alert)
                self.last_heat_alert = data.get("last_heat_alert", self.last_heat_alert)
                self.last_rain_alert = data.get("last_rain_alert", self.last_rain_alert)
                self.last_rain_start_alert = data.get("last_rain_start_alert", self.last_rain_start_alert)
                self.is_raining = data.get("is_raining", self.is_raining)
                self.last_rain_time = data.get("last_rain_time", self.last_rain_time)
                self.last_rain_forecast_alert = data.get("last_rain_forecast_alert", self.last_rain_forecast_alert)
                self.last_record_alert = data.get("last_record_alert", self.last_record_alert)
                self.last_storm_alert = data.get("last_storm_alert", self.last_storm_alert)
                self.last_storm_alert_press = data.get("last_storm_alert_press", self.last_storm_alert_press)
                self.last_wind_spike_alert = data.get("last_wind_spike_alert", self.last_wind_spike_alert)
                self.last_rain_burst_alert = data.get("last_rain_burst_alert", self.last_rain_burst_alert)
                self.last_uv_alert = data.get("last_uv_alert", self.last_uv_alert)
                self.last_temp_plunge_alert = data.get("last_temp_plunge_alert", self.last_temp_plunge_alert)
                self.is_station_offline = data.get("is_station_offline", self.is_station_offline)
                self.last_offline_alert_time = data.get("last_offline_alert_time", self.last_offline_alert_time)
                self.last_battery_alert = data.get("last_battery_alert", self.last_battery_alert)
                self.last_high_consumption_alert = data.get("last_high_consumption_alert", self.last_high_consumption_alert)
                self.last_battery_low_alert = data.get("last_battery_low_alert", self.last_battery_low_alert)
                self.last_battery_full_alert = data.get("last_battery_full_alert", self.last_battery_full_alert)
                self.last_evening_energy_date = data.get("last_evening_energy_date", self.last_evening_energy_date)
                self.last_digest_date = data.get("last_digest_date", self.last_digest_date)
                self.last_maintenance_date = data.get("last_maintenance_date", self.last_maintenance_date)
                self._was_battery_full = data.get("_was_battery_full", self._was_battery_full)
                self._last_presence_is_present = data.get("_last_presence_is_present", self._last_presence_is_present)
                self._presence_away_timestamp = data.get("_presence_away_timestamp", self._presence_away_timestamp)
                self._last_washer_was_running = data.get("_last_washer_was_running", self._last_washer_was_running)
                self._last_solar_appliance_alert = data.get("_last_solar_appliance_alert", self._last_solar_appliance_alert)
                self.last_leak_alert = data.get("last_leak_alert", self.last_leak_alert)
                self.last_record_alert_by_key = data.get("last_record_alert_by_key", self.last_record_alert_by_key)
                self.last_climate_away_alert = data.get("last_climate_away_alert", self.last_climate_away_alert)
                self.last_climate_runtime_alert = data.get("last_climate_runtime_alert", self.last_climate_runtime_alert)
                self.last_climate_night_alert = data.get("last_climate_night_alert", self.last_climate_night_alert)
                self.last_climate_solar_alert = data.get("last_climate_solar_alert", self.last_climate_solar_alert)
                self.last_climate_battery_alert = data.get("last_climate_battery_alert", self.last_climate_battery_alert)
                self.last_fridge_door_alert = data.get("last_fridge_door_alert", self.last_fridge_door_alert)
                self.last_fridge_away_alert = data.get("last_fridge_away_alert", self.last_fridge_away_alert)
                self.last_fridge_solar_alert = data.get("last_fridge_solar_alert", self.last_fridge_solar_alert)
                loaded_from_disk = True
                logger.info("[ALERT-STATE] Cache stato allarmi caricata con successo da disco.")
            except Exception as e:
                logger.warning(f"[ALERT-STATE] Errore lettura cache stato allarmi da disco: {e}")

        # Se non presente su disco, idrata dai log del DB SQLite
        if not loaded_from_disk:
            self._hydrate_from_db()

    def _hydrate_from_db(self):
        """Idrata i cooldown e gli stati dagli alert_logs e weather_records nel DB."""
        try:
            from backend.database import get_latest_alerts_by_type, get_latest_reading
            latest_alerts = get_latest_alerts_by_type()
            now_dt = settings.now_local()
            today_str = now_dt.strftime("%Y-%m-%d")

            for alert_type, info in latest_alerts.items():
                ts_str = info.get("timestamp")
                if not ts_str:
                    continue
                try:
                    dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                    ts = dt.timestamp()
                    local_dt = dt.astimezone(settings.get_tz())
                    alert_date_str = local_dt.strftime("%Y-%m-%d")
                except Exception:
                    continue

                if alert_type == "digest" and alert_date_str == today_str:
                    self.last_digest_date = today_str
                elif alert_type == "energy_digest" and alert_date_str == today_str:
                    self.last_evening_energy_date = today_str
                elif alert_type == "freeze":
                    self.last_freeze_alert = max(self.last_freeze_alert, ts)
                elif alert_type == "heatwave":
                    self.last_heat_alert = max(self.last_heat_alert, ts)
                elif alert_type == "rain":
                    self.last_rain_alert = max(self.last_rain_alert, ts)
                elif alert_type == "rain_start":
                    self.last_rain_start_alert = max(self.last_rain_start_alert, ts)
                elif alert_type == "rain_forecast":
                    self.last_rain_forecast_alert = max(self.last_rain_forecast_alert, ts)
                elif alert_type == "storm":
                    self.last_storm_alert = max(self.last_storm_alert, ts)
                elif alert_type == "wind_spike":
                    self.last_wind_spike_alert = max(self.last_wind_spike_alert, ts)
                elif alert_type == "lightning":
                    self.last_lightning_alert = max(self.last_lightning_alert, ts)
                elif alert_type == "uv_extreme":
                    self.last_uv_alert = max(self.last_uv_alert, ts)
                elif alert_type == "anomaly":
                    self.last_temp_plunge_alert = max(self.last_temp_plunge_alert, ts)
                elif alert_type == "energy_high":
                    self.last_high_consumption_alert = max(self.last_high_consumption_alert, ts)
                elif alert_type == "battery_full":
                    self.last_battery_full_alert = max(self.last_battery_full_alert, ts)
                elif alert_type == "battery_low":
                    self.last_battery_low_alert = max(self.last_battery_low_alert, ts)
                elif alert_type == "solar_synergy_appliances":
                    self._last_solar_appliance_alert = max(self._last_solar_appliance_alert, ts)
                elif alert_type == "soil_dry":
                    extra = info.get("data") or {}
                    ch = extra.get("channel")
                    if ch:
                        self.last_soil_alert[str(ch)] = max(self.last_soil_alert.get(str(ch), 0.0), ts)

            # Verifica stato pioggia dall'ultima lettura
            latest_read = get_latest_reading()
            if latest_read:
                rate = latest_read.get("rain_rate_mm_hr", 0.0) or 0.0
                if rate > 0.0:
                    self.is_raining = True
                    self.last_rain_time = time.time()

            logger.info("[ALERT-STATE] Idratazione stato allarmi da DB completata con successo.")
            self._save_state()
        except Exception as e:
            logger.warning(f"[ALERT-STATE] Errore idratazione stato da DB: {e}")


    def evaluate(self, current_data: Dict[str, Any]):
        now = time.time()
        
        # Se riceve dati, reimposta stato offline se era offline
        if self.is_station_offline:
            self.is_station_offline = False
            self._save_state()
            notifier.send_alert(
                alert_type="online",
                title="🟢 Stazione Meteo Riconnessa!",
                message="La stazione meteo ha ripreso la trasmissione regolare dei dati.",
                priority="high"
            )

        # 1. Controllo e aggiornamento Albo dei Record
        try:
            broken_records = check_and_update_records(current_data)
            if broken_records:
                for rec in broken_records:
                    key = rec["key"]
                    old_str = f" (precedente: {rec['old_value']} {rec['unit']})" if rec['old_value'] is not None else ""
                    msg = f"🏆 Nuovo record assoluto per '{rec['title']}': {rec['new_value']} {rec['unit']}{old_str}!"
                    logger.info(msg)
                    if rec.get("should_notify", True) and self._should_send_record_alert(key, now):
                        self._save_state()
                        notifier.send_alert(
                            alert_type="record",
                            title=f"🏆 Record Battuto: {rec['title']}!",
                            message=f"Registrato nuovo valore estremo: {rec['new_value']} {rec['unit']}{old_str}.",
                            priority="high",
                            extra_data={"record_key": rec["key"], "value": str(rec["new_value"])}
                        )
        except Exception as e:
            logger.error(f"Errore durante verifica record: {e}")

        # 2. Controllo Eventi Anomali
        self._check_anomalies(current_data, now)

        # 3. Controllo Condizioni Meteo Standard
        self._check_lightning(current_data, now)
        self._check_soil_moisture(current_data, now)
        self._check_temperatures(current_data, now)
        self._check_rain(current_data, now)
        self._check_water_leaks(current_data, now)

        # 4. Controllo Batterie Sensori
        self._check_batteries(current_data, now)

    def _should_send_record_alert(self, key: str, now: float) -> bool:
        """Verifica se per una specifica chiave di record è trascorso il tempo di cooldown."""
        last_time = self.last_record_alert_by_key.get(key, 0.0)
        cooldown_sec = getattr(settings, "RECORD_BROKEN_COOLDOWN_MIN", 720) * 60
        if (now - last_time) >= cooldown_sec:
            self.last_record_alert_by_key[key] = now
            self.last_record_alert = now
            return True
        return False

    def _check_water_leaks(self, data: Dict[str, Any], now: float):
        leaks = data.get("leak_sensors", {})
        for ch, status in leaks.items():
            if status in (1, "1"):
                last_time = self.last_leak_alert.get(ch, 0.0)
                if (now - last_time) >= 1800:  # allarme ogni 30 min se persiste
                    self.last_leak_alert[ch] = now
                    self._save_state()
                    notifier.send_alert(
                        alert_type="leak",
                        title=f"🚨 ALLARME ALLAGAMENTO ({ch.upper()})!",
                        message=f"Rilevata presenza d'acqua dal sensore perdite {ch.upper()}! Verificare immediatamente.",
                        priority="urgent",
                        extra_data={"leak_channel": ch}
                    )

    def _check_anomalies(self, data: Dict[str, Any], now: float):
        # A. Crollo Barometrico Rapido (Burrasca / Tempesta imminente)
        press = data.get("pressure_rel_hpa")
        if press is not None:
            trend_info = get_pressure_trend(press)
            if trend_info.get("is_storm_alert"):
                cooldown_sec = getattr(settings, "STORM_ALERT_COOLDOWN_MIN", 240) * 60
                time_elapsed = (now - self.last_storm_alert) >= cooldown_sec
                # Se è già stato inviato un avviso per questa depressione, non re-inviare continuamente;
                # invia solo se c'è un crollo ulteriore significativo (>= 1.5 hPa) rispetto alla pressione dell'ultimo allarme
                further_drop = (
                    self.last_storm_alert_press is not None and 
                    (press <= self.last_storm_alert_press - 1.5) and 
                    (now - self.last_storm_alert) >= 3600
                )
                
                if (self.last_storm_alert == 0.0) or time_elapsed or further_drop:
                    self.last_storm_alert = now
                    self.last_storm_alert_press = press
                    self._save_state()
                    notifier.send_alert(
                        alert_type="storm",
                        title="⚠️ Allerta Burrasca: Crollo Pressione!",
                        message=f"La pressione barometrica è crollata a {press} hPa ({trend_info['diff']} hPa nelle ultime 3h). Forte peggioramento o tempesta in arrivo.",
                        priority="urgent",
                        extra_data={"pressure_drop": str(trend_info['diff']), "pressure": str(press)}
                    )
            else:
                # Se la tendenza non è più in allarme burrasca da almeno 2 ore, resetta la pressione di riferimento
                if self.last_storm_alert_press is not None and (now - self.last_storm_alert) >= 7200:
                    self.last_storm_alert_press = None
                    self._save_state()

        # B. Raffica Anomala Improvvisa (Wind Spike)
        gust = data.get("wind_gust_kmh")
        speed = data.get("wind_speed_kmh") or 0.0
        if gust is not None and gust >= settings.GUST_SPIKE_THRESHOLD_KMH:
            if (now - self.last_wind_spike_alert) >= (settings.ANOMALY_ALERT_COOLDOWN_MIN * 60):
                self.last_wind_spike_alert = now
                self._save_state()
                notifier.send_alert(
                    alert_type="wind_spike",
                    title="💨 Forte Raffica di Vento Rilevata!",
                    message=f"Rilevata raffica improvvisa a {gust} km/h (vento medio: {speed} km/h). Attenzione a oggetti all'aperto.",
                    priority="high",
                    extra_data={"gust_kmh": str(gust)}
                )

        # C. Nubifragio / Bomba d'acqua (Rain Burst)
        rain_rate = data.get("rain_rate_mm_hr")
        if rain_rate is not None and rain_rate >= settings.RAIN_BURST_THRESHOLD_MM_HR:
            if (now - self.last_rain_burst_alert) >= (settings.ANOMALY_ALERT_COOLDOWN_MIN * 60):
                self.last_rain_burst_alert = now
                self._save_state()
                notifier.send_alert(
                    alert_type="rain",
                    title="🌧️ Allerta Nubifragio in Corso!",
                    message=f"Intensità di pioggia estrema: {rain_rate} mm/h! Rischio allagamenti rapidi.",
                    priority="urgent",
                    extra_data={"rain_rate": str(rain_rate)}
                )

        # D. Sbalzo Termico Repentino (Crollo o Impennata in 1h)
        temp = data.get("temp_c")
        if temp is not None:
            diff, is_plunge, is_spike = get_temp_1h_change(temp)
            if (is_plunge or is_spike) and (now - self.last_temp_plunge_alert) >= (settings.ANOMALY_ALERT_COOLDOWN_MIN * 60):
                self.last_temp_plunge_alert = now
                self._save_state()
                direction_txt = "crollo termico" if is_plunge else "impennata termica"
                notifier.send_alert(
                    alert_type="anomaly",
                    title=f"🌡️ Sbalzo Termico Repentino ({diff:+}°C in 1h)!",
                    message=f"Rilevato un forte {direction_txt}: la temperatura è ora {temp}°C (variazione di {diff:+}°C nell'ultima ora).",
                    priority="normal",
                    extra_data={"temp_diff_1h": str(diff)}
                )

        # E. Indice UV Estremo
        uv = data.get("uv_index")
        if uv is not None and uv >= settings.UV_EXTREME_THRESHOLD:
            if (now - self.last_uv_alert) >= (settings.ANOMALY_ALERT_COOLDOWN_MIN * 60):
                self.last_uv_alert = now
                self._save_state()
                notifier.send_alert(
                    alert_type="uv_extreme",
                    title="☀️ Indice UV Pericoloso / Estremo!",
                    message=f"Indice UV salito a {uv}! Rischio scottature in pochi minuti. Evitare esposizione diretta al sole.",
                    priority="normal",
                    extra_data={"uv_index": str(uv)}
                )

    def _check_lightning(self, data: Dict[str, Any], now: float):
        lightning = data.get("lightning", {})
        strike_epoch = lightning.get("last_strike_epoch")
        count = lightning.get("count_total") or 0
        dist_km = lightning.get("distance_km")

        if self.last_lightning_epoch is None:
            self.last_lightning_epoch = strike_epoch
            self.last_lightning_count = count
            self._save_state()
            return

        is_new_strike = False
        if strike_epoch and strike_epoch != self.last_lightning_epoch:
            is_new_strike = True
            self.last_lightning_epoch = strike_epoch
            self._save_state()
        elif count > self.last_lightning_count:
            is_new_strike = True
            self.last_lightning_count = count
            self._save_state()

        if is_new_strike and dist_km is not None and dist_km <= settings.LIGHTNING_MAX_DISTANCE_KM:
            if (now - self.last_lightning_alert) >= (settings.LIGHTNING_COOLDOWN_MIN * 60):
                self.last_lightning_alert = now
                self._save_state()
                notifier.send_alert(
                    alert_type="lightning",
                    title="⚡ Temporale in arrivo!",
                    message=f"Fulmine rilevato a {dist_km} km dalla tua stazione meteo!",
                    priority="high",
                    extra_data={"distance_km": str(dist_km)}
                )

    def _check_soil_moisture(self, data: Dict[str, Any], now: float):
        soil = data.get("soil_moisture", {})
        if not soil:
            return

        # 1. Recupera alias personalizzati dei sensori (se configurati)
        from backend.database import get_sensor_aliases
        aliases = get_sensor_aliases()

        # 2. Controllo se sta già piovendo ora
        rain_rate = data.get("rain_rate_mm_hr", 0.0) or 0.0
        daily_rain = data.get("daily_rain_mm", 0.0) or 0.0
        if rain_rate > 0.0 or (self.is_raining and daily_rain >= 0.5):
            logger.info("Controllo irrigazione suolo: precipitazioni attualmente in corso, notifica non necessaria.")
            return

        # 3. Controllo previsione meteo pioggia nelle prossime ore (Open-Meteo ECMWF/ICON)
        from backend.forecast_service import forecast_service
        rain_imminent = False
        rain_forecast_str = ""
        try:
            fc = forecast_service.fetch_open_meteo()
            if fc and "hourly_next_36h" in fc:
                # Controlla le prossime 6-8 ore
                upcoming_hours = fc["hourly_next_36h"][:8]
                max_prob = max((h.get("rain_prob_pct", 0) for h in upcoming_hours), default=0)
                sum_rain = sum((h.get("rain_mm", 0.0) for h in upcoming_hours))
                
                # Se probabilità >= 50% o accumulo previsto >= 1.0mm
                if max_prob >= 50 or sum_rain >= 1.0:
                    rain_imminent = True
                    rain_forecast_str = f"Prevista pioggia a breve ({max_prob}% probabilità, ~{sum_rain:.1f} mm)."
        except Exception as e:
            logger.warning(f"Errore verifica previsione pioggia per allerta suolo: {e}")

        # Se pioverà a breve, sopprime con intelligenza l'avviso di annaffiare per risparmiare acqua
        if rain_imminent:
            logger.info(f"Avviso irrigazione suolo soppresso: {rain_forecast_str}")
            return

        # 4. Calcolo consiglio sull'orario ideale di irrigazione (evita ore calde / pieno sole)
        local_hour = settings.now_local().hour
        solar = data.get("solar_radiation", 0.0) or 0.0
        temp_c = data.get("temp_c", 20.0) or 20.0
        
        advice_timing = ""
        if 11 <= local_hour <= 17 and (solar > 250 or temp_c > 27):
            advice_timing = " ☀️ Consiglio: evita di annaffiare sotto il sole cocente; preferisci stasera dopo il tramonto o domattina all'alba per evitare l'evaporazione rapida."
        elif 6 <= local_hour <= 9:
            advice_timing = " 🌅 Momento ideale: l'alba consente l'assorbimento radicale ottimale."
        elif 19 <= local_hour <= 23:
            advice_timing = " 🌙 Momento ideale: annaffiare di sera idrata il terreno per tutta la notte."

        # 5. Verifica soglia umidità per ciascun canale suolo
        for channel, value in soil.items():
            if value is None:
                continue
            sensor_name = aliases.get(f"soil_{channel}") or aliases.get(channel) or f"Sensore Terreno ({channel})"
            
            # Caso A: Terreno Secco (sotto soglia minima)
            if value <= settings.SOIL_MOISTURE_LOW_THRESHOLD:
                last_time = self.last_soil_alert.get(channel, 0.0)
                if (now - last_time) >= (settings.SOIL_MOISTURE_COOLDOWN_MIN * 60):
                    self.last_soil_alert[channel] = now
                    self._save_state()
                    
                    msg = f"L'umidità di '{sensor_name}' è scesa al {value}% (soglia minima: {settings.SOIL_MOISTURE_LOW_THRESHOLD}%). Nessuna pioggia prevista a breve.{advice_timing}"
                    
                    notifier.send_alert(
                        alert_type="soil_dry",
                        title=f"🌱 Annaffia: {sensor_name}",
                        message=msg,
                        priority="normal",
                        extra_data={"channel": channel, "moisture": str(value), "sensor_name": sensor_name}
                    )
            # Caso B: Terreno Troppo Umido / Saturo / Rischio Ristagno (sopra soglia massima)
            elif value >= settings.SOIL_MOISTURE_HIGH_THRESHOLD:
                last_wet_time = self.last_soil_wet_alert.get(channel, 0.0)
                if (now - last_wet_time) >= (settings.SOIL_MOISTURE_COOLDOWN_MIN * 60):
                    self.last_soil_wet_alert[channel] = now
                    self._save_state()

                    msg = f"L'umidità di '{sensor_name}' è salita al {value}% (soglia di saturazione: {settings.SOIL_MOISTURE_HIGH_THRESHOLD}%). Rischio ristagno idrico ed asfissia radicale; sospendi l'irrigazione."

                    notifier.send_alert(
                        alert_type="soil_wet",
                        title=f"⚠️ Terreno Troppo Umido: {sensor_name}",
                        message=msg,
                        priority="normal",
                        extra_data={"channel": channel, "moisture": str(value), "sensor_name": sensor_name}
                    )
            # Caso C: Ripristino Condizione Ottimale
            elif settings.SOIL_MOISTURE_LOW_THRESHOLD < value < settings.SOIL_MOISTURE_HIGH_THRESHOLD:
                # Ripristino da secca
                last_time = self.last_soil_alert.get(channel, 0.0)
                if last_time > 0 and (now - last_time) < (24 * 3600):
                    self.last_soil_alert[channel] = 0.0
                    self._save_state()
                    notifier.send_alert(
                        alert_type="soil_recovered",
                        title=f"💧 Terreno Irrigato: {sensor_name}",
                        message=f"L'umidità di '{sensor_name}' è risalita al {value}% (condizione ottimale).",
                        priority="low",
                        extra_data={"channel": channel, "moisture": str(value), "sensor_name": sensor_name}
                    )
                # Reset allarme terreno saturo
                if self.last_soil_wet_alert.get(channel, 0.0) > 0:
                    self.last_soil_wet_alert[channel] = 0.0
                    self._save_state()

    def _check_temperatures(self, data: Dict[str, Any], now: float):
        temp = data.get("temp_c")
        if temp is None:
            return

        if temp <= settings.TEMP_FREEZE_THRESHOLD_C:
            if (now - self.last_freeze_alert) >= (settings.TEMP_ALERT_COOLDOWN_MIN * 60):
                self.last_freeze_alert = now
                self._save_state()
                notifier.send_alert(
                    alert_type="freeze",
                    title="❄️ Allerta Gelo",
                    message=f"Temperatura scesa a {temp}°C! Rischio gelata per piante ed esterni.",
                    priority="high",
                    extra_data={"temp_c": str(temp)}
                )
        elif temp >= settings.TEMP_HEAT_THRESHOLD_C:
            if (now - self.last_heat_alert) >= (settings.TEMP_ALERT_COOLDOWN_MIN * 60):
                self.last_heat_alert = now
                self._save_state()
                notifier.send_alert(
                    alert_type="heatwave",
                    title="🔥 Caldo Estremo",
                    message=f"Temperatura salita a {temp}°C! Proteggersi dal caldo.",
                    priority="normal",
                    extra_data={"temp_c": str(temp)}
                )

    def _check_rain(self, data: Dict[str, Any], now: float):
        rain_rate = data.get("rain_rate_mm_hr")
        event_rain = data.get("event_rain_mm")

        is_current_rain = (rain_rate is not None and rain_rate > 0.0) or (event_rain is not None and event_rain > 0.0)

        # 1. Inizio Pioggia Istantaneo (Rilevamento prime gocce / transizione da asciutto a pioggia)
        if is_current_rain:
            self.last_rain_time = now
            if not self.is_raining:
                self.is_raining = True
                self._save_state()
                if settings.RAIN_START_ALERT_ENABLED and (now - self.last_rain_start_alert) >= (settings.RAIN_START_COOLDOWN_MIN * 60):
                    self.last_rain_start_alert = now
                    self._save_state()
                    rate_str = f" (intensità: {rain_rate} mm/h)" if (rain_rate and rain_rate > 0) else ""
                    notifier.send_alert(
                        alert_type="rain_start",
                        title="🌧️ Ha Iniziato a Piovere!",
                        message=f"Rilevate precipitazioni dalla stazione meteo{rate_str}. Ricordati di chiudere le finestre o ritirare il bucato!",
                        priority="high",
                        extra_data={"rain_rate": str(rain_rate or 0.0), "event_rain": str(event_rain or 0.0)}
                    )
            else:
                self._save_state()
        else:
            # Se per oltre 15 minuti non si registrano precipitazioni, reimposta lo stato asciutto
            if self.is_raining and (now - self.last_rain_time) >= 900:
                self.is_raining = False
                self._save_state()

        # 2. Pioggia Intensa (Standard)
        if rain_rate is not None and rain_rate >= settings.RAIN_RATE_ALERT_MM_HR and rain_rate < settings.RAIN_BURST_THRESHOLD_MM_HR:
            if (now - self.last_rain_alert) >= (settings.RAIN_ALERT_COOLDOWN_MIN * 60):
                self.last_rain_alert = now
                self._save_state()
                notifier.send_alert(
                    alert_type="rain",
                    title="🌧️ Pioggia Intensa",
                    message=f"Forte rovescio di pioggia in corso: intensità {rain_rate} mm/h.",
                    priority="normal",
                    extra_data={"rain_rate_mm_hr": str(rain_rate)}
                )

    def _check_batteries(self, data: Dict[str, Any], now: float):
        batteries = data.get("batteries", {})
        # WH65 Sensore 7-in-1
        wh65 = batteries.get("wh65")
        if wh65 in ("1", 1):
            last_time = self.last_battery_alert.get("wh65", 0.0)
            if (now - last_time) >= (24 * 3600):
                self.last_battery_alert["wh65"] = now
                self._save_state()
                notifier.send_alert(
                    alert_type="battery_low",
                    title="🪫 Batteria Bassa: Sensore 7-in-1",
                    message="La batteria del blocco sensori esterno 7-in-1 (WH65) è quasi scarica. Si consiglia la sostituzione delle pile.",
                    priority="high"
                )

        # WH57 Sensore Fulmini
        wh57 = batteries.get("wh57")
        if wh57 in ("1", 1):
            last_time = self.last_battery_alert.get("wh57", 0.0)
            if (now - last_time) >= (24 * 3600):
                self.last_battery_alert["wh57"] = now
                self._save_state()
                notifier.send_alert(
                    alert_type="battery_low",
                    title="🪫 Batteria Bassa: Sensore Fulmini WH57",
                    message="La batteria del sensore fulmini WH57 è quasi scarica.",
                    priority="normal"
                )

        # WH51 Sensori Suolo
        soil_batts = batteries.get("soil", {})
        for ch, val in soil_batts.items():
            if val in ("1", 1):
                last_time = self.last_battery_alert.get(f"soil_{ch}", 0.0)
                if (now - last_time) >= (24 * 3600):
                    self.last_battery_alert[f"soil_{ch}"] = now
                    self._save_state()
                    notifier.send_alert(
                        alert_type="battery_low",
                        title=f"🪫 Batteria Bassa: Sensore Suolo ({ch})",
                        message=f"La batteria del sensore di umidità suolo WH51 ({ch}) è scarica.",
                        priority="normal"
                    )

    def check_offline_watchdog(self):
        """
        Eseguito ciclicamente in background ogni minuto.
        Se la stazione non invia dati da oltre STATION_OFFLINE_TIMEOUT_MIN minuti,
        invia un allarme push di stazione offline.
        """
        now = time.time()
        status_info = get_station_status()
        
        if status_info["status"] == "offline":
            if not self.is_station_offline:
                self.is_station_offline = True
                mins = (status_info.get("seconds_ago") or 0) // 60
                logger.warning(f"[WATCHDOG] Stazione Meteo Offline da {mins} minuti!")
                self.last_offline_alert_time = now
                self._save_state()
                notifier.send_alert(
                    alert_type="offline",
                    title="⚠️ Stazione Meteo OFFLINE!",
                    message=f"Nessun dato ricevuto dalla stazione da oltre {mins} minuti. Verifica alimentazione, console o connessione Wi-Fi.",
                    priority="urgent",
                    extra_data={"offline_minutes": str(mins)}
                )
            elif (now - self.last_offline_alert_time) >= (3600 * 3): # ripeti ogni 3 ore se ancora offline
                self.last_offline_alert_time = now
                mins = (status_info.get("seconds_ago") or 0) // 60
                self._save_state()
                notifier.send_alert(
                    alert_type="offline",
                    title="⚠️ Promemoria: Stazione Meteo Ancora Offline",
                    message=f"La stazione meteo è ancora disconnessa (da {mins} minuti).",
                    priority="normal"
                )

    def check_rain_forecast(self):
        """
        Controlla periodicamente le previsioni Open-Meteo per rilevare pioggia imminente
        nelle prossime 1-2 ore (se non sta già piovendo).
        """
        if not settings.RAIN_FORECAST_ALERT_ENABLED:
            return

        now = time.time()
        if (now - self.last_rain_forecast_alert) < (settings.RAIN_FORECAST_COOLDOWN_MIN * 60):
            return

        # Se sta già piovendo, non inviare il preavviso
        if self.is_raining:
            return

        try:
            from backend.forecast_service import forecast_service
            forecast = forecast_service.fetch_open_meteo()
            if not forecast:
                return

            hourly = forecast.get("hourly_next_36h", [])
            if not hourly:
                return

            now_dt = settings.now_local().replace(tzinfo=None)

            # Cerca nelle prossime 2.5 ore
            for h in hourly:
                try:
                    h_dt = datetime.strptime(h["iso_time"], "%Y-%m-%dT%H:%M")
                    diff_hours = (h_dt - now_dt).total_seconds() / 3600.0
                    if 0 <= diff_hours <= 2.5:
                        prob = h.get("rain_prob_pct", 0)
                        mm = h.get("rain_mm", 0.0)

                        if prob >= settings.RAIN_FORECAST_PROB_THRESHOLD or (mm >= 0.5 and prob >= 40):
                            self.last_rain_forecast_alert = now
                            self._save_state()
                            hour_label = h.get("hour_label", f"{h_dt.hour:02d}:00")
                            cond_text = h.get("condition", "Pioggia")
                            notifier.send_alert(
                                alert_type="rain_forecast",
                                title="☔ Pioggia Prevista a Breve!",
                                message=f"I modelli meteo indicano {cond_text.lower()} in arrivo verso le {hour_label} (probabilità {prob}%, stima {mm} mm). Attenzione a finestre e bucato!",
                                priority="normal",
                                extra_data={"prob": str(prob), "rain_mm": str(mm), "time": hour_label}
                            )
                            logger.info(f"[RAIN-FORECAST] Notifica pioggia imminente inviata per le {hour_label} (prob: {prob}%, mm: {mm})")
                            break
                except Exception as ex:
                    logger.debug(f"Errore parsing ora previsione: {ex}")
        except Exception as e:
            logger.error(f"Errore controllo previsioni pioggia: {e}")

    def check_daily_digest(self):
        """
        Controlla se è l'ora di inviare il riepilogo del mattino 'Buongiorno Meteo'.
        """
        if not settings.DAILY_DIGEST_ENABLED:
            return

        now_dt = settings.now_local()
        today_str = now_dt.strftime("%Y-%m-%d")

        # Verifica se è l'orario configurato (es. 08:00) e non è già stato inviato oggi
        if getattr(self, "last_digest_date", None) != today_str:
            if now_dt.hour == settings.DAILY_DIGEST_HOUR and now_dt.minute >= settings.DAILY_DIGEST_MINUTE:
                self.last_digest_date = today_str
                self._save_state()
                self.send_daily_digest()

    def check_nightly_maintenance(self):
        """Esegue automaticamente ogni notte alle 03:30 la compattazione e l'ottimizzazione di SQLite."""
        now_dt = settings.now_local()
        today_str = now_dt.strftime("%Y-%m-%d")
        if getattr(self, "last_maintenance_date", None) != today_str:
            if now_dt.hour == 3 and now_dt.minute >= 30:
                self.last_maintenance_date = today_str
                self._save_state()
                try:
                    from backend.database import perform_database_maintenance
                    res = perform_database_maintenance(retention_days=60)
                    logger.info(f"[DB-MAINTENANCE] Manutenzione notturna eseguita: {res}")
                except Exception as e:
                    logger.error(f"[DB-MAINTENANCE] Errore durante manutenzione: {e}")

    def send_daily_digest(self) -> Dict[str, Any]:
        """
        Genera e invia il report del mattino 'Buongiorno Meteo'.
        """
        from backend.database import (
            get_latest_reading, get_today_extremes, get_yesterday_same_time,
            get_pressure_trend, get_tropical_nights_stats, get_soil_moisture_summary,
            check_and_update_records
        )
        from backend.analytics import calc_zambretti_forecast, abs_to_rel_pressure, evaluate_window_ventilation, evaluate_laundry_index, calc_sun_ephemeris

        latest = get_latest_reading() or {}
        today_ext = get_today_extremes()
        temp_c = latest.get("temp_c")
        yesterday_cmp = get_yesterday_same_time(temp_c)

        press = latest.get("pressure_rel_hpa") or abs_to_rel_pressure(latest.get("pressure_abs_hpa"), settings.ELEVATION, temp_c)
        press_trend = get_pressure_trend(press)
        forecast = calc_zambretti_forecast(press, press_trend.get("diff"), latest.get("wind_dir_deg"))

        sun = calc_sun_ephemeris(settings.LATITUDE, settings.LONGITUDE)
        laundry = evaluate_laundry_index(
            temp_c, latest.get("humidity"), latest.get("wind_speed_kmh"),
            latest.get("solar_radiation"), latest.get("rain_rate_mm_hr")
        )

        tropical_stats = get_tropical_nights_stats()
        soil_summary = get_soil_moisture_summary()

        # Verifica e aggiorna record Minima Più Alta (Notte Tropicale) se applicabile
        min_t_val = today_ext.get("temp_min")
        if min_t_val is not None and min_t_val >= settings.TROPICAL_NIGHT_TEMP_THRESHOLD_C:
            check_and_update_records({
                "temp_min_highest": min_t_val,
                "temp_min_highest_date": settings.now_local().strftime("%Y-%m-%d"),
                "timestamp": latest.get("timestamp")
            })

        # Costruisci messaggio
        min_txt = f"Minima: {min_t_val}°C" if min_t_val is not None else ""
        if today_ext.get("temp_min_time"):
            min_txt += f" (alle {today_ext['temp_min_time']})"

        cur_txt = f"Attualmente: {temp_c}°C" if temp_c is not None else ""
        if yesterday_cmp.get("diff_c") is not None:
            cur_txt += f" ({yesterday_cmp['text']})"

        # Riga Notte Tropicale (se la minima odierna è >= soglia o ieri notte)
        tropical_line = ""
        if min_t_val is not None and min_t_val >= settings.SUPER_TROPICAL_NIGHT_TEMP_THRESHOLD_C:
            tropical_line = f"🔥 Notte Rovente! Minima di {min_t_val}°C (N° {tropical_stats['total_super_tropical_nights']} dell'anno)"
        elif min_t_val is not None and min_t_val >= settings.TROPICAL_NIGHT_TEMP_THRESHOLD_C:
            streak_txt = f" • {tropical_stats['current_streak']}° giorno consecutivo" if tropical_stats.get('current_streak', 0) > 1 else ""
            tropical_line = f"🌴 Notte Tropicale: Minima non scesa sotto {min_t_val}°C (N° {tropical_stats['total_tropical_nights']} dell'anno{streak_txt})"

        # Riga Terreno (se presenti sensori WH51)
        soil_line = ""
        if soil_summary.get("has_sensors") and soil_summary.get("avg_moisture") is not None:
            soil_line = f"🌱 Terreno: Umidità {soil_summary['avg_moisture']}% ({soil_summary['status_text']})"

        lines = [
            f"🌅 {forecast['icon']} {forecast['text']}",
            f"🌡️ {cur_txt} • {min_txt}",
            tropical_line,
            f"☀️ Alba: {sun['sunrise']} • Tramonto: {sun['sunset']} ({sun['daylight_duration']} di luce)",
            f"{laundry['icon']} Panni: {laundry['title']} ({laundry['time_estimate']})",
            soil_line
        ]

        title = "☕ Buongiorno Meteo!"
        msg = "\n".join([line for line in lines if line])

        logger.info(f"[DIGEST] Invio notifica buongiorno: {title}\n{msg}")
        notifier.send_alert(
            alert_type="digest",
            title=title,
            message=msg,
            priority="normal"
        )
        return {"status": "sent", "title": title, "message": msg}

    # ----------------- ALLARMI & REPORT ENERGETICI ATON -----------------

    def evaluate_energy(self, energy_data: Dict[str, Any]):
        """Valuta le condizioni energetiche per invio allarmi istantanei."""
        now = time.time()
        
        # 1. Allarme Consumo Elettrico Elevato (Prevenzione distacco contatore)
        p_utenze = energy_data.get("p_utenze") or 0.0
        if p_utenze >= settings.ENERGY_HIGH_CONSUMPTION_W:
            if (now - self.last_high_consumption_alert) >= (settings.ENERGY_HIGH_CONSUMPTION_COOLDOWN_MIN * 60):
                self.last_high_consumption_alert = now
                self._save_state()
                kw = round(p_utenze / 1000.0, 2)
                notifier.send_alert(
                    alert_type="energy_high",
                    title="⚡ Consumo Elettrico Elevato!",
                    message=f"La casa sta assorbendo {kw} kW ({int(p_utenze)} W). Verifica i carichi per evitare distacchi.",
                    priority="urgent",
                    extra_data={"p_utenze": str(p_utenze)}
                )

        # 2. Allarme Batteria di Accumulo Scarica
        soc = energy_data.get("soc")
        if soc is not None:
            if soc <= settings.ENERGY_BATTERY_LOW_PCT:
                if (now - self.last_battery_low_alert) >= (settings.ENERGY_BATTERY_COOLDOWN_MIN * 60):
                    self.last_battery_low_alert = now
                    self._save_state()
                    notifier.send_alert(
                        alert_type="battery_low",
                        title="🪫 Batteria Aton Quasi Scarica!",
                        message=f"Il livello di carica della batteria è al {int(soc)}%. La casa preleverà dalla rete.",
                        priority="normal",
                        extra_data={"soc": str(soc)}
                    )

            # 3. Notifica Batteria Carica al 100%
            if soc >= settings.ENERGY_BATTERY_FULL_PCT:
                if not self._was_battery_full and (now - self.last_battery_full_alert) >= (settings.ENERGY_BATTERY_COOLDOWN_MIN * 60):
                    self.last_battery_full_alert = now
                    self._was_battery_full = True
                    self._save_state()
                    notifier.send_alert(
                        alert_type="battery_full",
                        title="🔋 Batteria Aton Completamente Carica!",
                        message=f"Accumulatore al {int(soc)}%. Tutta l'energia solare eccedente è pronta per l'autoconsumo!",
                        priority="normal",
                        extra_data={"soc": str(soc)}
                    )
            elif soc < 90:
                if self._was_battery_full:
                    self._was_battery_full = False
                    self._save_state()

    def check_evening_energy_digest(self):
        """Controlla se è l'ora di inviare il bilancio energetico serale."""
        if not settings.ENERGY_REPORT_ENABLED or not settings.ATON_ENABLED:
            return

        now_dt = settings.now_local()
        today_str = now_dt.strftime("%Y-%m-%d")

        if getattr(self, "last_evening_energy_date", None) != today_str:
            if now_dt.hour == settings.ENERGY_REPORT_HOUR and now_dt.minute >= 0:
                self.last_evening_energy_date = today_str
                self._save_state()
                self.send_evening_energy_digest()

    def send_evening_energy_digest(self) -> Dict[str, Any]:
        """Genera e invia la notifica con il bilancio energetico giornaliero."""
        from backend.database import get_today_energy_summary
        summary = get_today_energy_summary()

        solar_kwh = summary.get("solar_today_kwh", 0.0)
        self_consumed_kwh = summary.get("self_consumed_kwh", 0.0)
        autarky_pct = summary.get("autarky_pct", 0.0)
        self_cons_pct = summary.get("self_consumption_pct", 0.0)
        bought_kwh = summary.get("bought_today_kwh", 0.0)
        soc = summary.get("battery_soc", 0.0)

        lines = [
            f"☀️ Solare prodotto oggi: {solar_kwh} kWh",
            f"🏠 Autoconsumati: {self_consumed_kwh} kWh ({self_cons_pct}%)",
            f"🔋 Batteria attuale: {int(soc)}% SoC",
            f"🔌 Rete elettrica prelevata: {bought_kwh} kWh",
            f"🏆 Indice Autosufficienza: {autarky_pct}%"
        ]

        title = "📊 Bilancio Energetico di Oggi"
        msg = "\n".join(lines)

        logger.info(f"[ENERGY DIGEST] Invio bilancio energetico serale: {title}\n{msg}")
        notifier.send_alert(
            alert_type="energy_digest",
            title=title,
            message=msg,
            priority="normal"
        )
        return {"status": "sent", "title": title, "message": msg}

    def evaluate_smartthings_automations(
        self,
        smartthings_data: Dict[str, Any],
        weather_data: Dict[str, Any],
        energy_data: Dict[str, Any]
    ):
        """
        Esegue automazioni intelligenti incrociando:
        - Presenza S26 Ultra di Vincenzo
        - Elettrodomestici (Lavatrice & Lavastoviglie)
        - Dati meteo Ecowitt (Indice bucato / temperatura)
        - Fotovoltaico & Batteria Aton Storage
        """
        if not smartthings_data or not smartthings_data.get("enabled"):
            return

        now = time.time()

        # 1. Automazione Rilevamento Presenza S26 Ultra (Transizioni A Casa / Fuori Casa)
        presence = smartthings_data.get("presence")
        if presence:
            is_present = presence.get("is_present")
            dev_name = presence.get("device_name", "S26 Ultra")

            if hasattr(self, "_last_presence_is_present") and self._last_presence_is_present is not None:
                # Transizione Fuori Casa -> A Casa (Rientro)
                if not self._last_presence_is_present and is_present:
                    logger.info(f"[SMART-AUTOMATION] Rientro a casa rilevato per {dev_name}")
                    p_solare = float(energy_data.get("p_solare") or 0.0)
                    soc = float(energy_data.get("soc") or 0.0)
                    temp_c = float(weather_data.get("temp_c") or 25.0)

                    climate_note = ""
                    if temp_c >= 28.0 and (p_solare >= 600 or soc >= 50):
                        climate_note = f"\n☀️ Clima estivo ({temp_c}°C): energia solare disponibile ({int(p_solare)} W, Batteria {int(soc)}%) per il raffrescamento a costo zero."
                    
                    notifier.send_alert(
                        alert_type="presence_home",
                        title=f"🏠 Bentornato a Casa, Vincenzo!",
                        message=f"Rilevata presenza di {dev_name} a casa.{climate_note}",
                        priority="normal",
                        extra_data={"device": dev_name, "presence": "present"}
                    )

                # Transizione A Casa -> Fuori Casa (Uscita)
                elif self._last_presence_is_present and not is_present:
                    logger.info(f"[SMART-AUTOMATION] Uscita da casa rilevata per {dev_name}")
                    notifier.send_alert(
                        alert_type="presence_away",
                        title=f"🚗 Uscita di Casa Rilevata",
                        message=f"{dev_name} è fuori casa. Monitoraggio consumi ed energia attivo.",
                        priority="low",
                        extra_data={"device": dev_name, "presence": "away"}
                    )

            if self._last_presence_is_present != is_present:
                self._last_presence_is_present = is_present
                self._save_state()

        # 2. Notifica Lavatrice Terminata + Asciugatura Bucato al Sole
        washer = smartthings_data.get("washer")
        if washer:
            current_job = washer.get("job_state")
            was_running = getattr(self, "_last_washer_was_running", False)
            
            if was_running and current_job == "finish":
                logger.info("[SMART-AUTOMATION] Lavatrice ha completato il ciclo di lavaggio!")
                drying_synergy = smartthings_data.get("laundry_drying_synergy")
                if drying_synergy and drying_synergy.get("optimal"):
                    msg = "🫧 Ciclo di lavaggio completato! Il meteo all'esterno è ideale per stendere il bucato al sole ☀️"
                else:
                    msg = "🫧 Ciclo di lavaggio completato! Ricordati di ritirare o stendere il bucato."

                notifier.send_alert(
                    alert_type="washer_finish",
                    title="🫧 Lavatrice: Ciclo Terminato!",
                    message=msg,
                    priority="normal",
                    extra_data={"device": "Lavatrice Samsung AI"}
                )

            is_running_now = washer.get("is_running", False)
            if self._last_washer_was_running != is_running_now:
                self._last_washer_was_running = is_running_now
                self._save_state()

        # 3. Suggerimento Avvio Elettrodomestici con Surplus Solare Aton (quando Vincenzo è a casa)
        solar_syn = smartthings_data.get("solar_synergy", {})
        if solar_syn.get("solar_optimal") and (presence and presence.get("is_present")):
            last_solar_alert = getattr(self, "_last_solar_appliance_alert", 0.0)
            # Notifica al massimo una volta ogni 3 ore (180 min) per non spammare
            if (now - last_solar_alert) >= (180 * 60):
                self._last_solar_appliance_alert = now
                self._save_state()
                p_sol = int(solar_syn.get("p_solare", 0))
                soc_val = int(solar_syn.get("soc", 0))
                notifier.send_alert(
                    alert_type="solar_synergy_appliances",
                    title="☀️ Momento Ideale: Elettrodomestici a Costo Zero!",
                    message=f"Produzione solare a {p_sol} W e batteria al {soc_val}%: momento ideale per avviare Lavatrice o Lavastoviglie!",
                    priority="normal",
                    extra_data={"p_solare": str(p_sol), "soc": str(soc_val)}
                )

    async def evaluate_climate_automations(
        self,
        climate_devices: List[Dict[str, Any]],
        weather_data: Dict[str, Any],
        energy_data: Dict[str, Any],
        presence_data: Optional[Dict[str, Any]]
    ):
        """
        Motore di Intelligenza Clima: valuta regole autonome e notifiche per LG ThinQ.
        Configurazione gestita dinamicamente da SQLite (climate_automations_config).
        """
        if not settings.LG_THINQ_ENABLED or not climate_devices:
            return

        from backend.database import get_climate_automations_config
        from backend.thinq_service import thinq_service

        cfg = get_climate_automations_config()
        if not cfg.get("master_enabled", True):
            return

        now = time.time()
        now_dt = settings.now_local()
        current_hour = now_dt.hour
        temp_out = weather_data.get("temp_c")
        rain_rate = weather_data.get("rain_rate_mm_hr", 0.0) or 0.0
        p_solare = float(energy_data.get("p_solare") or 0.0)
        soc = float(energy_data.get("soc") or 0.0)
        is_present = presence_data.get("is_present") if presence_data else None

        # Separa condizionatori (gestione climatica) dal frigorifero
        all_ac_units = [d for d in climate_devices if d.get("device_type") == "DEVICE_AIR_CONDITIONER"]
        active_climates = [d for d in all_ac_units if d.get("is_on")]

        # =========================================================================
        # 1. SCENARIO USCITA DI CASA / PARTENZA (Presenza Vincenzo S26 Ultra)
        # =========================================================================
        away_action = cfg.get("away_action", "notify")  # 'off', 'notify', 'disabled'
        away_delay_min = int(cfg.get("away_delay_min", 10))

        if away_action != "disabled" and is_present is False and active_climates:
            if self._presence_away_timestamp is None:
                self._presence_away_timestamp = now
                self._save_state()

            away_elapsed_min = (now - self._presence_away_timestamp) / 60.0
            
            if (now - self.last_climate_away_alert) >= 3600:  # Cooldown 1h per avviso uscita
                if away_action == "off" and away_elapsed_min >= away_delay_min:
                    # Spegnimento automatico dei climatizzatori rimasti accesi
                    turned_off_names = []
                    for dev in active_climates:
                        dev_id = dev.get("device_id") or dev.get("deviceId")
                        alias = dev.get("alias", "Climatizzatore")
                        await thinq_service.control_device(dev_id, {"power": False})
                        turned_off_names.append(alias)
                    
                    self.last_climate_away_alert = now
                    self._save_state()
                    names_str = ", ".join(turned_off_names)
                    notifier.send_alert(
                        alert_type="climate_auto_off",
                        title="🤖 Clima Spento in Autonomia (Uscita Casa)",
                        message=f"Sei fuori casa da oltre {int(away_elapsed_min)} min: {names_str} spento automaticamente per evitare sprechi.",
                        priority="high",
                        extra_data={"action": "auto_off", "devices": names_str}
                    )
                    logger.info(f"[CLIMATE-AUTO] Spegnimento autonomo eseguito per uscita casa: {names_str}")

                elif away_action == "notify" and away_elapsed_min >= 2:
                    # Solo notifica (perché ci potrebbero essere altre persone in casa)
                    names_list = []
                    for dev in active_climates:
                        alias = dev.get("alias", "Clima")
                        curr_t = dev.get("current_temp")
                        t_str = f"{curr_t}°C" if curr_t else ""
                        names_list.append(f"{alias} ({t_str})" if t_str else alias)
                    
                    self.last_climate_away_alert = now
                    self._save_state()
                    names_str = ", ".join(names_list)
                    notifier.send_alert(
                        alert_type="climate_away_reminder",
                        title="🚗 Uscita di Casa: Climatizzatore Acceso",
                        message=f"Sei uscito ma {names_str} è rimasto in funzione. Se in casa non c'è nessuno, puoi spegnerlo dal pannello.",
                        priority="normal",
                        extra_data={"action": "notify_away", "devices": names_str}
                    )
                    logger.info(f"[CLIMATE-NOTIFY] Inviata notifica clima acceso per uscita Vincenzo: {names_str}")

        elif is_present is True:
            self._presence_away_timestamp = None

        # =========================================================================
        # 2. SCENARIO DIMENTICANZA / MAX RUNTIME GUARD
        # =========================================================================
        runtime_action = cfg.get("max_runtime_action", "notify")  # 'off', 'notify', 'disabled'
        max_runtime_hours = float(cfg.get("max_runtime_hours", 5))

        if runtime_action != "disabled":
            for dev in active_climates:
                dev_id = dev.get("device_id") or dev.get("deviceId")
                alias = dev.get("alias", "Climatizzatore")
                p_since = dev.get("power_on_since")
                
                if p_since:
                    hours_on = (now - p_since) / 3600.0
                    if hours_on >= max_runtime_hours:
                        last_alert = self.last_climate_runtime_alert.get(dev_id, 0.0)
                        if (now - last_alert) >= (max_runtime_hours * 1800):  # Cooldown
                            self.last_climate_runtime_alert[dev_id] = now
                            self._save_state()
                            h_rounded = round(hours_on, 1)
                            curr_t = dev.get("current_temp")
                            target_t = dev.get("target_temp")
                            t_info = f" (Stanza: {curr_t}°C, Setpoint: {target_t}°C)" if curr_t else ""

                            if runtime_action == "off":
                                await thinq_service.control_device(dev_id, {"power": False})
                                notifier.send_alert(
                                    alert_type="climate_auto_off",
                                    title=f"🤖 Spegnimento Autonomo: {alias}",
                                    message=f"Il climatizzatore '{alias}' era acceso ininterrottamente da {h_rounded} ore{t_info}. Spento per prevenire dimenticanze.",
                                    priority="high",
                                    extra_data={"device_id": dev_id, "runtime_hours": str(h_rounded)}
                                )
                                logger.info(f"[CLIMATE-AUTO] Spegnimento max runtime per {alias} ({h_rounded}h)")
                            elif runtime_action == "notify":
                                notifier.send_alert(
                                    alert_type="climate_runtime_warning",
                                    title=f"⏱️ Clima Acceso da {h_rounded} Ore: {alias}",
                                    message=f"Il climatizzatore '{alias}' è in funzione da oltre {h_rounded} ore{t_info}. Ricordati di spegnerlo se la stanza è a temperatura.",
                                    priority="normal",
                                    extra_data={"device_id": dev_id, "runtime_hours": str(h_rounded)}
                                )

        # =========================================================================
        # 3. SCENARIO FREE COOLING NOTTURNO (Fuori fresco, Dentro caldo/clima in cool)
        # =========================================================================
        night_action = cfg.get("night_cooling_action", "notify")  # 'off', 'notify', 'disabled'
        night_start = int(cfg.get("night_start_hour", 23))
        night_end = int(cfg.get("night_end_hour", 7))
        night_diff = float(cfg.get("night_temp_diff", 1.5))

        is_night_window = (current_hour >= night_start or current_hour < night_end)

        if night_action != "disabled" and is_night_window and temp_out is not None and rain_rate == 0.0 and not self.is_raining:
            for dev in active_climates:
                dev_id = dev.get("device_id") or dev.get("deviceId")
                alias = dev.get("alias", "Climatizzatore")
                mode = dev.get("mode", "COOL")
                curr_in = dev.get("current_temp") or weather_data.get("temp_in_c")

                # Se il clima è in raffrescamento e fuori fa fresco (e non è notte tropicale >= 20°C)
                if mode in ("COOL", "AUTO") and curr_in is not None and temp_out < 24.0:
                    if temp_out <= (curr_in - night_diff):
                        last_alert = self.last_climate_night_alert.get(dev_id, 0.0)
                        if (now - last_alert) >= 14400:  # Cooldown 4h
                            self.last_climate_night_alert[dev_id] = now
                            self._save_state()
                            diff_t = round(curr_in - temp_out, 1)

                            if night_action == "off":
                                await thinq_service.control_device(dev_id, {"power": False})
                                notifier.send_alert(
                                    alert_type="climate_night_cooling",
                                    title=f"🌙 Free Cooling Notturno: {alias} Spento",
                                    message=f"All'esterno la temperatura è scesa a {temp_out}°C ({diff_t}°C più fresco della stanza a {curr_in}°C). Clima spento in autonomia: apri le finestre per rinfrescare a costo zero!",
                                    priority="normal",
                                    extra_data={"temp_out": str(temp_out), "temp_in": str(curr_in)}
                                )
                                logger.info(f"[CLIMATE-AUTO] Free cooling spegnimento autonomo {alias}")
                            elif night_action == "notify":
                                notifier.send_alert(
                                    alert_type="climate_night_cooling",
                                    title=f"🌙 Rinfresca all'Esterno: {alias}",
                                    message=f"All'esterno la temperatura è scesa a {temp_out}°C ({diff_t}°C più fresco della stanza a {curr_in}°C). Puoi spegnere il clima '{alias}' e aprire le finestre per dormire con aria fresca naturale.",
                                    priority="normal",
                                    extra_data={"temp_out": str(temp_out), "temp_in": str(curr_in)}
                                )

        # =========================================================================
        # 4. SCENARIO PRE-COOLING SOLARE ATON (Surplus Fotovoltaico Gratuito)
        # =========================================================================
        solar_action = cfg.get("solar_preconditioning_action", "notify")  # 'on', 'notify', 'disabled'
        solar_surplus_w = float(cfg.get("solar_surplus_w", 1800))
        solar_min_soc = float(cfg.get("solar_min_soc", 80))
        solar_target_t = float(cfg.get("solar_target_temp", 25.0))

        if solar_action != "disabled" and p_solare >= solar_surplus_w and soc >= solar_min_soc:
            # Condizioni estive diurne (ore 10:00 - 18:00)
            if 10 <= current_hour <= 18 and (is_present is True or is_present is None):
                for dev in all_ac_units:
                    dev_id = dev.get("device_id") or dev.get("deviceId")
                    alias = dev.get("alias", "Climatizzatore")
                    is_on = dev.get("is_on", False)
                    curr_in = dev.get("current_temp") or 26.0

                    if not is_on and curr_in >= 26.0:
                        last_alert = self.last_climate_solar_alert.get(dev_id, 0.0)
                        if (now - last_alert) >= 10800:  # Cooldown 3h
                            self.last_climate_solar_alert[dev_id] = now
                            self._save_state()

                            if solar_action == "on":
                                await thinq_service.control_device(dev_id, {
                                    "power": True,
                                    "mode": "COOL",
                                    "target_temp": solar_target_t
                                })
                                notifier.send_alert(
                                    alert_type="climate_solar_auto_on",
                                    title=f"☀️ Pre-Raffrescamento Solare: {alias}",
                                    message=f"Forte surplus fotovoltaico ({int(p_solare)} W, Batteria al {int(soc)}%): {alias} avviato in raffrescamento a {solar_target_t}°C a costo zero prima del picco pomeridiano.",
                                    priority="normal",
                                    extra_data={"p_solare": str(p_solare), "soc": str(soc)}
                                )
                                logger.info(f"[CLIMATE-AUTO] Pre-cooling solare auto ON per {alias}")
                            elif solar_action == "notify":
                                notifier.send_alert(
                                    alert_type="climate_solar_opportunity",
                                    title=f"☀️ Climatizzazione a Costo Zero: {alias}",
                                    message=f"Produzione solare abbondante ({int(p_solare)} W) e accumulatore al {int(soc)}%: momento ideale per accendere {alias} gratis ed evitare il surriscaldamento.",
                                    priority="normal",
                                    extra_data={"p_solare": str(p_solare), "soc": str(soc)}
                                )

        # =========================================================================
        # 5. SCENARIO PROTEZIONE BATTERIA SCARICA / PRELIEVO RETE
        # =========================================================================
        battery_action = cfg.get("battery_guard_action", "notify")  # 'off', 'notify', 'disabled'
        battery_min_soc = float(cfg.get("battery_min_soc", 20))

        if battery_action != "disabled" and p_solare < 100 and soc <= battery_min_soc and active_climates:
            for dev in active_climates:
                dev_id = dev.get("device_id") or dev.get("deviceId")
                alias = dev.get("alias", "Climatizzatore")
                last_alert = self.last_climate_battery_alert.get(dev_id, 0.0)
                
                if (now - last_alert) >= 7200:  # Cooldown 2h
                    self.last_climate_battery_alert[dev_id] = now
                    self._save_state()

                    if battery_action == "off":
                        await thinq_service.control_device(dev_id, {"power": False})
                        notifier.send_alert(
                            alert_type="climate_battery_guard",
                            title=f"🔋 Protezione Batteria Aton: {alias} Spento",
                            message=f"Batteria di accumulo al {int(soc)}% e produzione solare assente: {alias} spento per evitare prelievi costosi dalla rete.",
                            priority="high",
                            extra_data={"soc": str(soc)}
                        )
                        logger.info(f"[CLIMATE-AUTO] Battery guard auto OFF per {alias}")
                    elif battery_action == "notify":
                        notifier.send_alert(
                            alert_type="climate_battery_guard",
                            title=f"🔋 Batteria Bassa con Clima Attivo: {alias}",
                            message=f"Batteria Aton scesa al {int(soc)}% e fotovoltaico assente. {alias} sta prelevando energia a pagamento dalla rete elettrica.",
                            priority="normal",
                            extra_data={"soc": str(soc)}
                        )

        # =========================================================================
        # 6. ALLARMI & AUTOMAZIONI FRIGORIFERO SMART LG THINQ
        # =========================================================================
        fridges = [d for d in climate_devices if d.get("device_type") == "DEVICE_REFRIGERATOR"]
        for fr in fridges:
            fr_id = fr.get("device_id") or fr.get("deviceId")
            fr_alias = fr.get("alias", "Frigorifero")
            door_open = fr.get("door_open", False)
            door_open_since = fr.get("door_open_since")
            express_mode = fr.get("express_mode", False)

            # A. Allarme Porta Frigo Rimasta Aperta (> 2 min)
            if door_open and door_open_since:
                open_duration_sec = now - door_open_since
                if open_duration_sec >= 120 and (now - self.last_fridge_door_alert) >= 600:  # 2 min aperto, cooldown 10 min
                    self.last_fridge_door_alert = now
                    self._save_state()
                    notifier.send_alert(
                        alert_type="fridge_door_open",
                        title=f"🚪 Porta {fr_alias} Rimasta Aperta!",
                        message=f"⚠️ La porta del {fr_alias} è aperta da oltre 2 minuti ({int(open_duration_sec // 60)} min). Chiudila per non deteriorare gli alimenti.",
                        priority="high",
                        extra_data={"device_id": fr_id, "duration_sec": str(int(open_duration_sec))}
                    )
                    logger.warning(f"[FRIDGE-GUARD] Porta {fr_alias} aperta da {int(open_duration_sec)}s -> allarme inviato.")

            # B. Allarme Uscita di Casa con Porta Frigo Aperta
            if is_present is False and door_open:
                if (now - self.last_fridge_away_alert) >= 900:  # Cooldown 15 min
                    self.last_fridge_away_alert = now
                    self._save_state()
                    notifier.send_alert(
                        alert_type="fridge_door_away",
                        title=f"🚨 ALLARME: {fr_alias} Aperto all'Uscita!",
                        message=f"🚪 [URGENTE] Sei uscito di casa ma la porta del {fr_alias} risulta ancora APERTA! Rientra o avvisa chi è in casa per richiuderla.",
                        priority="urgent",
                        extra_data={"device_id": fr_id}
                    )
                    logger.warning(f"[FRIDGE-GUARD] Vincenzo away ma {fr_alias} ha la porta APERTA! Allarme urgente inviato.")

            # C. Sinergia Solare Aton: Express Cool a Costo Zero
            if p_solare >= 2200 and soc >= 95 and not express_mode and (now - self.last_fridge_solar_alert) >= 14400:  # Cooldown 4h
                self.last_fridge_solar_alert = now
                self._save_state()
                notifier.send_alert(
                    alert_type="fridge_solar_opportunity",
                    title="☀️ Frigorifero & Surplus Solare",
                    message=f"Surplus fotovoltaico a {int(p_solare)} W e batteria al {int(soc)}%: puoi attivare Express Cool sul {fr_alias} per accumulare freddo gratis!",
                    priority="normal",
                    extra_data={"p_solare": str(int(p_solare)), "soc": str(int(soc))}
                )

engine = AlertEngine()



