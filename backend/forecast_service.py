import os
import json
import time
import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
import requests

from backend.config import settings
from backend.helpers import (
    ITALIAN_WEEKDAYS as ITALIAN_DAYS,
    ITALIAN_SHORT_MONTHS as ITALIAN_MONTHS,
    format_duration_italian
)

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


EAQI_INFO = {
    1: {"label": "Molto Buona", "badge_class": "badge-success", "color": "#10b981", "icon": "🟢", "desc": "Aria pulita e ideale per ventilare ambienti e attività all'aperto."},
    2: {"label": "Buona", "badge_class": "badge-success", "color": "#22c55e", "icon": "🟢", "desc": "Qualità dell'aria buona. Nessun rischio per la popolazione."},
    3: {"label": "Moderata", "badge_class": "badge-warning", "color": "#f59e0b", "icon": "🟡", "desc": "Accettabile, ma soggetti ipersensibili potrebbero avvertire lievi fastidi."},
    4: {"label": "Scadente", "badge_class": "badge-danger", "color": "#f97316", "icon": "🟠", "desc": "Qualità dell'aria scadente. Si consiglia di limitare l'apertura prolungata delle finestre."},
    5: {"label": "Molto Scadente", "badge_class": "badge-danger", "color": "#ef4444", "icon": "🔴", "desc": "Inquinamento elevato. Finestre chiuse e uso purificatori consigliato."}
}


# Codici WMO "cielo sereno/poco nuvoloso" per cui di notte si mostra un'icona notturna.
NIGHT_ICON_OVERRIDES = {0: "🌙", 1: "🌙", 2: "☁️"}

# Codici WMO di pioviggine/pioggia che vengono declassati a "parzialmente nuvoloso"
# quando probabilità e accumulo sono trascurabili.
DOWNGRADABLE_RAIN_CODES = (51, 53, 55, 56, 57, 61, 63, 65, 80, 81)

DAILY_VARS = [
    "weathercode", "temperature_2m_max", "temperature_2m_min", "precipitation_sum",
    "precipitation_probability_max", "windspeed_10m_max", "uv_index_max",
    "shortwave_radiation_sum", "sunshine_duration",
]
HOURLY_VARS = [
    "temperature_2m", "apparent_temperature", "relativehumidity_2m", "precipitation",
    "precipitation_probability", "weathercode", "cloudcover", "windspeed_10m",
    "windgusts_10m", "winddirection_10m", "direct_radiation", "diffuse_radiation",
    "shortwave_radiation_instant", "is_day",
]

MODEL_LABELS = {
    "icon_seamless": "DWD ICON",
    "ecmwf_ifs025": "ECMWF IFS",
    "best_match": "best match",
    "italia_meteo_arpae_icon_2i": "ItaliaMeteo ICON-2I",
}

# Correzione locale temperatura: scarto massimo applicato e costante di attenuazione (ore)
TEMP_BIAS_MAX_C = 6.0
TEMP_BIAS_DECAY_H = 6.0

# Oltre questa età (secondi) la previsione in cache viene segnalata come non aggiornata.
STALE_FORECAST_SECONDS = 3 * 3600


def rain_intensity_label(mm_per_hour: Optional[float]) -> str:
    """Descrizione a parole dell'intensità di pioggia oraria (mm/h)."""
    mm = mm_per_hour or 0.0
    if mm < 0.1:
        return "asciutto"
    if mm < 0.5:
        return "qualche goccia"
    if mm < 2.0:
        return "pioggia debole"
    if mm < 6.0:
        return "pioggia moderata"
    if mm < 15.0:
        return "pioggia forte"
    return "nubifragio"


def _val(seq: List[Any], idx: int) -> Optional[Any]:
    """Elemento idx di una serie Open-Meteo, oppure None se mancante o nullo."""
    return seq[idx] if idx < len(seq) else None


