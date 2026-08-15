import time
import logging
from datetime import datetime
from typing import Dict, Any, List
from backend.config import settings
from backend.notifier import notifier
from backend.database import check_and_update_records, get_pressure_trend, get_temp_1h_change, get_station_status


logger = logging.getLogger("ecowitt_alert_engine")

class AlertEngine:
    def __init__(self):
        self.last_lightning_epoch = None
        self.last_lightning_count = 0
        self.last_lightning_alert = 0.0
        self.last_soil_alert = {}
        self.last_freeze_alert = 0.0
        self.last_heat_alert = 0.0
        self.last_rain_alert = 0.0
        self.last_record_alert = 0.0
        
        # Anomaly cooldowns
        self.last_storm_alert = 0.0
        self.last_wind_spike_alert = 0.0
        self.last_rain_burst_alert = 0.0
        self.last_uv_alert = 0.0
        self.last_temp_plunge_alert = 0.0
        
        # Offline Watchdog state
        self.is_station_offline = False
        self.last_offline_alert_time = 0.0
        self.last_battery_alert = {}

    def evaluate(self, current_data: Dict[str, Any]):
        now = time.time()
        
        # Se riceve dati, reimposta stato offline se era offline
        if self.is_station_offline:
            self.is_station_offline = False
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
                    old_str = f" (precedente: {rec['old_value']} {rec['unit']})" if rec['old_value'] is not None else ""
                    msg = f"🏆 Nuovo record assoluto per '{rec['title']}': {rec['new_value']} {rec['unit']}{old_str}!"
                    logger.info(msg)
                    if (now - self.last_record_alert) >= (settings.RECORD_BROKEN_COOLDOWN_MIN * 60):
                        self.last_record_alert = now
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

        # 4. Controllo Batterie Sensori
        self._check_batteries(current_data, now)

    def _check_anomalies(self, data: Dict[str, Any], now: float):
        # A. Crollo Barometrico Rapido (Burrasca / Tempesta imminente)
        press = data.get("pressure_rel_hpa")
        if press is not None:
            trend_info = get_pressure_trend(press)
            if trend_info.get("is_storm_alert"):
                if (now - self.last_storm_alert) >= (settings.ANOMALY_ALERT_COOLDOWN_MIN * 60):
                    self.last_storm_alert = now
                    notifier.send_alert(
                        alert_type="storm",
                        title="⚠️ Allerta Burrasca: Crollo Pressione!",
                        message=f"La pressione barometrica è crollata a {press} hPa ({trend_info['diff']} hPa nelle ultime 3h). Forte peggioramento o tempesta in arrivo.",
                        priority="urgent",
                        extra_data={"pressure_drop": str(trend_info['diff'])}
                    )

        # B. Raffica Anomala Improvvisa (Wind Spike)
        gust = data.get("wind_gust_kmh")
        speed = data.get("wind_speed_kmh") or 0.0
        if gust is not None and gust >= settings.GUST_SPIKE_THRESHOLD_KMH:
            if (now - self.last_wind_spike_alert) >= (settings.ANOMALY_ALERT_COOLDOWN_MIN * 60):
                self.last_wind_spike_alert = now
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
            return

        is_new_strike = False
        if strike_epoch and strike_epoch != self.last_lightning_epoch:
            is_new_strike = True
            self.last_lightning_epoch = strike_epoch
        elif count > self.last_lightning_count:
            is_new_strike = True
            self.last_lightning_count = count

        if is_new_strike and dist_km is not None and dist_km <= settings.LIGHTNING_MAX_DISTANCE_KM:
            if (now - self.last_lightning_alert) >= (settings.LIGHTNING_COOLDOWN_MIN * 60):
                self.last_lightning_alert = now
                notifier.send_alert(
                    alert_type="lightning",
                    title="⚡ Temporale in arrivo!",
                    message=f"Fulmine rilevato a {dist_km} km dalla tua stazione meteo!",
                    priority="high",
                    extra_data={"distance_km": str(dist_km)}
                )

    def _check_soil_moisture(self, data: Dict[str, Any], now: float):
        soil = data.get("soil_moisture", {})
        for channel, value in soil.items():
            if value is not None and value <= settings.SOIL_MOISTURE_LOW_THRESHOLD:
                last_time = self.last_soil_alert.get(channel, 0.0)
                if (now - last_time) >= (settings.SOIL_MOISTURE_COOLDOWN_MIN * 60):
                    self.last_soil_alert[channel] = now
                    notifier.send_alert(
                        alert_type="soil_dry",
                        title="🌱 Annaffia le piante",
                        message=f"L'umidità del terreno ({channel}) è scesa al {value}% (sotto la soglia minima del {settings.SOIL_MOISTURE_LOW_THRESHOLD}%).",
                        priority="normal",
                        extra_data={"channel": channel, "moisture": str(value)}
                    )

    def _check_temperatures(self, data: Dict[str, Any], now: float):
        temp = data.get("temp_c")
        if temp is None:
            return

        if temp <= settings.TEMP_FREEZE_THRESHOLD_C:
            if (now - self.last_freeze_alert) >= (settings.TEMP_ALERT_COOLDOWN_MIN * 60):
                self.last_freeze_alert = now
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
                notifier.send_alert(
                    alert_type="heatwave",
                    title="🔥 Caldo Estremo",
                    message=f"Temperatura salita a {temp}°C! Proteggersi dal caldo.",
                    priority="normal",
                    extra_data={"temp_c": str(temp)}
                )

    def _check_rain(self, data: Dict[str, Any], now: float):
        rain_rate = data.get("rain_rate_mm_hr")
        if rain_rate is not None and rain_rate >= settings.RAIN_RATE_ALERT_MM_HR and rain_rate < settings.RAIN_BURST_THRESHOLD_MM_HR:
            if (now - self.last_rain_alert) >= (settings.RAIN_ALERT_COOLDOWN_MIN * 60):
                self.last_rain_alert = now
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
                notifier.send_alert(
                    alert_type="offline",
                    title="⚠️ Promemoria: Stazione Meteo Ancora Offline",
                    message=f"La stazione meteo è ancora disconnessa (da {mins} minuti).",
                    priority="normal"
                )

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
                self.send_daily_digest()

    def send_daily_digest(self) -> Dict[str, Any]:
        """
        Genera e invia il report del mattino 'Buongiorno Meteo'.
        """
        from backend.database import get_latest_reading, get_today_extremes, get_yesterday_same_time, get_pressure_trend
        from backend.analytics import calc_zambretti_forecast, evaluate_window_ventilation, evaluate_laundry_index, calc_sun_ephemeris

        latest = get_latest_reading() or {}
        today_ext = get_today_extremes()
        temp_c = latest.get("temp_c")
        yesterday_cmp = get_yesterday_same_time(temp_c)

        press = latest.get("pressure_rel_hpa")
        press_trend = get_pressure_trend(press)
        forecast = calc_zambretti_forecast(press, press_trend.get("diff"), latest.get("wind_dir_deg"))

        sun = calc_sun_ephemeris(settings.LATITUDE, settings.LONGITUDE)
        laundry = evaluate_laundry_index(
            temp_c, latest.get("humidity"), latest.get("wind_speed_kmh"),
            latest.get("solar_radiation"), latest.get("rain_rate_mm_hr")
        )

        # Costruisci messaggio
        min_txt = f"Minima: {today_ext['temp_min']}°C" if today_ext.get("temp_min") is not None else ""
        if today_ext.get("temp_min_time"):
            min_txt += f" (alle {today_ext['temp_min_time']})"

        cur_txt = f"Attualmente: {temp_c}°C" if temp_c is not None else ""
        if yesterday_cmp.get("diff_c") is not None:
            cur_txt += f" ({yesterday_cmp['text']})"

        lines = [
            f"🌅 {forecast['icon']} {forecast['text']}",
            f"🌡️ {cur_txt} • {min_txt}",
            f"☀️ Alba: {sun['sunrise']} • Tramonto: {sun['sunset']} ({sun['daylight_duration']} di luce)",
            f"{laundry['icon']} Panni: {laundry['title']} ({laundry['time_estimate']})"
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

engine = AlertEngine()

