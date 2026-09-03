import os
import json
import time
import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
import requests

from backend.config import settings

logger = logging.getLogger("weather_hub.forecast")

WMO_CODE_MAP = {
    0: {"text": "Sereno", "icon": "☀️", "desc": "Cielo completamente sgombro da nubi."},
    1: {"text": "Prevalentemente sereno", "icon": "🌤️", "desc": "Poche nubi sparse, ampi spazi di sole."},
    2: {"text": "Parzialmente nuvoloso", "icon": "⛅", "desc": "Alternanza di sole e nuvole."},
    3: {"text": "Nuvoloso / Coperto", "icon": "☁️", "desc": "Cielo coperto con nubi compatte."},
    45: {"text": "Nebbia", "icon": "🌫️", "desc": "Forte riduzione della visibilità per nebbia."},
    48: {"text": "Nebbia con brina", "icon": "🌫️", "desc": "Nebbia densa con deposito di galaverna/brina."},
    51: {"text": "Pioviggine leggera", "icon": "🌦️", "desc": "Deboli gocce intermittenti."},
    53: {"text": "Pioviggine moderata", "icon": "🌦️", "desc": "Pioviggine continua e diffusa."},
    55: {"text": "Pioviggine intensa", "icon": "🌧️", "desc": "Fitta pioviggine con ridotta visibilità."},
    56: {"text": "Pioviggine gelata", "icon": "🌨️", "desc": "Pioviggine con formazione di ghiaccio."},
    57: {"text": "Pioviggine gelata intensa", "icon": "🌨️", "desc": "Gelo e pioviggine insidiosa."},
    61: {"text": "Pioggia debole", "icon": "🌧️", "desc": "Precipitazioni lievi e continue."},
    63: {"text": "Pioggia moderata", "icon": "🌧️", "desc": "Pioggia costante e ben organizzata."},
    65: {"text": "Pioggia forte", "icon": "🌧️", "desc": "Forte maltempo con accumuli consistenti."},
    66: {"text": "Pioggia gelata", "icon": "🌨️", "desc": "Pioggia che gela al suolo (gelicidio)."},
    67: {"text": "Forte pioggia gelata", "icon": "🌨️", "desc": "Pericolosa pioggia congelantesi."},
    71: {"text": "Neve debole", "icon": "❄️", "desc": "Deboli fiocchi di neve."},
    73: {"text": "Neve moderata", "icon": "❄️", "desc": "Nevicata costante con accumulo."},
    75: {"text": "Forte nevicata", "icon": "❄️", "desc": "Nevicata intensa e abbondante."},
    77: {"text": "Granuli di neve", "icon": "❄️", "desc": "Neve granulare intermittente."},
    80: {"text": "Rovesci deboli", "icon": "🌦️", "desc": "Brevi scrosci di pioggia isolati."},
    81: {"text": "Rovesci moderati", "icon": "🌧️", "desc": "Rovesci di pioggia a tratti intensi."},
    82: {"text": "Nubifragio / Rovesci violenti", "icon": "⛈️", "desc": "Forti rovesci temporaleschi concentrati."},
    85: {"text": "Rovesci di neve lievi", "icon": "🌨️", "desc": "Scrosci di neve improvvisi ma deboli."},
    86: {"text": "Rovesci di neve forti", "icon": "🌨️", "desc": "Bora o rovesci nevosi consistenti."},
    95: {"text": "Temporale", "icon": "⛈️", "desc": "Attività elettrica con pioggia e vento."},
    96: {"text": "Temporale con grandine", "icon": "⛈️", "desc": "Temporale forte accompagnato da grandinate."},
    99: {"text": "Forte temporale con grandine", "icon": "⛈️", "desc": "Supercella o violento temporale con grandine grossa."}
}

ITALIAN_DAYS = {
    0: "Lunedì",
    1: "Martedì",
    2: "Mercoledì",
    3: "Giovedì",
    4: "Venerdì",
    5: "Sabato",
    6: "Domenica"
}

ITALIAN_MONTHS = {
    1: "Gen", 2: "Feb", 3: "Mar", 4: "Apr", 5: "Mag", 6: "Giu",
    7: "Lug", 8: "Ago", 9: "Set", 10: "Ott", 11: "Nov", 12: "Dic"
}

