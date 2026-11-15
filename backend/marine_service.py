"""
Condizioni del mare davanti alla stazione (Open-Meteo Marine API).

Onde da DWD EWAM (griglia europea fine: punto a pochi km dalla costa), con il modello
marino standard come riserva oltre l'orizzonte di EWAM e per la temperatura dell'acqua.
Come per le previsioni meteo, in cache c'è il payload grezzo e l'elaborazione relativa
all'ora corrente viene rifatta a ogni lettura.
"""
import json
import logging
import math
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from backend.analytics import wind_name
from backend.config import settings
from backend.helpers import ITALIAN_SHORT_MONTHS, ITALIAN_WEEKDAYS

logger = logging.getLogger("weather_hub.marine")

PRIMARY_MODEL = "ewam"
FALLBACK_MODEL = "marine_best_match"   # suffisso con cui Open-Meteo restituisce best_match
HOURLY_VARS = [
    "wave_height", "wave_direction", "wave_period",
    "swell_wave_height", "swell_wave_direction", "swell_wave_period",
    "wind_wave_height", "sea_surface_temperature",
]

# Scala Douglas (stato del mare) per altezza significativa d'onda in metri
DOUGLAS = [
    (0.0, 0, "Calmo", "Superficie liscia come l'olio."),
    (0.1, 1, "Quasi calmo", "Increspature leggere."),
    (0.5, 2, "Poco mosso", "Onde piccole, creste che non si rompono."),
    (1.25, 3, "Mosso", "Onde moderate, qualche cresta bianca."),
    (2.5, 4, "Molto mosso", "Onde lunghe e frequenti creste bianche."),
    (4.0, 5, "Agitato", "Onde alte, spruzzi e schiuma diffusa."),
    (6.0, 6, "Molto agitato", "Mare grosso, navigazione pericolosa."),
    (9.0, 7, "Grosso", "Onde molto alte, mare impraticabile."),
    (14.0, 8, "Molto grosso", "Onde altissime."),
]


def douglas_state(wave_height_m: Optional[float]) -> Dict[str, Any]:
    """Stato del mare secondo la scala Douglas (le soglie sono i limiti superiori in metri)."""
    if wave_height_m is None:
        return {"grade": None, "label": "N/D", "desc": ""}
    h = max(0.0, float(wave_height_m))
    for limit, grade, label, desc in DOUGLAS:
        if h <= limit:
            return {"grade": grade, "label": label, "desc": desc}
    return {"grade": 9, "label": "Tempestoso", "desc": "Condizioni eccezionali."}


def sea_advice(wave_h: Optional[float], wind_kmh: Optional[float], gust_kmh: Optional[float],
               water_c: Optional[float]) -> Dict[str, str]:
    """Indicazione pratica per bagno e piccola barca, da onde e vento misurato dalla stazione."""
    wave = wave_h or 0.0
    wind = max(wind_kmh or 0.0, (gust_kmh or 0.0) * 0.7)
    if wave >= 1.25 or wind >= 39:
        boat = ("no", "Sconsigliato uscire con piccole imbarcazioni.")
    elif wave >= 0.5 or wind >= 20:
        boat = ("attenzione", "Uscita possibile solo con esperienza: mare mosso o vento teso.")
    else:
        boat = ("ok", "Condizioni favorevoli per una piccola barca.")

    if wave >= 1.0:
        swim = ("no", "Bagno sconsigliato: onde alte e possibili correnti.")
    elif water_c is not None and water_c < 17:
        swim = ("freddo", f"Acqua fredda ({water_c:.0f} °C): bagno solo per i più coraggiosi.")
    elif wave >= 0.5:
        swim = ("attenzione", "Bagno con prudenza: onda formata vicino a riva.")
    else:
        swim = ("ok", "Mare tranquillo per un bagno." if (water_c or 0) >= 20 else "Mare tranquillo, acqua fresca.")
    return {"boat_level": boat[0], "boat": boat[1], "swim_level": swim[0], "swim": swim[1]}


def _pick(hourly: Dict[str, List[Any]], var: str, i: int) -> Optional[float]:
    """Valore dal modello principale, altrimenti dalla riserva."""
    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        seq = hourly.get(f"{var}_{model}") or hourly.get(var) or []
        if i < len(seq) and seq[i] is not None:
            return seq[i]
    return None


