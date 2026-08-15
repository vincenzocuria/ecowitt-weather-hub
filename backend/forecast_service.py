import os
import json
import time
import logging
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


class ForecastService:
    def __init__(self, cache_ttl_seconds: int = 3600):
        self.cache_ttl = cache_ttl_seconds
        self._cached_data: Optional[Dict[str, Any]] = None
        self._last_fetch_time: float = 0.0
        self._cache_file = os.path.join(settings.DATA_DIR, "forecast_cache.json")
        self._load_disk_cache()

    def _load_disk_cache(self):
        """Carica l'ultima previsione salvata su disco se disponibile e valida."""
        if os.path.exists(self._cache_file):
            try:
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._cached_data = data.get("data")
                    self._last_fetch_time = data.get("fetched_at", 0.0)
                    logger.info("Caricata cache previsioni da disco con successo")
            except Exception as e:
                logger.warning(f"Impossibile leggere forecast cache da disco: {e}")

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

    def get_wmo_info(self, code: Optional[int]) -> Dict[str, str]:
        """Restituisce testo, icona e descrizione per un codice meteo WMO."""
        if code is None:
            return {"text": "Variabile", "icon": "🌤️", "desc": "Condizioni meteo nella media."}
        return WMO_CODE_MAP.get(code, {"text": "Variabile", "icon": "🌤️", "desc": "Condizioni meteo nella media."})

    def fetch_open_meteo(self, force: bool = False) -> Optional[Dict[str, Any]]:
        """
        Scarica le previsioni meteo ad alta risoluzione da Open-Meteo per le coordinate configurate.
        Implementa caching in memoria e su disco.
        """
        now = time.time()
        if not force and self._cached_data and (now - self._last_fetch_time < self.cache_ttl):
            return self._cached_data

        lat = settings.LATITUDE
        lon = settings.LONGITUDE

        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum,"
            f"precipitation_probability_max,windspeed_10m_max,uv_index_max"
            f"&hourly=temperature_2m,relativehumidity_2m,precipitation,precipitation_probability,"
            f"weathercode,windspeed_10m"
            f"&timezone=auto&forecast_days=7"
        )

        try:
            logger.info(f"Scaricamento previsioni Open-Meteo per lat={lat}, lon={lon}...")
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
        except Exception as e:
            logger.error(f"Eccezione durante la richiesta a Open-Meteo: {e}")

        # Se fallisce la rete, ritorna la cache esistente se presente
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

            # FILTRO METEOROLOGICO REALISTICO:
            # Se la probabilità di pioggia è trascurabile (< 20% e accumulo < 0.2mm) ma il modello
            # restituisce un codice WMO di pioggia/pioviggine (es. 51-67, 80-81), correggi il codice
            # verso parzialmente nuvoloso o sereno per evitare di mostrare nuvole di pioggia ingannevoli per l'1%.
            if code in (51, 53, 55, 56, 57, 61, 63, 65, 80, 81) and prob_pct < 20 and rain_mm < 0.2:
                code = 2  # Parzialmente nuvoloso

            w_info = self.get_wmo_info(code)

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
            })

        # Elabora le prossime 24-48 ore
        now_dt = settings.now_local().replace(tzinfo=None)
        hourly_times = hourly_raw.get("time", [])
        hourly_temps = hourly_raw.get("temperature_2m", [])
        hourly_hums = hourly_raw.get("relativehumidity_2m", [])
        hourly_rains = hourly_raw.get("precipitation", [])
        hourly_probs = hourly_raw.get("precipitation_probability", [])
        hourly_codes = hourly_raw.get("weathercode", [])
        hourly_winds = hourly_raw.get("windspeed_10m", [])

        hours_list: List[Dict[str, Any]] = []
        for j in range(len(hourly_times)):
            t_str = hourly_times[j]
            try:
                t_dt = datetime.strptime(t_str, "%Y-%m-%dT%H:%M")
                # Prendi da 1 ora fa fino alle prossime 36 ore
                diff_hours = (t_dt - now_dt).total_seconds() / 3600.0
                if -1.0 <= diff_hours <= 36.0:
                    code = hourly_codes[j] if j < len(hourly_codes) else None
                    prob_pct = int(hourly_probs[j]) if j < len(hourly_probs) and hourly_probs[j] is not None else 0
                    rain_mm = round(hourly_rains[j], 1) if j < len(hourly_rains) else 0.0

                    if code in (51, 53, 55, 56, 57, 61, 63, 65, 80, 81) and prob_pct < 20 and rain_mm < 0.2:
                        code = 2  # Parzialmente nuvoloso

                    w_info = self.get_wmo_info(code)
                    hours_list.append({
                        "iso_time": t_str,
                        "hour_label": t_dt.strftime("%H:%M"),
                        "day_short": ITALIAN_DAYS.get(t_dt.weekday(), "")[:3],
                        "temp_c": round(hourly_temps[j], 1) if j < len(hourly_temps) else None,
                        "humidity": round(hourly_hums[j], 0) if j < len(hourly_hums) else None,
                        "rain_mm": rain_mm,
                        "rain_prob_pct": prob_pct,
                        "wind_kmh": round(hourly_winds[j], 1) if j < len(hourly_winds) else 0.0,
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

        # Cerca l'ora più vicina
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
        station_rain = current_reading.get("rain_rate_mm_hr", 0.0) or 0.0
        model_rain = closest_hour.get("rain_mm", 0.0) or 0.0

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
            accuracy_status = "Ottima Correlazione"
            badge_class = "badge-success"
            accuracy_desc = f"Stazione ({station_temp}°C) perfettamente allineata al modello ({model_temp}°C, Δ {sign}{delta_t}°C)."
        elif abs(delta_t) <= 2.0:
            accuracy_status = "Buon Allineamento"
            badge_class = "badge-info"
            accuracy_desc = f"Microclima locale: Stazione {station_temp}°C vs Modello {model_temp}°C ({sign}{delta_t}°C)."
        else:
            accuracy_status = "Microclima Specifico"
            badge_class = "badge-warning"
            loc_str = f" a {settings.LOCATION_NAME}" if settings.LOCATION_NAME else ""
            accuracy_desc = f"Marcata variazione locale{loc_str}: Stazione {station_temp}°C vs Modello {model_temp}°C ({sign}{delta_t}°C)."

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