EAQI_INFO = {
    1: {"label": "Molto Buona", "badge_class": "badge-success", "color": "#10b981", "icon": "🟢", "desc": "Aria pulita e ideale per ventilare ambienti e attività all'aperto."},
    2: {"label": "Buona", "badge_class": "badge-success", "color": "#22c55e", "icon": "🟢", "desc": "Qualità dell'aria buona. Nessun rischio per la popolazione."},
    3: {"label": "Moderata", "badge_class": "badge-warning", "color": "#f59e0b", "icon": "🟡", "desc": "Accettabile, ma soggetti ipersensibili potrebbero avvertire lievi fastidi."},
    4: {"label": "Scadente", "badge_class": "badge-danger", "color": "#f97316", "icon": "🟠", "desc": "Qualità dell'aria scadente. Si consiglia di limitare l'apertura prolungata delle finestre."},
    5: {"label": "Molto Scadente", "badge_class": "badge-danger", "color": "#ef4444", "icon": "🔴", "desc": "Inquinamento elevato. Finestre chiuse e uso purificatori consigliato."}
}


class ForecastService:
    def __init__(self, cache_ttl_seconds: int = 3600):
        self.cache_ttl = cache_ttl_seconds
        self._cached_data: Optional[Dict[str, Any]] = None
        self._last_fetch_time: float = 0.0
        self._cache_file = os.path.join(settings.DATA_DIR, "forecast_cache.json")

        self._cached_aqi: Optional[Dict[str, Any]] = None
        self._last_aqi_fetch: float = 0.0
        self._aqi_cache_file = os.path.join(settings.DATA_DIR, "air_quality_cache.json")

        self._load_disk_cache()

    def _load_disk_cache(self):
        """Carica l'ultima previsione e qualità aria salvate su disco se disponibili."""
        if os.path.exists(self._cache_file):
            try:
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._cached_data = data.get("data")
                    self._last_fetch_time = data.get("fetched_at", 0.0)
                    logger.info("Caricata cache previsioni meteo da disco")
            except Exception as e:
                logger.warning(f"Impossibile leggere forecast cache da disco: {e}")

        if os.path.exists(self._aqi_cache_file):
            try:
                with open(self._aqi_cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._cached_aqi = data.get("data")
                    self._last_aqi_fetch = data.get("fetched_at", 0.0)
                    logger.info("Caricata cache qualità dell'aria da disco")
            except Exception as e:
                logger.warning(f"Impossibile leggere AQI cache da disco: {e}")

    def _save_disk_cache(self):
        """Salva la cache in formato JSON su disco per persistenza ai riavvii."""
        try:
            os.makedirs(settings.DATA_DIR, exist_ok=True)
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump({
                    "fetched_at": self._last_fetch_time,
                    "data": self._cached_data
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Errore nel salvataggio forecast cache su disco: {e}")

    def _save_aqi_disk_cache(self):
        """Salva la cache della qualità dell'aria su disco."""
        try:
            os.makedirs(settings.DATA_DIR, exist_ok=True)
            with open(self._aqi_cache_file, "w", encoding="utf-8") as f:
                json.dump({
                    "fetched_at": self._last_aqi_fetch,
                    "data": self._cached_aqi
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Errore nel salvataggio AQI cache su disco: {e}")

    def get_wmo_info(self, code: Optional[int]) -> Dict[str, str]:
        """Restituisce testo, icona e descrizione per un codice meteo WMO."""
        if code is None:
            return {"text": "Variabile", "icon": "🌤️", "desc": "Condizioni meteo nella media."}
        return WMO_CODE_MAP.get(code, {"text": "Variabile", "icon": "🌤️", "desc": "Condizioni meteo nella media."})

    def fetch_open_meteo(self, force: bool = False) -> Optional[Dict[str, Any]]:
        """
        Scarica le previsioni meteo ad alta risoluzione e parametri solari da Open-Meteo.
        Implementa caching in memoria e su disco.
        """
        now = time.time()
        if not force and self._cached_data and (now - self._last_fetch_time < self.cache_ttl):
            return self._cached_data

        lat = settings.LATITUDE
        lon = settings.LONGITUDE
        elev = settings.ELEVATION

        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}&elevation={elev}"
            f"&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum,"
            f"precipitation_probability_max,windspeed_10m_max,uv_index_max,shortwave_radiation_sum,sunshine_duration"
            f"&hourly=temperature_2m,relativehumidity_2m,precipitation,precipitation_probability,"
            f"weathercode,windspeed_10m,direct_radiation,diffuse_radiation,shortwave_radiation_instant"
            f"&timezone=auto&forecast_days=7"
        )

        try:
            logger.info(f"Scaricamento previsioni Open-Meteo per lat={lat}, lon={lon}, elev={elev}m...")
            resp = requests.get(url, timeout=8, headers={"User-Agent": "WeatherHub/1.0"})
            if resp.status_code == 200:
                raw_json = resp.json()
                processed = self._process_open_meteo_payload(raw_json)
                self._cached_data = processed
                self._last_fetch_time = now
                self._save_disk_cache()
                logger.info("Previsioni Open-Meteo aggiornate con successo")
                return self._cached_data
            else:
                logger.error(f"Errore HTTP da Open-Meteo API ({resp.status_code}): {resp.text[:200]}")
                self._last_fetch_time = now - self.cache_ttl + 300
        except Exception as e:
            logger.error(f"Eccezione durante la richiesta a Open-Meteo: {e}")
            self._last_fetch_time = now - self.cache_ttl + 300

        return self._cached_data

    def _process_open_meteo_payload(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Elabora e formatta il payload di Open-Meteo in una struttura pulita per frontend e API."""
        daily_raw = raw.get("daily", {})
        hourly_raw = raw.get("hourly", {})

        daily_times = daily_raw.get("time", [])
        daily_codes = daily_raw.get("weathercode", [])
        daily_max_t = daily_raw.get("temperature_2m_max", [])
        daily_min_t = daily_raw.get("temperature_2m_min", [])
        daily_precip = daily_raw.get("precipitation_sum", [])
        daily_prob = daily_raw.get("precipitation_probability_max", [])
        daily_wind = daily_raw.get("windspeed_10m_max", [])
        daily_uv = daily_raw.get("uv_index_max", [])
        daily_rad_mj = daily_raw.get("shortwave_radiation_sum", [])
        daily_sun_sec = daily_raw.get("sunshine_duration", [])

        today_dt = settings.now_local().date()

        days_list: List[Dict[str, Any]] = []
        for i in range(len(daily_times)):
            d_str = daily_times[i]
            try:
                d_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
                delta_days = (d_obj - today_dt).days
                if delta_days == 0:
                    day_name = "Oggi"
                elif delta_days == 1:
                    day_name = "Domani"
                else:
                    day_name = ITALIAN_DAYS.get(d_obj.weekday(), d_obj.strftime("%a"))
                
                formatted_date = f"{d_obj.day} {ITALIAN_MONTHS.get(d_obj.month, '')}"
            except Exception:
                day_name = d_str
                formatted_date = d_str

            code = daily_codes[i] if i < len(daily_codes) else None
            prob_pct = int(daily_prob[i]) if i < len(daily_prob) and daily_prob[i] is not None else 0
            rain_mm = round(daily_precip[i], 1) if i < len(daily_precip) and daily_precip[i] is not None else 0.0

            if code in (51, 53, 55, 56, 57, 61, 63, 65, 80, 81) and prob_pct < 20 and rain_mm < 0.2:
                code = 2

            w_info = self.get_wmo_info(code)
            rad_mj = round(daily_rad_mj[i], 1) if i < len(daily_rad_mj) and daily_rad_mj[i] is not None else None
            sun_hours = round(daily_sun_sec[i] / 3600.0, 1) if i < len(daily_sun_sec) and daily_sun_sec[i] is not None else None

            days_list.append({
                "date": d_str,
                "formatted_date": formatted_date,
                "day_name": day_name,
                "weather_code": code,
                "icon": w_info["icon"],
                "condition": w_info["text"],
                "desc": w_info["desc"],
                "temp_max": round(daily_max_t[i], 1) if i < len(daily_max_t) and daily_max_t[i] is not None else None,
                "temp_min": round(daily_min_t[i], 1) if i < len(daily_min_t) and daily_min_t[i] is not None else None,
                "rain_sum_mm": rain_mm,
                "rain_prob_pct": prob_pct,
                "wind_max_kmh": round(daily_wind[i], 1) if i < len(daily_wind) and daily_wind[i] is not None else 0.0,
                "uv_max": round(daily_uv[i], 1) if i < len(daily_uv) and daily_uv[i] is not None else 0.0,
                "radiation_mj_m2": rad_mj,
                "sunshine_hours": sun_hours
            })

        now_dt = settings.now_local().replace(tzinfo=None)
        hourly_times = hourly_raw.get("time", [])
        hourly_temps = hourly_raw.get("temperature_2m", [])
        hourly_hums = hourly_raw.get("relativehumidity_2m", [])
        hourly_rains = hourly_raw.get("precipitation", [])
        hourly_probs = hourly_raw.get("precipitation_probability", [])
        hourly_codes = hourly_raw.get("weathercode", [])
        hourly_winds = hourly_raw.get("windspeed_10m", [])
        hourly_direct_rad = hourly_raw.get("direct_radiation", [])
        hourly_diffuse_rad = hourly_raw.get("diffuse_radiation", [])

        hours_list: List[Dict[str, Any]] = []
        for j in range(len(hourly_times)):
            t_str = hourly_times[j]
            try:
                t_dt = datetime.strptime(t_str, "%Y-%m-%dT%H:%M")
                diff_hours = (t_dt - now_dt).total_seconds() / 3600.0
                if -1.0 <= diff_hours <= 48.0:
                    code = hourly_codes[j] if j < len(hourly_codes) else None
                    prob_pct = int(hourly_probs[j]) if j < len(hourly_probs) and hourly_probs[j] is not None else 0
                    rain_mm = round(hourly_rains[j], 1) if j < len(hourly_rains) else 0.0

                    if code in (51, 53, 55, 56, 57, 61, 63, 65, 80, 81) and prob_pct < 20 and rain_mm < 0.2:
                        code = 2

                    w_info = self.get_wmo_info(code)
                    dir_r = hourly_direct_rad[j] if j < len(hourly_direct_rad) and hourly_direct_rad[j] is not None else 0.0
                    dif_r = hourly_diffuse_rad[j] if j < len(hourly_diffuse_rad) and hourly_diffuse_rad[j] is not None else 0.0
                    total_rad_w = round(dir_r + dif_r, 1)

                    hours_list.append({
                        "iso_time": t_str,
                        "hour_label": t_dt.strftime("%H:%M"),
                        "day_short": ITALIAN_DAYS.get(t_dt.weekday(), "")[:3],
                        "temp_c": round(hourly_temps[j], 1) if j < len(hourly_temps) else None,
                        "humidity": round(hourly_hums[j], 0) if j < len(hourly_hums) else None,
                        "rain_mm": rain_mm,
                        "rain_prob_pct": prob_pct,
                        "wind_kmh": round(hourly_winds[j], 1) if j < len(hourly_winds) else 0.0,
                        "solar_irradiance_w_m2": total_rad_w,
                        "weather_code": code,
                        "icon": w_info["icon"],
                        "condition": w_info["text"]
                    })
            except Exception:
                continue

        return {
            "source": "Open-Meteo (ECMWF IFS & ICON-EU)",
            "updated_at": settings.now_local().strftime("%Y-%m-%d %H:%M:%S"),
            "daily": days_list,
            "hourly_next_36h": hours_list,
            "raw_hourly": hourly_raw
        }

    # ----------------- 4. QUALITÀ DELL'ARIA & POLLINI (COPERNICUS CAMS) -----------------

    def fetch_air_quality(self, force: bool = False) -> Dict[str, Any]:
        """
        Scarica i dati di qualità dell'aria (EAQI, PM2.5, PM10, NO2, O3, CO, SO2)
        e pollini (Graminacee, Betulla, Olivo, Ambrosia, Ontano, Artemisia) da Open-Meteo CAMS.
        """
        now = time.time()
        if not force and self._cached_aqi and (now - self._last_aqi_fetch < self.cache_ttl):
            return self._cached_aqi

        lat = settings.LATITUDE
        lon = settings.LONGITUDE

        url = (
            f"https://air-quality-api.open-meteo.com/v1/air-quality"
            f"?latitude={lat}&longitude={lon}"
            f"&current=european_aqi,us_aqi,pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone,"
            f"alder_pollen,birch_pollen,grass_pollen,mugwort_pollen,olive_pollen,ragweed_pollen,dust"
            f"&hourly=european_aqi,pm2_5,pm10,ozone,nitrogen_dioxide"
            f"&timezone=auto"
        )

        try:
            logger.info(f"Scaricamento Qualità dell'Aria & Pollini CAMS per lat={lat}, lon={lon}...")
            resp = requests.get(url, timeout=8, headers={"User-Agent": "WeatherHub/1.0"})
            if resp.status_code == 200:
                raw_json = resp.json()
                processed = self._process_air_quality_payload(raw_json)
                self._cached_aqi = processed
                self._last_aqi_fetch = now
                self._save_aqi_disk_cache()
                logger.info("Qualità dell'aria e pollini aggiornati con successo")
                return self._cached_aqi
            else:
                logger.error(f"Errore HTTP da Air Quality API ({resp.status_code}): {resp.text[:200]}")
                self._last_aqi_fetch = now - self.cache_aqi_ttl + 300
        except Exception as e:
            logger.error(f"Eccezione durante richiesta qualità dell'aria: {e}")
            self._last_aqi_fetch = now - self.cache_aqi_ttl + 300

        if self._cached_aqi:
            return self._cached_aqi

        return self._get_fallback_air_quality()

    def _process_air_quality_payload(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Elabora e struttura i dati di inquinanti e pollini per l'Hub."""
        curr = raw.get("current", {})
        
        eaqi_val = curr.get("european_aqi")
        if eaqi_val is None or eaqi_val <= 0:
            eaqi_val = 1
        elif eaqi_val > 5:
            eaqi_val = 5

        eaqi_meta = EAQI_INFO.get(int(eaqi_val), EAQI_INFO[1])

        pm25 = curr.get("pm2_5")
        pm10 = curr.get("pm10")
        no2 = curr.get("nitrogen_dioxide")
        o3 = curr.get("ozone")
        co = curr.get("carbon_monoxide")
        so2 = curr.get("sulphur_dioxide")

        pollens = {
            "grass": self._classify_pollen("Graminacee", curr.get("grass_pollen"), [0, 5, 25, 75]),
            "olive": self._classify_pollen("Olivo", curr.get("olive_pollen"), [0, 10, 50, 150]),
            "birch": self._classify_pollen("Betulla", curr.get("birch_pollen"), [0, 10, 50, 100]),
            "ragweed": self._classify_pollen("Ambrosia", curr.get("ragweed_pollen"), [0, 5, 20, 50]),
            "alder": self._classify_pollen("Ontano", curr.get("alder_pollen"), [0, 10, 50, 100]),
            "mugwort": self._classify_pollen("Artemisia", curr.get("mugwort_pollen"), [0, 5, 20, 50]),
        }

        highest_pollen = max(pollens.values(), key=lambda p: p["severity_score"])

        pm25_val = float(pm25) if pm25 is not None else 0.0
        if pm25_val >= 35.0 or eaqi_val >= 4:
            window_advice = "Qualità aria scadente: sconsigliato arieggiare o limitare a pochi minuti."
            window_status = "poor"
        elif highest_pollen["severity_score"] >= 3:
            window_advice = f"Attenzione: concentrazione elevata di pollini ({highest_pollen['name']}). Limitare aerazione se allergici."
            window_status = "pollen_high"
        elif pm25_val < 15.0 and eaqi_val <= 2:
            window_advice = "Aria pulita e salubre: ottimo momento per arieggiare casa."
            window_status = "good"
        else:
            window_advice = "Qualità dell'aria nella norma."
            window_status = "moderate"

        return {
            "source": "Copernicus Atmosphere Monitoring Service (CAMS)",
            "updated_at": settings.now_local().strftime("%Y-%m-%d %H:%M"),
            "eaqi": {
                "value": int(eaqi_val),
                "label": eaqi_meta["label"],
                "badge_class": eaqi_meta["badge_class"],
                "color": eaqi_meta["color"],
                "icon": eaqi_meta["icon"],
                "desc": eaqi_meta["desc"]
            },
            "pollutants": {
                "pm2_5": {"val": round(pm25, 1) if pm25 is not None else None, "unit": "µg/m³", "label": "PM2.5 (Fine)"},
                "pm10": {"val": round(pm10, 1) if pm10 is not None else None, "unit": "µg/m³", "label": "PM10 (Inalabile)"},
                "no2": {"val": round(no2, 1) if no2 is not None else None, "unit": "µg/m³", "label": "Biossido di Azoto (NO₂)"},
                "o3": {"val": round(o3, 1) if o3 is not None else None, "unit": "µg/m³", "label": "Ozono (O₃)"},
                "co": {"val": round(co, 1) if co is not None else None, "unit": "µg/m³", "label": "Monossido di Carbonio (CO)"},
                "so2": {"val": round(so2, 1) if so2 is not None else None, "unit": "µg/m³", "label": "Biossido di Zolfo (SO₂)"},
            },
            "pollens": pollens,
            "dominant_pollen": highest_pollen,
            "window_advice": window_advice,
            "window_status": window_status
        }

    def _classify_pollen(self, name: str, val: Optional[float], thresholds: List[float]) -> Dict[str, Any]:
        """Classifica i pollini in Assente, Basso, Medio, Alto, Molto Alto."""
        if val is None or val < 0.1:
            return {"name": name, "val": 0.0, "level": "Assente", "badge": "badge-neutral", "color": "#94a3b8", "severity_score": 0}
        
        v = float(val)
        if v < thresholds[1]:
            return {"name": name, "val": round(v, 1), "level": "Basso", "badge": "badge-success", "color": "#10b981", "severity_score": 1}
        elif v < thresholds[2]:
            return {"name": name, "val": round(v, 1), "level": "Medio", "badge": "badge-warning", "color": "#f59e0b", "severity_score": 2}
        elif v < thresholds[3]:
            return {"name": name, "val": round(v, 1), "level": "Alto", "badge": "badge-danger", "color": "#f97316", "severity_score": 3}
        else:
            return {"name": name, "val": round(v, 1), "level": "Molto Alto", "badge": "badge-danger", "color": "#ef4444", "severity_score": 4}

    def _get_fallback_air_quality(self) -> Dict[str, Any]:
        """Fallback in caso di assenza temporanea di rete."""
        return {
            "source": "Stima Locale",
            "updated_at": settings.now_local().strftime("%Y-%m-%d %H:%M"),
            "eaqi": {
                "value": 1,
                "label": "Buona (Stima)",
                "badge_class": "badge-success",
                "color": "#10b981",
                "icon": "🟢",
                "desc": "Aria in condizioni stabili."
            },
            "pollutants": {
                "pm2_5": {"val": 8.0, "unit": "µg/m³", "label": "PM2.5"},
                "pm10": {"val": 14.0, "unit": "µg/m³", "label": "PM10"},
                "no2": {"val": 10.0, "unit": "µg/m³", "label": "NO₂"},
                "o3": {"val": 45.0, "unit": "µg/m³", "label": "O₃"},
                "co": {"val": 150.0, "unit": "µg/m³", "label": "CO"},
                "so2": {"val": 2.0, "unit": "µg/m³", "label": "SO₂"},
            },
            "pollens": {
                "grass": {"name": "Graminacee", "val": 0.0, "level": "Basso", "badge": "badge-success", "color": "#10b981", "severity_score": 1},
                "olive": {"name": "Olivo", "val": 0.0, "level": "Basso", "badge": "badge-success", "color": "#10b981", "severity_score": 1},
                "birch": {"name": "Betulla", "val": 0.0, "level": "Assente", "badge": "badge-neutral", "color": "#94a3b8", "severity_score": 0},
                "ragweed": {"name": "Ambrosia", "val": 0.0, "level": "Assente", "badge": "badge-neutral", "color": "#94a3b8", "severity_score": 0},
                "alder": {"name": "Ontano", "val": 0.0, "level": "Assente", "badge": "badge-neutral", "color": "#94a3b8", "severity_score": 0},
                "mugwort": {"name": "Artemisia", "val": 0.0, "level": "Assente", "badge": "badge-neutral", "color": "#94a3b8", "severity_score": 0},
            },
            "dominant_pollen": {"name": "Graminacee", "val": 0.0, "level": "Basso", "severity_score": 1},
            "window_advice": "Qualità dell'aria nella norma.",
            "window_status": "good"
        }

    # ----------------- 7. PREVISIONE ENERGETICA FOTOVOLTAICO & BATTERIA -----------------

    def fetch_solar_forecast(self, aton_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Calcola la produzione fotovoltaica stimata per Oggi e Domani (in kWh),
        la curva di insolazione oraria, la finestra ideale per elettrodomestici,
        l'orario stimato di batteria al 100% e il surplus previsto.
        """
        forecast = self.fetch_open_meteo()
        kwp = settings.SOLAR_INSTALLED_KWP
        pr = 0.80

        today_est_kwh = 0.0
        tomorrow_est_kwh = 0.0
        tomorrow_peak_start = "11:00"
        tomorrow_peak_end = "15:30"
        est_surplus_kwh = 0.0

        if forecast and forecast.get("daily"):
            days = forecast["daily"]
            if len(days) >= 1 and days[0].get("radiation_mj_m2") is not None:
                rad_mj_today = days[0]["radiation_mj_m2"] or 18.0
                today_est_kwh = round((rad_mj_today / 3.6) * kwp * pr, 1)

            if len(days) >= 2 and days[1].get("radiation_mj_m2") is not None:
                rad_mj_tom = days[1]["radiation_mj_m2"] or 18.0
                tomorrow_est_kwh = round((rad_mj_tom / 3.6) * kwp * pr, 1)
            else:
                tomorrow_est_kwh = round(today_est_kwh * 0.95, 1)

        if tomorrow_est_kwh <= 0.0:
            month = settings.now_local().month
            summer_months = {5: 24, 6: 28, 7: 28, 8: 26, 9: 20}
            winter_months = {11: 10, 12: 8, 1: 9, 2: 12, 3: 16, 4: 20, 10: 14}
            base = summer_months.get(month, winter_months.get(month, 18))
            tomorrow_est_kwh = round(base * (kwp / 6.0), 1)
            today_est_kwh = tomorrow_est_kwh

        avg_house_daily_kwh = 9.0
        est_surplus_kwh = max(0.0, round(tomorrow_est_kwh - avg_house_daily_kwh, 1))

        if tomorrow_est_kwh >= 22.0:
            battery_100_est = "12:15 - 13:00"
        elif tomorrow_est_kwh >= 15.0:
            battery_100_est = "13:30 - 14:30"
        else:
            battery_100_est = "Non garantito (giornata coperta)"

        soc_now = aton_data.get("soc") if aton_data else None
        p_solare_now = aton_data.get("p_solare") if aton_data else None

        return {
            "installed_kwp": kwp,
            "today_est_kwh": today_est_kwh,
            "tomorrow_est_kwh": tomorrow_est_kwh,
            "tomorrow_range_str": f"{max(1.0, tomorrow_est_kwh - 2.0):.0f}-{tomorrow_est_kwh + 2.0:.0f} kWh",
            "best_appliances_window": f"{tomorrow_peak_start} - {tomorrow_peak_end}",
            "battery_100_est": battery_100_est,
            "est_surplus_kwh": est_surplus_kwh,
            "summary_text": f"☀️ Produzione stimata domani: {tomorrow_est_kwh:.1f} kWh. Finestra consigliata elettrodomestici: {tomorrow_peak_start}-{tomorrow_peak_end}.",
            "live_soc": soc_now,
            "live_solar_w": p_solare_now
        }

    # ----------------- 3. NOWCASTING RADAR & PRECIPITAZIONI -----------------

    def build_rain_nowcasting_summary(self, current_reading: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Algoritmo di nowcasting pioggia a 0-6 ore che combina:
        - Telemetria live della stazione (pioggia in corso, rain rate, trend barometrico)
        - Previsioni orarie ad alta risoluzione Open-Meteo (prossime 6 ore)
        - Calcolo tempi di arrivo stimati pioggia / rovesci.
        """
        current_rain_rate = current_reading.get("rain_rate_mm_hr", 0.0) if current_reading else 0.0

        forecast = self.fetch_open_meteo()
        hourly = forecast.get("hourly_next_36h", []) if forecast else []

        now_dt = settings.now_local().replace(tzinfo=None)

        max_prob_6h = 0
        total_rain_6h = 0.0
        first_rain_hour: Optional[Dict[str, Any]] = None

        for h in hourly:
            try:
                h_dt = datetime.strptime(h["iso_time"], "%Y-%m-%dT%H:%M")
                diff_h = (h_dt - now_dt).total_seconds() / 3600.0
                if 0.0 <= diff_h <= 6.5:
                    prob = h.get("rain_prob_pct", 0)
                    r_mm = h.get("rain_mm", 0.0)
                    if prob > max_prob_6h:
                        max_prob_6h = prob
                    total_rain_6h += r_mm
                    if r_mm >= 0.3 and prob >= 40 and first_rain_hour is None:
                        first_rain_hour = h
            except Exception:
                continue

        if current_rain_rate and current_rain_rate > 0.2:
            if current_rain_rate >= 15.0:
                headline = f"⛈️ Nubifragio in corso ({current_rain_rate} mm/h)!"
                desc = "Precipitazioni molto intense sulla stazione meteo."
                status_class = "danger"
                icon = "⛈️"
            elif current_rain_rate >= 4.0:
                headline = f"🌧️ Pioggia moderata/forte ({current_rain_rate} mm/h)"
                desc = "Precipitazioni attive in corso."
                status_class = "warning"
                icon = "🌧️"
            else:
                headline = f"🌦️ Pioviggine / Pioggia debole ({current_rain_rate} mm/h)"
                desc = "Deboli precipitazioni rilevate dai sensori."
                status_class = "info"
                icon = "🌦️"

            return {
                "active_rain": True,
                "headline": headline,
                "desc": desc,
                "icon": icon,
                "status_class": status_class,
                "prob_next_6h": 100,
                "rain_sum_next_6h": round(total_rain_6h, 1),
                "radar_link": "/radar"
            }

        if first_rain_hour is not None:
            try:
                first_dt = datetime.strptime(first_rain_hour["iso_time"], "%Y-%m-%dT%H:%M")
                min_until = max(15, int((first_dt - now_dt).total_seconds() / 60.0))
                time_range_min = f"{max(15, min_until - 20)}-{min_until + 20}"

                if first_rain_hour.get("weather_code") in (95, 96, 99, 82):
                    headline = f"⛈️ Temporale / Cella in avvicinamento (tra ~{time_range_min} min)"
                    desc = f"Attività convettiva o rovesci previsti intorno alle {first_rain_hour['hour_label']} (probabilità {first_rain_hour['rain_prob_pct']}%)."
                    status_class = "danger"
                    icon = "⛈️"
                else:
                    headline = f"🌧️ Pioggia prevista nella tua zona tra circa {time_range_min} minuti"
                    desc = f"Inizio precipitazioni stimato intorno alle {first_rain_hour['hour_label']} (accumulo stimato: {first_rain_hour['rain_mm']} mm)."
                    status_class = "warning"
                    icon = "🌧️"

                return {
                    "active_rain": False,
                    "headline": headline,
                    "desc": desc,
                    "icon": icon,
                    "status_class": status_class,
                    "prob_next_6h": max_prob_6h,
                    "rain_sum_next_6h": round(total_rain_6h, 1),
                    "radar_link": "/radar"
                }
            except Exception:
                pass

        if max_prob_6h >= 30 and total_rain_6h > 0.1:
            headline = f"⛅ Possibilità di isolati piovaschi nelle prossime 6 ore ({max_prob_6h}%)"
            desc = "Bassa probabilità di fenomeni isolati o locali."
            status_class = "info"
            icon = "🌦️"
        else:
            headline = "☀️ Niente pioggia nelle prossime 6 ore"
            desc = "Condizioni asciutte e cielo stabile sulla tua zona."
            status_class = "success"
            icon = "☀️"

        return {
            "active_rain": False,
            "headline": headline,
            "desc": desc,
            "icon": icon,
            "status_class": status_class,
            "prob_next_6h": max_prob_6h,
            "rain_sum_next_6h": round(total_rain_6h, 1),
            "radar_link": "/radar"
        }

    # ----------------- CROSS CHECK MODELLO VS STAZIONE -----------------

    def build_cross_check_summary(self, current_reading: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Incrocia la telemetria reale della stazione locale con la previsione oraria del modello.
        Calcola lo scostamento termico (Bias locale) e lo stato di accuratezza.
        """
        forecast = self.fetch_open_meteo()
        if not forecast or not current_reading:
            return {
                "available": False,
                "status": "In attesa dati",
                "delta_temp": None,
                "text": "Dati di cross-check non ancora disponibili."
            }

        hourly = forecast.get("hourly_next_36h", [])
        if not hourly:
            return {
                "available": False,
                "status": "In attesa dati",
                "delta_temp": None,
                "text": "Nessuna ora previsionale disponibile."
            }

        now_dt = settings.now_local().replace(tzinfo=None)
        closest_hour = hourly[0]
        min_diff = 999999
        for h in hourly:
            try:
                h_dt = datetime.strptime(h["iso_time"], "%Y-%m-%dT%H:%M")
                diff = abs((h_dt - now_dt).total_seconds())
                if diff < min_diff:
                    min_diff = diff
                    closest_hour = h
            except Exception:
                continue

        station_temp = current_reading.get("temp_c")
        model_temp = closest_hour.get("temp_c")

        if station_temp is None or model_temp is None:
            return {
                "available": False,
                "status": "Dati parziali",
                "delta_temp": None,
                "text": "Temperatura stazione non rilevata."
            }

        delta_t = round(station_temp - model_temp, 1)
        sign = "+" if delta_t > 0 else ""
        
        if abs(delta_t) <= 0.8:
            accuracy_status = "Ottimo accordo col modello"
            badge_class = "badge-success"
            accuracy_desc = f"Stazione ({station_temp}°C) in ottimo accordo col modello ECMWF ({model_temp}°C, scarto {sign}{delta_t}°C)."
        elif abs(delta_t) <= 2.0:
            accuracy_status = "Buon accordo col modello"
            badge_class = "badge-info"
            accuracy_desc = f"Stazione ({station_temp}°C) vs Modello ECMWF ({model_temp}°C, scarto {sign}{delta_t}°C)."
        else:
            accuracy_status = "Scostamento locale"
            badge_class = "badge-warning"
            loc_str = f" a {settings.LOCATION_NAME}" if settings.LOCATION_NAME else ""
            accuracy_desc = f"Marcata variazione microclimatica{loc_str}: Stazione {station_temp}°C vs Modello ({model_temp}°C, scarto {sign}{delta_t}°C)."

        return {
            "available": True,
            "status": accuracy_status,
            "badge_class": badge_class,
            "station_temp": station_temp,
            "model_temp": model_temp,
            "delta_temp": delta_t,
            "delta_str": f"{sign}{delta_t}°C",
            "model_condition": closest_hour.get("condition"),
            "model_icon": closest_hour.get("icon"),
            "model_rain_prob": closest_hour.get("rain_prob_pct", 0),
            "text": accuracy_desc
        }


forecast_service = ForecastService()
