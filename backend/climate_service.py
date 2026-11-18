"""
Medie climatiche del periodo (1991–2020) per la posizione della stazione.

Fonte: archivio storico Open-Meteo (rianalisi ERA5), scaricato una volta sola e salvato su disco.
Per ogni giorno dell'anno calcola la media di massime, minime e pioggia (finestra di ±7 giorni
per smussare), poi confronta le misure della stazione con questi valori normali.
"""
import json
import logging
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from backend.config import settings

logger = logging.getLogger(__name__)

NORMALS_PERIOD = (1991, 2020)
SMOOTH_DAYS = 7
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
MONTHS_IT = ["", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
             "agosto", "settembre", "ottobre", "novembre", "dicembre"]


def _doy(d: date) -> int:
    """Giorno dell'anno 1–365 (il 29 febbraio vale come il 28)."""
    if d.month == 2 and d.day == 29:
        d = d.replace(day=28)
    return d.replace(year=2001).timetuple().tm_yday


def compute_normals(daily: Dict[str, List[Any]]) -> Dict[str, Any]:
    """Medie per giorno dell'anno da una serie giornaliera pluriennale."""
    sums = {k: [0.0] * 366 for k in ("tmax", "tmin", "rain")}
    counts = {k: [0] * 366 for k in sums}
    month_rain: Dict[int, Dict[int, float]] = {}
    keys = {"tmax": "temperature_2m_max", "tmin": "temperature_2m_min", "rain": "precipitation_sum"}
    for i, t in enumerate(daily.get("time", [])):
        d = date.fromisoformat(t)
        idx = _doy(d)
        for k, src in keys.items():
            v = (daily.get(src) or [None])[i] if i < len(daily.get(src) or []) else None
            if v is not None:
                sums[k][idx] += float(v)
                counts[k][idx] += 1
        r = (daily.get("precipitation_sum") or [])[i] if i < len(daily.get("precipitation_sum") or []) else None
        if r is not None:
            month_rain.setdefault(d.year, {}).setdefault(d.month, 0.0)
            month_rain[d.year][d.month] += float(r)

    raw = {k: [(sums[k][j] / counts[k][j]) if counts[k][j] else None for j in range(366)] for k in sums}

    def smooth(series: List[Optional[float]]) -> List[Optional[float]]:
        out: List[Optional[float]] = [None] * 366
        for j in range(1, 366):
            vals = []
            for off in range(-SMOOTH_DAYS, SMOOTH_DAYS + 1):
                jj = (j - 1 + off) % 365 + 1
                if series[jj] is not None:
                    vals.append(series[jj])
            out[j] = round(sum(vals) / len(vals), 2) if vals else None
        return out

    tmax, tmin = smooth(raw["tmax"]), smooth(raw["tmin"])
    rain_day = [round(v, 3) if v is not None else None for v in raw["rain"]]  # pioggia: media del giorno, non smussata
    years = [y for y in month_rain if len(month_rain[y]) == 12]
    monthly = {m: round(sum(month_rain[y][m] for y in years) / len(years), 1) for m in range(1, 13)} if years else {}
    return {
        "period": f"{NORMALS_PERIOD[0]}–{NORMALS_PERIOD[1]}",
        "tmax": tmax, "tmin": tmin, "rain_day": rain_day,
        "rain_month": monthly,
        "rain_year": round(sum(monthly.values()), 0) if monthly else None,
    }