class MarineService:
    def __init__(self, cache_ttl_seconds: int = 3600):
        self.cache_ttl = cache_ttl_seconds
        self._raw: Optional[Dict[str, Any]] = None
        self._last_fetch = 0.0
        self._last_success = 0.0
        self._cache_file = os.path.join(settings.DATA_DIR, "marine_cache.json")
        self._load_cache()

    def _load_cache(self) -> None:
        try:
            if os.path.exists(self._cache_file):
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data.get("raw"), dict):
                    self._raw = data["raw"]
                    self._last_fetch = self._last_success = data.get("fetched_at", 0.0)
        except Exception as e:
            logger.warning(f"Cache mare non leggibile: {e}")

    def _save_cache(self) -> None:
        try:
            os.makedirs(settings.DATA_DIR, exist_ok=True)
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump({"fetched_at": self._last_success, "raw": self._raw}, f)
        except Exception as e:
            logger.warning(f"Impossibile salvare la cache mare: {e}")

    def _download(self, now: float) -> None:
        lat, lon = settings.MARINE_LATITUDE, settings.MARINE_LONGITUDE
        url = (
            "https://marine-api.open-meteo.com/v1/marine"
            f"?latitude={lat}&longitude={lon}"
            f"&hourly={','.join(HOURLY_VARS)}"
            f"&models={PRIMARY_MODEL},best_match"
            "&forecast_days=4&timezone=auto"
        )
        try:
            resp = requests.get(url, timeout=8, headers={"User-Agent": "WeatherHub/1.0"})
            if resp.status_code == 200:
                self._raw = resp.json()
                self._last_fetch = self._last_success = now
                self._save_cache()
                logger.info("Dati mare aggiornati")
                return
            logger.error(f"Errore HTTP Marine API ({resp.status_code}): {resp.text[:200]}")
        except Exception as e:
            logger.error(f"Eccezione richiesta Marine API: {e}")
        self._last_fetch = now - self.cache_ttl + 300   # nuovo tentativo tra 5 minuti

    def fetch(self, force: bool = False, reading: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        if not settings.MARINE_ENABLED:
            return None
        now = time.time()
        if force or not self._raw or (now - self._last_fetch >= self.cache_ttl):
            self._download(now)
        if not self._raw:
            return None
        try:
            return self.process(self._raw, reading)
        except Exception as e:
            logger.error(f"Elaborazione dati mare fallita: {e}")
            return None

    def process(self, raw: Dict[str, Any], reading: Optional[Dict[str, Any]] = None,
                now_dt: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        hourly = raw.get("hourly") or {}
        times = hourly.get("time") or []
        now_dt = now_dt or settings.now_local().replace(tzinfo=None)
        window_start = now_dt.replace(minute=0, second=0, microsecond=0)

        hours: List[Dict[str, Any]] = []
        for i, t in enumerate(times):
            try:
                t_dt = datetime.strptime(t, "%Y-%m-%dT%H:%M")
            except (TypeError, ValueError):
                continue
            lead = (t_dt - window_start).total_seconds() / 3600.0
            if not (0 <= lead <= 72):
                continue
            wave = _pick(hourly, "wave_height", i)
            if wave is None:
                continue
            hours.append({
                "iso_time": t,
                "hour_label": t_dt.strftime("%H:%M"),
                "day_short": ITALIAN_WEEKDAYS.get(t_dt.weekday(), "")[:3],
                "wave_m": round(wave, 2),
                "wave_dir": _pick(hourly, "wave_direction", i),
                "wave_period_s": _pick(hourly, "wave_period", i),
                "swell_m": _pick(hourly, "swell_wave_height", i),
                "sst_c": _pick(hourly, "sea_surface_temperature", i),
            })
        if not hours:
            return None

        cur_i = times.index(hours[0]["iso_time"])
        wave = hours[0]["wave_m"]
        wave_dir = _pick(hourly, "wave_direction", cur_i)
        swell = _pick(hourly, "swell_wave_height", cur_i)
        swell_dir = _pick(hourly, "swell_wave_direction", cur_i)
        sst = next((h["sst_c"] for h in hours if h["sst_c"] is not None), None)

        # Riepilogo giornaliero (massimi) per i prossimi giorni
        days: Dict[str, Dict[str, Any]] = {}
        for h in hours:
            d = h["iso_time"][:10]
            day = days.setdefault(d, {"date": d, "wave_max": 0.0, "dirs": []})
            day["wave_max"] = max(day["wave_max"], h["wave_m"])
            if h["wave_dir"] is not None:
                day["dirs"].append(h["wave_dir"])
        today = now_dt.date()
        daily = []
        for d, day in days.items():
            d_obj = datetime.strptime(d, "%Y-%m-%d").date()
            delta = (d_obj - today).days
            label = "Oggi" if delta == 0 else ("Domani" if delta == 1 else ITALIAN_WEEKDAYS.get(d_obj.weekday(), d))
            dom_dir = None
            if day["dirs"]:
                sx = sum(math.sin(math.radians(x)) for x in day["dirs"])
                cx = sum(math.cos(math.radians(x)) for x in day["dirs"])
                dom_dir = round(math.degrees(math.atan2(sx, cx)) % 360)
            daily.append({
                "day": label,
                "date_label": f"{d_obj.day} {ITALIAN_SHORT_MONTHS.get(f'{d_obj.month:02d}', '')}",
                "wave_max": round(day["wave_max"], 2),
                "state": douglas_state(day["wave_max"]),
                "dir_name": wind_name(dom_dir)["name"] if dom_dir is not None else "--",
            })

        reading = reading or {}
        wind_kmh, gust_kmh = reading.get("wind_speed_kmh"), reading.get("wind_gust_kmh")
        peak = max(hours, key=lambda h: h["wave_m"])
        grid_lat, grid_lon = raw.get("latitude"), raw.get("longitude")
        dist_km = None
        if grid_lat is not None and grid_lon is not None:
            dist_km = round(math.hypot((grid_lat - settings.MARINE_LATITUDE) * 111.0,
                                       (grid_lon - settings.MARINE_LONGITUDE) * 111.0 * math.cos(math.radians(grid_lat))), 1)
        fetched = datetime.fromtimestamp(self._last_success, settings.get_tz()).strftime("%d/%m %H:%M") if self._last_success else None

        # Curva delle onde nelle prossime 72 ore per la card (viewBox 0 0 300 44)
        top = max(1.0, peak["wave_m"] * 1.15)
        n = max(1, len(hours) - 1)
        pts = [(round(i * 300.0 / n, 1), round(42.0 - h["wave_m"] / top * 38.0, 1)) for i, h in enumerate(hours)]
        spark_line = " ".join(("M" if i == 0 else "L") + f"{x},{y}" for i, (x, y) in enumerate(pts))
        spark_area = spark_line + f" L300,44 L0,44 Z"

        return {
            "name": f"Mare di {settings.LOCATION_NAME}" if settings.LOCATION_NAME else "Mare",
            "spark_line": spark_line,
            "spark_area": spark_area,
            "current": {
                "wave_m": wave,
                "wave_dir": wave_dir,
                "wave_from": wind_name(wave_dir)["name"] if wave_dir is not None else "--",
                "wave_period_s": hours[0]["wave_period_s"],
                "swell_m": round(swell, 2) if swell is not None else None,
                "swell_from": wind_name(swell_dir)["name"] if swell_dir is not None else "--",
                "sst_c": round(sst, 1) if sst is not None else None,
                "state": douglas_state(wave),
            },
            "advice": sea_advice(wave, wind_kmh, gust_kmh, sst),
            "station_wind": wind_name(reading.get("wind_dir_deg"), wind_kmh) if reading else None,
            "peak": {"wave_m": peak["wave_m"], "when": f"{peak['day_short']} {peak['hour_label']}", "state": douglas_state(peak["wave_m"])},
            "hourly": hours,
            "daily": daily[:4],
            "source": "Open-Meteo Marine • DWD EWAM",
            "grid_distance_km": dist_km,
            "fetched_at": fetched,
        }


marine_service = MarineService()
