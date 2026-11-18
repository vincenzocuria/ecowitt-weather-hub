"""
Affidabilità delle previsioni dagli "ensemble" di Open-Meteo.

Ogni modello viene fatto girare molte volte con condizioni iniziali leggermente diverse
(ICON 40 scenari, ECMWF 51). Se gli scenari concordano la previsione è sicura; se si dividono
(metà vede pioggia, metà no) è incerta. Per ogni giorno: probabilità di pioggia (scenari con
almeno 1 mm), forbice di massime e minime, giudizio sintetico.
"""
import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

import requests

from backend.config import settings

logger = logging.getLogger(__name__)

ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
ENSEMBLE_MODELS = ["icon_seamless", "ecmwf_ifs025"]
DAILY = ["temperature_2m_max", "temperature_2m_min", "precipitation_sum"]
CACHE_TTL = 3 * 3600
RAIN_DAY_MM = 1.0


def _percentile(vals: List[float], p: float) -> Optional[float]:
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def summarize_day(tmax: List[float], tmin: List[float], rain: List[float]) -> Optional[Dict[str, Any]]:
    """Giudizio di affidabilità di un giorno dagli scenari."""
    if len(rain) < 10 or len(tmax) < 10:
        return None
    rain_pct = round(100 * sum(1 for r in rain if r >= RAIN_DAY_MM) / len(rain))
    tmax_lo, tmax_hi = _percentile(tmax, 0.1), _percentile(tmax, 0.9)
    tmin_lo, tmin_hi = (_percentile(tmin, 0.1), _percentile(tmin, 0.9)) if tmin else (None, None)
    spread = tmax_hi - tmax_lo
    heavy = round(100 * sum(1 for r in rain if r >= 10) / len(rain))

    if rain_pct >= 80:
        rain_text = "Pioggia quasi certa"
    elif rain_pct >= 55:
        rain_text = "Pioggia probabile"
    elif rain_pct >= 30:
        rain_text = "Pioggia possibile: i modelli sono divisi"
    elif rain_pct >= 10:
        rain_text = "Poche possibilità di pioggia"
    else:
        rain_text = "Asciutto quasi certo"

    rain_split = 30 <= rain_pct <= 70
    if rain_split or spread > 6:
        level, label = "bassa", "Incerta"
    elif (20 < rain_pct < 80) or spread > 3:
        level, label = "media", "Abbastanza sicura"
    else:
        level, label = "alta", "Sicura"

    return {
        "level": level, "label": label, "members": len(rain),
        "rain_pct": rain_pct, "heavy_rain_pct": heavy, "rain_text": rain_text,
        "tmax_low": round(tmax_lo), "tmax_high": round(tmax_hi),
        "tmin_low": round(tmin_lo) if tmin_lo is not None else None,
        "tmin_high": round(tmin_hi) if tmin_hi is not None else None,
        "rain_median_mm": round(_percentile(rain, 0.5), 1),
        "rain_high_mm": round(_percentile(rain, 0.9), 1),
    }


def summarize_payload(raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    daily = raw.get("daily") or {}
    times = daily.get("time") or []
    groups = {var: [k for k in daily if k.startswith(var + "_") or k == var] for var in DAILY}
    out: Dict[str, Dict[str, Any]] = {}
    for i, t in enumerate(times):
        def col(var: str) -> List[float]:
            return [float(daily[k][i]) for k in groups[var] if i < len(daily[k]) and daily[k][i] is not None]
        s = summarize_day(col("temperature_2m_max"), col("temperature_2m_min"), col("precipitation_sum"))
        if s:
            out[t] = s
    return out


class EnsembleService:
    def __init__(self):
        self._days: Dict[str, Dict[str, Any]] = {}
        self._fetched = 0.0
        self._attempt = 0.0
        self._loading = False
        self._loaded_disk = False

    @property
    def _cache_file(self) -> str:
        return os.path.join(settings.DATA_DIR, "ensemble_cache.json")

    def get_days(self) -> Dict[str, Dict[str, Any]]:
        """Giudizi per data (dalla cache); aggiorna in background quando scadono."""
        if not self._loaded_disk:
            self._loaded_disk = True
            try:
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._days, self._fetched = data.get("days") or {}, float(data.get("fetched") or 0)
            except FileNotFoundError:
                pass
            except Exception as e:
                logger.warning(f"Cache ensemble non leggibile: {e}")
        now = time.time()
        if now - self._fetched > CACHE_TTL and not self._loading and now - self._attempt > 600:
            self._loading = True
            self._attempt = now
            threading.Thread(target=self.refresh, daemon=True).start()
        return self._days

    def for_date(self, date_str: str) -> Optional[Dict[str, Any]]:
        return self.get_days().get(date_str)

    def refresh(self) -> None:
        try:
            resp = requests.get(ENSEMBLE_URL, params={
                "latitude": settings.LATITUDE, "longitude": settings.LONGITUDE, "elevation": settings.ELEVATION,
                "daily": ",".join(DAILY), "models": ",".join(ENSEMBLE_MODELS),
                "timezone": settings.TIMEZONE, "forecast_days": 7,
            }, timeout=30, headers={"User-Agent": "WeatherHub/1.0"})
            resp.raise_for_status()
            days = summarize_payload(resp.json())
            if days:
                self._days, self._fetched = days, time.time()
                os.makedirs(settings.DATA_DIR, exist_ok=True)
                with open(self._cache_file, "w", encoding="utf-8") as f:
                    json.dump({"days": days, "fetched": self._fetched}, f)
                logger.info(f"Affidabilità previsioni aggiornata ({len(days)} giorni)")
        except Exception as e:
            logger.error(f"Previsioni ensemble non scaricate: {e}")
        finally:
            self._loading = False


ensemble_service = EnsembleService()