def _rounded(seq: List[Any], idx: int, digits: int = 1, default: Optional[float] = None) -> Optional[float]:
    v = _val(seq, idx)
    return round(v, digits) if v is not None else default


class ForecastService:
    def __init__(self, cache_ttl_seconds: int = 3600):
        self.cache_ttl = cache_ttl_seconds
        # Si conserva il payload grezzo: la finestra oraria e le etichette Oggi/Domani
        # vengono ricalcolate a ogni lettura, così non invecchiano insieme alla cache.
        self._cached_raw: Optional[Dict[str, Any]] = None
        self._last_fetch_time: float = 0.0
        self._last_success_time: float = 0.0
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
                # Il vecchio formato (dati già elaborati in "data") non è riutilizzabile.
                if isinstance(data.get("raw"), dict):
                    self._cached_raw = data["raw"]
                    self._last_fetch_time = data.get("fetched_at", 0.0)
                    self._last_success_time = self._last_fetch_time
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
        """Salva il payload grezzo su disco per persistenza ai riavvii."""
        try:
            os.makedirs(settings.DATA_DIR, exist_ok=True)
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump({
                    "fetched_at": self._last_success_time,
                    "raw": self._cached_raw
                }, f, ensure_ascii=False)
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
        Il payload grezzo è in cache (memoria + disco); l'elaborazione relativa all'ora
        corrente viene rifatta a ogni chiamata.
        """
        now = time.time()
        if force or not self._cached_raw or (now - self._last_fetch_time >= self.cache_ttl):
            self._download_open_meteo(now)

        if not self._cached_raw:
            return None
        return self._process_open_meteo_payload(self._cached_raw)

    @staticmethod
    def _models() -> List[str]:
        return [m.strip() for m in (settings.FORECAST_MODELS or "").split(",") if m.strip()] or ["best_match"]

    @staticmethod
    def _merge_models(section: Dict[str, Any], variables: List[str], models: List[str],
                      precip_var: str, prob_vars: List[str]) -> Dict[str, Any]:
        """
        Combina in un'unica serie le variabili restituite da Open-Meteo per più modelli
        (chiavi "<variabile>_<modello>"). Regole:
        - probabilità di pioggia: massimo tra i modelli (un modello che prevede pioggia
          non deve essere annullato da uno che non la vede);
        - weathercode: quello del modello più piovoso se piove (>= 0.2 mm), altrimenti
          quello del primo modello;
        - is_day / direzione vento: primo valore disponibile;
        - altre variabili: media dei modelli disponibili.
        Aggiunge "<precip_var>_max"/"_min" (estremi tra i modelli) e "models_used".
        """
        def series(var: str) -> List[List[Any]]:
            if var in section:
                return [section[var]]
            return [section[f"{var}_{m}"] for m in models if f"{var}_{m}" in section]

        merged: Dict[str, Any] = {"time": section.get("time", [])}
        n = len(merged["time"])
        precip_series = series(precip_var)

        for var in variables:
            ss = series(var)
            if not ss:
                continue
            out: List[Any] = []
            for i in range(n):
                vals = [s[i] for s in ss if i < len(s) and s[i] is not None]
                if not vals:
                    out.append(None)
                elif var in prob_vars:
                    out.append(max(vals))
                elif var == "weathercode":
                    precs = [(s[i] if i < len(s) and s[i] is not None else -1.0) for s in precip_series]
                    if len(precs) == len(ss) and precs and max(precs) >= 0.2:
                        code = ss[precs.index(max(precs))][i]
                        out.append(code if code is not None else vals[0])
                    else:
                        out.append(vals[0])
                elif var in ("is_day", "winddirection_10m"):
                    out.append(vals[0])
                else:
                    out.append(sum(vals) / len(vals))
            merged[var] = out

        merged[f"{precip_var}_max"] = [
            max((s[i] for s in precip_series if i < len(s) and s[i] is not None), default=None)
            for i in range(n)
        ]
        merged[f"{precip_var}_min"] = [
            min((s[i] for s in precip_series if i < len(s) and s[i] is not None), default=None)
            for i in range(n)
        ]
        merged["models_used"] = len(precip_series)
        return merged

    def _download_open_meteo(self, now: float) -> None:
        lat = settings.LATITUDE
        lon = settings.LONGITUDE
        elev = settings.ELEVATION

        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}&elevation={elev}"
            f"&daily={','.join(DAILY_VARS)}"
            f"&hourly={','.join(HOURLY_VARS)}"
            f"&models={','.join(self._models())}"
            f"&timezone=auto&forecast_days=7"
        )

        try:
            logger.info(f"Scaricamento previsioni Open-Meteo per lat={lat}, lon={lon}, elev={elev}m...")
            resp = requests.get(url, timeout=8, headers={"User-Agent": "WeatherHub/1.0"})
            if resp.status_code == 200:
                self._cached_raw = resp.json()
                self._last_fetch_time = now
                self._last_success_time = now
                self._save_disk_cache()
                logger.info("Previsioni Open-Meteo aggiornate con successo")
                return
            logger.error(f"Errore HTTP da Open-Meteo API ({resp.status_code}): {resp.text[:200]}")
        except Exception as e:
            logger.error(f"Eccezione durante la richiesta a Open-Meteo: {e}")
        # Nuovo tentativo tra 5 minuti
        self._last_fetch_time = now - self.cache_ttl + 300

    def _process_open_meteo_payload(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Elabora e formatta il payload di Open-Meteo in una struttura pulita per frontend e API."""
        models = self._models()
        daily_raw = self._merge_models(raw.get("daily", {}), DAILY_VARS, models,
                                       "precipitation_sum", ["precipitation_probability_max"])
        hourly_raw = self._merge_models(raw.get("hourly", {}), HOURLY_VARS, models,
                                        "precipitation", ["precipitation_probability"])

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
                
                formatted_date = f"{d_obj.day} {ITALIAN_MONTHS.get(f'{d_obj.month:02d}', '')}"
            except Exception:
                day_name = d_str
                formatted_date = d_str

            code = daily_codes[i] if i < len(daily_codes) else None
            prob_pct = int(daily_prob[i]) if i < len(daily_prob) and daily_prob[i] is not None else 0
            rain_mm = round(daily_precip[i], 1) if i < len(daily_precip) and daily_precip[i] is not None else 0.0

            if code in DOWNGRADABLE_RAIN_CODES and prob_pct < 20 and rain_mm < 0.2:
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
        # Prima ora mostrata = ora corrente (es. alle 14:35 si parte dalle 14:00)
        window_start = now_dt.replace(minute=0, second=0, microsecond=0)
        hourly_times = hourly_raw.get("time", [])
        hourly_temps = hourly_raw.get("temperature_2m", [])
        hourly_hums = hourly_raw.get("relativehumidity_2m", [])
        hourly_rains = hourly_raw.get("precipitation", [])
        hourly_probs = hourly_raw.get("precipitation_probability", [])
        hourly_codes = hourly_raw.get("weathercode", [])
        hourly_winds = hourly_raw.get("windspeed_10m", [])
        hourly_direct_rad = hourly_raw.get("direct_radiation", [])
        hourly_diffuse_rad = hourly_raw.get("diffuse_radiation", [])
        hourly_is_day = hourly_raw.get("is_day", [])
        hourly_apparent = hourly_raw.get("apparent_temperature", [])
        hourly_gusts = hourly_raw.get("windgusts_10m", [])
        hourly_wind_dir = hourly_raw.get("winddirection_10m", [])
        hourly_clouds = hourly_raw.get("cloudcover", [])
        hourly_rains_max = hourly_raw.get("precipitation_max", [])
        hourly_rains_min = hourly_raw.get("precipitation_min", [])

        hours_list: List[Dict[str, Any]] = []
        rain_24h_sum = 0.0
        for j, t_str in enumerate(hourly_times):
            try:
                t_dt = datetime.strptime(t_str, "%Y-%m-%dT%H:%M")
            except (TypeError, ValueError):
                continue
            diff_hours = (t_dt - window_start).total_seconds() / 3600.0
            if not (0.0 <= diff_hours <= 48.0):
                continue

            code = _val(hourly_codes, j)
            prob_pct = int(_val(hourly_probs, j) or 0)
            rain_mm = _rounded(hourly_rains, j, 1, 0.0)

            # Open-Meteo: la pioggia delle HH:00 è l'accumulo dell'ora PRECEDENTE.
            if (t_dt - now_dt).total_seconds() > 0 and diff_hours <= 24.0:
                rain_24h_sum += rain_mm

            if code in DOWNGRADABLE_RAIN_CODES and prob_pct < 20 and rain_mm < 0.2:
                code = 2

            w_info = self.get_wmo_info(code)
            is_day_val = _val(hourly_is_day, j)
            is_day = True if is_day_val is None else bool(is_day_val)
            icon = w_info["icon"]
            if not is_day and code in NIGHT_ICON_OVERRIDES:
                icon = NIGHT_ICON_OVERRIDES[code]

            dir_r = _val(hourly_direct_rad, j) or 0.0
            dif_r = _val(hourly_diffuse_rad, j) or 0.0
            hum = _val(hourly_hums, j)
            clouds = _val(hourly_clouds, j)
            wind_dir = _val(hourly_wind_dir, j)
            rain_mm_max = _rounded(hourly_rains_max, j, 1, rain_mm)
            rain_mm_min = _rounded(hourly_rains_min, j, 1, rain_mm)

            hours_list.append({
                "iso_time": t_str,
                "hour_label": t_dt.strftime("%H:%M"),
                # Inizio del periodo a cui si riferiscono pioggia e probabilità
                "rain_period_start_label": (t_dt - timedelta(hours=1)).strftime("%H:%M"),
                "day_short": ITALIAN_DAYS.get(t_dt.weekday(), "")[:3],
                "temp_c": _rounded(hourly_temps, j, 1),
                "humidity": round(hum) if hum is not None else None,
                "rain_mm": rain_mm,
                "rain_mm_max": rain_mm_max,
                "rain_label": rain_intensity_label(rain_mm),
                "rain_prob_pct": prob_pct,
                # I modelli divergono: uno vede pioggia, un altro (quasi) niente
                "models_disagree": rain_mm_max >= 0.5 and rain_mm_min < 0.1,
                "apparent_temp_c": _rounded(hourly_apparent, j, 1),
                "cloudcover_pct": round(clouds) if clouds is not None else None,
                "wind_kmh": _rounded(hourly_winds, j, 1, 0.0),
                "wind_gust_kmh": _rounded(hourly_gusts, j, 1),
                "wind_dir_deg": round(wind_dir) if wind_dir is not None else None,
                "solar_irradiance_w_m2": round(dir_r + dif_r, 1),
                "weather_code": code,
                "is_day": is_day,
                "icon": icon,
                "condition": w_info["text"]
            })

        age_s = max(0.0, time.time() - self._last_success_time) if self._last_success_time else None
        fetched_at = (
            datetime.fromtimestamp(self._last_success_time, settings.get_tz()).strftime("%Y-%m-%d %H:%M:%S")
            if self._last_success_time else None
        )

        return {
            "source": f"Open-Meteo ({', '.join(MODEL_LABELS.get(m, m) for m in self._models())})",
            "updated_at": fetched_at or settings.now_local().strftime("%Y-%m-%d %H:%M:%S"),
            "fetched_at": fetched_at,
            "is_stale": age_s is not None and age_s > STALE_FORECAST_SECONDS,
            "daily": days_list,
            # Nome storico: contiene le prossime 48 ore a partire dall'ora corrente.
            "hourly_next_36h": hours_list,
            "rain_24h_sum": round(rain_24h_sum, 1),
        }

    @staticmethod
    def _reading_is_fresh(reading: Dict[str, Any], max_age_s: int = 900) -> bool:
        ts = reading.get("timestamp")
        if not ts:
            return False
        try:
            last_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - last_dt).total_seconds() <= max_age_s
        except (TypeError, ValueError):
            return False

    def apply_station_observation(self, forecast: Optional[Dict[str, Any]],
                                  reading: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Affina la previsione oraria con i dati reali della stazione (se recenti):
        - casella "Ora": temperatura, umidità e pioggia misurate al posto di quelle del modello;
        - pioggia in corso: 100% anche sull'ora il cui periodo contiene "adesso";
        - temperatura delle ore successive corretta con lo scarto stazione-modello misurato
          ora, che si attenua col passare delle ore (dimezzato dopo ~4 ore).
        """
        if not forecast or not reading or not self._reading_is_fresh(reading):
            return forecast
        hours = forecast.get("hourly_next_36h") or []
        if not hours:
            return forecast

        now_dt = settings.now_local().replace(tzinfo=None)
        rate = reading.get("rain_rate_mm_hr") or 0.0
        raining = rate > 0.2

        # --- Correzione locale temperatura (bias stazione - modello) ---
        station_t = reading.get("temp_c")
        model_now = self._model_temp_at(hours, now_dt)
        bias = None
        if station_t is not None and model_now is not None:
            bias = max(-TEMP_BIAS_MAX_C, min(TEMP_BIAS_MAX_C, station_t - model_now))
            forecast["temp_bias_c"] = round(bias, 1)
            for h in hours[1:]:
                try:
                    lead_h = (datetime.strptime(h["iso_time"], "%Y-%m-%dT%H:%M") - now_dt).total_seconds() / 3600.0
                except (KeyError, ValueError):
                    continue
                corr = bias * math.exp(-max(0.0, lead_h) / TEMP_BIAS_DECAY_H)
                if abs(corr) < 0.05:
                    continue
                for key in ("temp_c", "apparent_temp_c"):
                    if h.get(key) is not None:
                        h[f"{key}_model"] = h[key]
                        h[key] = round(h[key] + corr, 1)
                h["temp_corrected"] = True

        # --- Casella "Ora": valori misurati ---
        now_h = hours[0]
        now_h["observed"] = True
        if station_t is not None:
            now_h["temp_c_model"] = now_h.get("temp_c")
            now_h["temp_c"] = round(station_t, 1)
        if reading.get("humidity") is not None:
            now_h["humidity"] = round(reading["humidity"])
        if reading.get("apparent_temp_c") is not None:
            now_h["apparent_temp_c"] = round(reading["apparent_temp_c"], 1)

        if raining:
            code = 82 if rate >= 15.0 else (65 if rate >= 4.0 else 61)
            w_info = self.get_wmo_info(code)
            targets = [now_h]
            # Anche l'ora il cui periodo di accumulo contiene "adesso" (HH:00 successivo)
            for h in hours[1:3]:
                try:
                    if datetime.strptime(h["iso_time"], "%Y-%m-%dT%H:%M") > now_dt:
                        targets.append(h)
                        break
                except (KeyError, ValueError):
                    continue
            for h in targets:
                h["rain_prob_pct"] = 100
                h["rain_mm"] = max(h.get("rain_mm") or 0.0, round(rate, 1))
                h["weather_code"] = code
                h["icon"] = w_info["icon"]
                h["condition"] = f"{w_info['text']} in corso (stazione)"
                h["observed_rain"] = True
                h["rain_label"] = rain_intensity_label(rate)
        else:
            # Adesso non piove: la casella "Ora" lo dice, le ore successive restano previsione.
            now_h["rain_prob_pct"] = 0
            now_h["rain_mm"] = 0.0
            now_h["observed_dry"] = True
            now_h["rain_label"] = "asciutto"
            if now_h.get("weather_code") is not None and now_h["weather_code"] >= 51:
                clouds = now_h.get("cloudcover_pct")
                code = 3 if clouds is None or clouds >= 85 else (2 if clouds >= 40 else 1)
                w_info = self.get_wmo_info(code)
                now_h["weather_code"] = code
                now_h["icon"] = NIGHT_ICON_OVERRIDES.get(code, w_info["icon"]) if not now_h.get("is_day", True) else w_info["icon"]
                now_h["condition"] = f"{w_info['text']}, asciutto (stazione)"
        return forecast

    @staticmethod
    def _model_temp_at(hours: List[Dict[str, Any]], at_dt: datetime) -> Optional[float]:
        """Temperatura del modello interpolata linearmente all'istante at_dt."""
        pts = []
        for h in hours[:3]:
            try:
                pts.append((datetime.strptime(h["iso_time"], "%Y-%m-%dT%H:%M"), h.get("temp_c")))
            except (KeyError, ValueError):
                continue
        for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
            if v0 is None or v1 is None:
                continue
            if t0 <= at_dt <= t1:
                frac = (at_dt - t0).total_seconds() / max(1.0, (t1 - t0).total_seconds())
                return v0 + (v1 - v0) * frac
        return pts[0][1] if pts else None

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
                self._last_aqi_fetch = now - self.cache_ttl + 300
        except Exception as e:
            logger.error(f"Eccezione durante richiesta qualità dell'aria: {e}")
            self._last_aqi_fetch = now - self.cache_ttl + 300

        if self._cached_aqi:
            return self._cached_aqi

        return self._get_fallback_air_quality()

    def _process_air_quality_payload(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Elabora e struttura i dati di inquinanti e pollini per l'Hub."""
        curr = raw.get("current", {})
        
        # Open-Meteo restituisce l'indice europeo su scala continua (0-20 buona, 20-40 discreta,
        # 40-60 moderata, 60-80 scadente, 80-100 molto scadente, >100 estremamente scadente):
        # lo si converte nelle 5 classi usate dall'app.
        eaqi_index = curr.get("european_aqi")
        eaqi_val = self._eaqi_class(eaqi_index)

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
                "index": round(eaqi_index) if eaqi_index is not None else None,
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

    @staticmethod
    def _eaqi_class(index: Optional[float]) -> int:
        if index is None or index <= 20:
            return 1
        if index <= 40:
            return 2
        if index <= 60:
            return 3
        if index <= 80:
            return 4
        return 5

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

    def build_rain_nowcasting_summary(self, current_reading: Optional[Dict[str, Any]], lightning_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Algoritmo di nowcasting pioggia a 0-6 ore che combina:
        - Telemetria live della stazione (pioggia in corso, rain rate, trend barometrico)
        - Rilevatore fulmini WH57 (celle temporalesche attive o in avvicinamento)
        - Previsioni orarie ad alta risoluzione Open-Meteo (prossime 6 ore)
        - Calcolo tempi di arrivo stimati pioggia / rovesci.
        """
        current_rain_rate = current_reading.get("rain_rate_mm_hr", 0.0) if current_reading else 0.0

        if lightning_info is None and current_reading:
            try:
                from backend.analytics import analyze_lightning_activity
                lightning_info = analyze_lightning_activity(current_reading)
            except Exception:
                lightning_info = None

        forecast = self.fetch_open_meteo()
        hourly = forecast.get("hourly_next_36h", []) if forecast else []

        now_dt = settings.now_local().replace(tzinfo=None)

        max_prob_6h = 0
        total_rain_6h = 0.0
        first_rain_hour: Optional[Dict[str, Any]] = None
        peak_hour: Optional[Dict[str, Any]] = None

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
                    if prob >= 30 and (peak_hour is None or r_mm > peak_hour.get("rain_mm", 0.0)):
                        peak_hour = h
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

        # Controllo cella temporalesca attiva o in avvicinamento dal sensore fulmini WH57
        if lightning_info and (lightning_info.get("is_storm_active") or lightning_info.get("trend") == "approaching"):
            l_dist = lightning_info.get("current_distance_km")
            l_trend_lbl = lightning_info.get("trend_label", "In avvicinamento")
            l_threat = lightning_info.get("threat_level", "warning")
            l_desc = lightning_info.get("trend_desc") or f"Scariche attive a {l_dist} km dalla stazione."
            dist_txt = f"a {l_dist} km" if l_dist is not None else "nelle vicinanze"

            return {
                "active_rain": False,
                "headline": f"⛈️ Cella temporalesca {dist_txt} ({l_trend_lbl})!",
                "desc": f"{l_desc} Possibili rovesci improvvisi e forti raffiche.",
                "icon": "⛈️",
                "status_class": "danger" if l_threat in ("critical", "warning") else "warning",
                "prob_next_6h": max(85, max_prob_6h),
                "rain_sum_next_6h": max(total_rain_6h, 1.5),
                "radar_link": "/radar"
            }


        if first_rain_hour is not None:
            try:
                first_dt = datetime.strptime(first_rain_hour["iso_time"], "%Y-%m-%dT%H:%M")
                # La pioggia delle HH:00 cade nell'ora precedente: l'inizio è HH-1:00.
                start_dt = first_dt - timedelta(hours=1)
                min_until = int((start_dt - now_dt).total_seconds() / 60.0)
                if min_until <= 0:
                    when_str = "entro un'ora"
                elif min_until >= 60:
                    when_str = f"tra circa {format_duration_italian(min_until)}"
                else:
                    when_str = f"tra circa {max(5, min_until - 15)}-{min_until + 15} minuti"
                period_str = f"tra le {start_dt.strftime('%H:%M')} e le {first_rain_hour['hour_label']}"

                if first_rain_hour.get("weather_code") in (95, 96, 99, 82):
                    headline = f"⛈️ Temporale / Cella in avvicinamento ({when_str})"
                    desc = f"Attività convettiva o rovesci previsti {period_str} (probabilità {first_rain_hour['rain_prob_pct']}%)."
                    status_class = "danger"
                    icon = "⛈️"
                else:
                    label = rain_intensity_label(first_rain_hour["rain_mm"])
                    headline = f"🌧️ {label.capitalize()} prevista {when_str}"
                    desc = f"Inizio stimato {period_str}: circa {first_rain_hour['rain_mm']} mm (probabilità {first_rain_hour['rain_prob_pct']}%)."
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

        if max_prob_6h >= 30 and total_rain_6h > 0.1 and peak_hour is not None:
            label = rain_intensity_label(peak_hour.get("rain_mm"))
            if label == "asciutto":
                label = "qualche goccia"
            headline = f"🌦️ Possibile {label} nelle prossime ore"
            desc = (f"Al massimo {peak_hour.get('rain_mm', 0.0)} mm tra le {peak_hour.get('rain_period_start_label', '')} "
                    f"e le {peak_hour.get('hour_label', '')}, in tutto ~{round(total_rain_6h, 1)} mm in 6 ore "
                    f"(probabilità fino al {max_prob_6h}%)"
                    + (": niente di significativo." if total_rain_6h < 1.0 else "."))
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
            accuracy_desc = f"Stazione ({station_temp}°C) in ottimo accordo col modello ({model_temp}°C, scarto {sign}{delta_t}°C)."
        elif abs(delta_t) <= 2.0:
            accuracy_status = "Buon accordo col modello"
            badge_class = "badge-info"
            accuracy_desc = f"Stazione ({station_temp}°C) vs Modello ({model_temp}°C, scarto {sign}{delta_t}°C)."
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