class ClimateService:
    def __init__(self):
        self._normals: Optional[Dict[str, Any]] = None
        self._lock = threading.Lock()
        self._loading = False
        self._last_attempt = 0.0

    @property
    def _cache_file(self) -> str:
        return os.path.join(settings.DATA_DIR, "climate_normals.json")

    def _key(self) -> str:
        return f"{round(settings.LATITUDE, 3)},{round(settings.LONGITUDE, 3)},{NORMALS_PERIOD[0]}-{NORMALS_PERIOD[1]}"

    def get_normals(self, wait: bool = False) -> Optional[Dict[str, Any]]:
        """Medie dal disco; se mancano le scarica in background (o subito con wait=True)."""
        if self._normals is not None:
            return self._normals
        try:
            with open(self._cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("key") == self._key():
                data["rain_month"] = {int(k): v for k, v in (data.get("rain_month") or {}).items()}
                self._normals = data
                return data
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"Medie climatiche su disco non leggibili: {e}")
        if wait:
            self._download()
        elif not self._loading and time.time() - self._last_attempt > 1800:
            threading.Thread(target=self._download, daemon=True).start()
        return self._normals

    def _download(self) -> None:
        with self._lock:
            if self._normals is not None:
                return
            self._loading = True
            self._last_attempt = time.time()
            try:
                logger.info("Scaricamento medie climatiche 1991–2020 (archivio Open-Meteo)...")
                resp = requests.get(ARCHIVE_URL, params={
                    "latitude": settings.LATITUDE, "longitude": settings.LONGITUDE, "elevation": settings.ELEVATION,
                    "start_date": f"{NORMALS_PERIOD[0]}-01-01", "end_date": f"{NORMALS_PERIOD[1]}-12-31",
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum", "timezone": settings.TIMEZONE,
                }, timeout=120, headers={"User-Agent": "WeatherHub/1.0"})
                resp.raise_for_status()
                normals = compute_normals(resp.json().get("daily") or {})
                normals["key"] = self._key()
                normals["source"] = "Open-Meteo, archivio ERA5"
                os.makedirs(settings.DATA_DIR, exist_ok=True)
                with open(self._cache_file, "w", encoding="utf-8") as f:
                    json.dump(normals, f)
                self._normals = normals
                logger.info(f"Medie climatiche pronte: pioggia media annua {normals.get('rain_year')} mm")
            except Exception as e:
                logger.error(f"Medie climatiche non scaricate: {e}")
            finally:
                self._loading = False

    # ------------------------------------------------------------------ confronto
    def normal_for(self, d: date) -> Optional[Dict[str, Any]]:
        n = self.get_normals()
        if not n:
            return None
        j = _doy(d)
        return {"tmax": n["tmax"][j], "tmin": n["tmin"][j]}

    def build_comparison(self, today_extremes: Dict[str, Any], forecast_today: Optional[Dict[str, Any]],
                         month_days: List[Dict[str, Any]], rain_month_mm: Optional[float],
                         rain_year_mm: Optional[float], data_since: Optional[date],
                         now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        """
        Confronta oggi, il mese e l'anno con le medie 1991–2020.
        month_days: [{"day": "YYYY-MM-DD", "max_t": .., "min_t": ..}] misurati dalla stazione nel mese.
        """
        n = self.get_normals()
        if not n:
            return None
        now = now or settings.now_local()
        today = now.date()
        j = _doy(today)
        out: Dict[str, Any] = {"period": n.get("period"), "source": n.get("source"),
                               "month_name": MONTHS_IT[today.month]}

        # Oggi: la massima misurata finora o, se più alta, quella prevista; la minima dopo le 9 è quella vera
        meas_max = today_extremes.get("temp_max")
        fc_max = (forecast_today or {}).get("temp_max")
        day_max = max(v for v in (meas_max, fc_max) if v is not None) if (meas_max is not None or fc_max is not None) else None
        meas_min = today_extremes.get("temp_min")
        day_min = meas_min if (meas_min is not None and now.hour >= 9) else ((forecast_today or {}).get("temp_min") or meas_min)
        out["today"] = {
            "max": _r(day_max), "min": _r(day_min),
            "max_is_forecast": meas_max is None or (fc_max is not None and fc_max > meas_max and now.hour < 16),
            "min_is_forecast": day_min is not None and day_min != meas_min,
            "normal_max": _r(n["tmax"][j]), "normal_min": _r(n["tmin"][j]),
            "diff_max": _r(day_max - n["tmax"][j]) if day_max is not None and n["tmax"][j] is not None else None,
            "diff_min": _r(day_min - n["tmin"][j]) if day_min is not None and n["tmin"][j] is not None else None,
        }

        # Mese finora: media degli scarti di massime e minime dei giorni completi misurati
        diffs = []
        for row in month_days:
            try:
                d = date.fromisoformat(row["day"])
            except Exception:
                continue
            if d >= today or row.get("max_t") is None or row.get("min_t") is None:
                continue
            jj = _doy(d)
            if n["tmax"][jj] is None or n["tmin"][jj] is None:
                continue
            diffs.append(((row["max_t"] - n["tmax"][jj]) + (row["min_t"] - n["tmin"][jj])) / 2)
        out["month_temp"] = {"diff": _r(sum(diffs) / len(diffs)) if diffs else None, "days": len(diffs)}

        # Pioggia: mese e anno rispetto alla media fino a oggi
        def rain_normal(start: date, end: date) -> float:
            tot, d = 0.0, start
            while d <= end:
                tot += n["rain_day"][_doy(d)] or 0.0
                d += timedelta(days=1)
            return round(tot, 1)

        month_start = today.replace(day=1)
        month_full = n.get("rain_month", {}).get(today.month)
        if rain_month_mm is not None and data_since is not None and data_since <= month_start + timedelta(days=1):
            norm_to_date = rain_normal(month_start, today)
            out["rain_month"] = {"mm": _r(rain_month_mm), "normal_to_date": norm_to_date, "normal_full": month_full,
                                 "pct": round(100 * rain_month_mm / norm_to_date) if norm_to_date >= 1 else None}
        year_start = today.replace(month=1, day=1)
        if rain_year_mm is not None and data_since is not None and data_since <= year_start + timedelta(days=3):
            norm_to_date = rain_normal(year_start, today)
            out["rain_year"] = {"mm": _r(rain_year_mm), "normal_to_date": norm_to_date, "normal_full": n.get("rain_year"),
                                "pct": round(100 * rain_year_mm / norm_to_date) if norm_to_date >= 1 else None}
        out["headline"] = _headline(out)
        return out


def _r(v: Optional[float], digits: int = 1) -> Optional[float]:
    return round(float(v), digits) if v is not None else None


def _fmt(v: float) -> str:
    return f"{v:+.1f}".replace(".", ",")


def _headline(c: Dict[str, Any]) -> str:
    t = c.get("today") or {}
    d = t.get("diff_max")
    if d is None:
        return "Medie del periodo pronte"
    if abs(d) < 1:
        return f"Oggi nella media del periodo (massima {_fmt(d)}°)"
    word = "più caldo" if d > 0 else "più fresco"
    return f"Oggi {_fmt(d)}° rispetto alla media: {word} del solito"


climate_service = ClimateService()


def station_month_days() -> List[Dict[str, Any]]:
    """Massima e minima misurate per ogni giorno del mese in corso."""
    from backend.database import get_connection
    tz = settings.get_tz()
    now = settings.now_local()
    start_utc = datetime(now.year, now.month, 1, tzinfo=tz).astimezone(timezone.utc).isoformat()
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT local_date(timestamp) AS day, MAX(temp_c) AS max_t, MIN(temp_c) AS min_t, COUNT(*) AS n
            FROM weather_records WHERE timestamp >= ? AND temp_c IS NOT NULL
            GROUP BY local_date(timestamp)
        """, (start_utc,)).fetchall()
        # Un giorno con pochissime letture (stazione spenta) falserebbe la media
        return [{"day": r["day"], "max_t": r["max_t"], "min_t": r["min_t"]} for r in rows if r["n"] >= 48]
    finally:
        conn.close()


def station_data_since() -> Optional[date]:
    """Primo giorno con dati della stazione (per sapere se il totale dell'anno è completo)."""
    from backend.database import get_connection
    conn = get_connection()
    try:
        row = conn.execute("SELECT MIN(timestamp) AS ts FROM weather_records").fetchone()
        ts = row["ts"] if row else None
        if not ts:
            return None
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(settings.get_tz()).date()
    except Exception:
        return None
    finally:
        conn.close()
