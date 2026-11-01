from __future__ import annotations
import os
import json
import time
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Tuple
import requests

from backend.config import settings

logger = logging.getLogger("weather_hub.civil_protection")

# Mappatura Codici Colore & Severità
ALERT_SEVERITY = {
    "VERDE": 0,
    "GIALLA": 1,
    "ARANCIONE": 2,
    "ROSSA": 3
}

ALERT_META = {
    "VERDE": {
        "color": "#10b981",
        "bg_class": "bg-emerald-950/40 border-emerald-500/30 text-emerald-300",
        "badge_class": "badge-success",
        "label": "Verde - Nessuna Allerta",
        "icon": "🟢",
        "short": "Nessuna Allerta"
    },
    "GIALLA": {
        "color": "#eab308",
        "bg_class": "bg-amber-950/40 border-amber-500/40 text-amber-300",
        "badge_class": "badge-warning",
        "label": "Gialla - Ordinaria Criticità",
        "icon": "🟡",
        "short": "Allerta Gialla"
    },
    "ARANCIONE": {
        "color": "#f97316",
        "bg_class": "bg-orange-950/40 border-orange-500/40 text-orange-300",
        "badge_class": "badge-orange",
        "label": "Arancione - Moderata Criticità",
        "icon": "🟠",
        "short": "Allerta Arancione"
    },
    "ROSSA": {
        "color": "#ef4444",
        "bg_class": "bg-red-950/50 border-red-500/50 text-red-300",
        "badge_class": "badge-danger",
        "label": "Rossa - Elevata Criticità",
        "icon": "🔴",
        "short": "Allerta Rossa"
    }
}


def _point_in_polygon(x: float, y: float, poly: List[List[float]]) -> bool:
    """Ray casting algorithm per determinare se (lon, lat) è dentro poly."""
    n = len(poly)
    inside = False
    if n < 3:
        return False
    p1x, p1y = poly[0]
    for i in range(n + 1):
        p2x, p2y = poly[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


def _point_in_geometry(lon: float, lat: float, geometry: Dict[str, Any]) -> bool:
    """Verifica se il punto (lon, lat) ricade nella geometria GeoJSON (Polygon o MultiPolygon)."""
    gtype = geometry.get("type", "")
    coords = geometry.get("coordinates", [])
    if gtype == "Polygon":
        for ring in coords:
            if _point_in_polygon(lon, lat, ring):
                return True
    elif gtype == "MultiPolygon":
        for poly in coords:
            for ring in poly:
                if _point_in_polygon(lon, lat, ring):
                    return True
    return False


def _parse_alert_level(text: Optional[str]) -> str:
    """Estrae il livello di allerta normalizzato (VERDE, GIALLA, ARANCIONE, ROSSA) da una stringa DPC."""
    if not text:
        return "VERDE"
    t = text.upper()
    if "ROSSA" in t or "ELEVATA" in t:
        return "ROSSA"
    if "ARANCIONE" in t or "MODERATA" in t:
        return "ARANCIONE"
    if "GIALLA" in t or "ORDINARIA" in t:
        return "GIALLA"
    return "VERDE"


class CivilProtectionService:
    def __init__(self, cache_ttl_seconds: int = 3600):
        self.cache_ttl = cache_ttl_seconds
        self._cache_file = os.path.join(settings.DATA_DIR, "civil_protection_cache.json")
        self._cached_data: Optional[Dict[str, Any]] = None
        self._last_fetch_time: float = 0.0
        self._load_disk_cache()

    def _load_disk_cache(self):
        """Carica l'ultimo bollettino salvato su disco se presente."""
        if os.path.exists(self._cache_file):
            try:
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._cached_data = data.get("data")
                    self._last_fetch_time = data.get("fetched_at", 0.0)
                    logger.info("Caricata cache allerte Protezione Civile da disco")
            except Exception as e:
                logger.warning(f"Impossibile leggere civil_protection cache da disco: {e}")

    def _save_disk_cache(self, data: Dict[str, Any]):
        """Salva i dati su file cache locale persistente."""
        try:
            os.makedirs(os.path.dirname(self._cache_file), exist_ok=True)
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump({"data": data, "fetched_at": time.time()}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Impossibile salvare civil_protection cache su disco: {e}")

    def _get_latest_bulletin_info(self) -> Optional[Tuple[str, str, str]]:
        """
        Interroga l'API di GitHub per trovare l'ultimo bollettino disponibile.
        Restituisce (timestamp_str, today_geojson_url, tomorrow_geojson_url).
        """
        try:
            commits_url = "https://api.github.com/repos/pcm-dpc/DPC-Bollettini-Criticita-Idrogeologica-Idraulica/commits?per_page=5"
            headers = {"User-Agent": "EcowittWeatherHub/1.0", "Accept": "application/vnd.github.v3+json"}
            res = requests.get(commits_url, headers=headers, timeout=10)
            if res.status_code == 200:
                commits = res.json()
                for c in commits:
                    sha = c.get("sha")
                    if not sha:
                        continue
                    detail_res = requests.get(f"https://api.github.com/repos/pcm-dpc/DPC-Bollettini-Criticita-Idrogeologica-Idraulica/commits/{sha}", headers=headers, timeout=10)
                    if detail_res.status_code == 200:
                        files = detail_res.json().get("files", [])
                        for f in files:
                            fn = f.get("filename", "")
                            # Match files/geojson/YYYYMMDD_HHMM_today.json o files/preview/...
                            m = re.search(r"(\d{8}_\d{4})", fn)
                            if m:
                                ts_str = m.group(1)
                                today_url = f"https://raw.githubusercontent.com/pcm-dpc/DPC-Bollettini-Criticita-Idrogeologica-Idraulica/master/files/geojson/{ts_str}_today.json"
                                tomorrow_url = f"https://raw.githubusercontent.com/pcm-dpc/DPC-Bollettini-Criticita-Idrogeologica-Idraulica/master/files/geojson/{ts_str}_tomorrow.json"
                                return ts_str, today_url, tomorrow_url
        except Exception as e:
            logger.warning(f"Errore query API GitHub per bollettino DPC: {e}")

        # Fallback se GitHub API fallisce (ad es. per rate limit): cerca date recenti
        now = datetime.now()
        for delta_days in (0, 1, 2):
            test_date = (now - timedelta(days=delta_days)).strftime("%Y%m%d")
            for hour in ("1530", "1500", "1430", "1415", "1600", "1630", "1700"):
                ts_str = f"{test_date}_{hour}"
                today_url = f"https://raw.githubusercontent.com/pcm-dpc/DPC-Bollettini-Criticita-Idrogeologica-Idraulica/master/files/geojson/{ts_str}_today.json"
                try:
                    head_res = requests.head(today_url, timeout=5)
                    if head_res.status_code == 200:
                        tomorrow_url = f"https://raw.githubusercontent.com/pcm-dpc/DPC-Bollettini-Criticita-Idrogeologica-Idraulica/master/files/geojson/{ts_str}_tomorrow.json"
                        return ts_str, today_url, tomorrow_url
                except Exception:
                    pass
        return None

    def _find_zone_feature(self, geojson_data: Dict[str, Any], lat: float, lon: float, location_name: str, zone_override: str = "") -> Optional[Dict[str, Any]]:
        """Trova la feature corrispondente alla zona dell'utente."""
        features = geojson_data.get("features", [])
        if not features:
            return None

        # 1. Override manuale della zona se configurato
        if zone_override:
            zo_upper = zone_override.strip().upper()
            for f in features:
                props = f.get("properties", {})
                if zo_upper in props.get("Nome zona", "").upper() or zo_upper in props.get("Nome_Zona", "").upper():
                    return f

        # 2. Ricerca per nome del comune configurato
        if location_name:
            loc_clean = location_name.strip().lower()
            for f in features:
                comuni = f.get("properties", {}).get("Comuni", [])
                for com in comuni:
                    if loc_clean in com.lower() or com.lower() in loc_clean:
                        return f

        # 3. Ricerca per coordinate geografiche Point-in-Polygon
        for f in features:
            geom = f.get("geometry", {})
            if geom and _point_in_geometry(lon, lat, geom):
                return f

        return None

    def _extract_day_summary(self, feature: Optional[Dict[str, Any]], ts_str: str, day_type: str) -> Dict[str, Any]:
        """Estrae e normalizza le informazioni di rischio per oggi o domani."""
        if not feature:
            return {
                "level": "VERDE",
                "severity": 0,
                "label": ALERT_META["VERDE"]["label"],
                "short_label": ALERT_META["VERDE"]["short"],
                "color": ALERT_META["VERDE"]["color"],
                "badge_class": ALERT_META["VERDE"]["badge_class"],
                "bg_class": ALERT_META["VERDE"]["bg_class"],
                "icon": ALERT_META["VERDE"]["icon"],
                "overall_text": "Nessun dato disponibile o assenza di fenomeni",
                "risks": {
                    "temporali": {"level": "VERDE", "label": "Verde", "color": ALERT_META["VERDE"]["color"], "badge_class": ALERT_META["VERDE"]["badge_class"], "text": "Assenza di fenomeni significativi"},
                    "idrogeologico": {"level": "VERDE", "label": "Verde", "color": ALERT_META["VERDE"]["color"], "badge_class": ALERT_META["VERDE"]["badge_class"], "text": "Assenza di fenomeni significativi"},
                    "idraulico": {"level": "VERDE", "label": "Verde", "color": ALERT_META["VERDE"]["color"], "badge_class": ALERT_META["VERDE"]["badge_class"], "text": "Assenza di fenomeni significativi"}
                },
                "active_hazards": [],
                "preview_url": f"https://raw.githubusercontent.com/pcm-dpc/DPC-Bollettini-Criticita-Idrogeologica-Idraulica/master/files/preview/{ts_str}_{'oggi' if day_type == 'today' else 'domani'}.png" if ts_str else ""
            }

        props = feature.get("properties", {})
        overall_text = props.get("Rappresentata nella mappa", "")
        hydro_text = props.get("Per rischio idrogeologico", "")
        temp_text = props.get("Per rischio temporali", "")
        idr_text = props.get("Per rischio idraulico", "")

        lvl_overall = _parse_alert_level(overall_text)
        lvl_hydro = _parse_alert_level(hydro_text)
        lvl_temp = _parse_alert_level(temp_text)
        lvl_idr = _parse_alert_level(idr_text)

        # Il livello massimo effettivo è il massimo tra le componenti
        max_sev = max(
            ALERT_SEVERITY.get(lvl_overall, 0),
            ALERT_SEVERITY.get(lvl_hydro, 0),
            ALERT_SEVERITY.get(lvl_temp, 0),
            ALERT_SEVERITY.get(lvl_idr, 0)
        )

        effective_level = "VERDE"
        for lvl_name, sev in ALERT_SEVERITY.items():
            if sev == max_sev:
                effective_level = lvl_name
                break

        meta = ALERT_META.get(effective_level, ALERT_META["VERDE"])

        active_hazards = []
        if lvl_temp != "VERDE":
            active_hazards.append(f"Temporali ({lvl_temp.capitalize()})")
        if lvl_hydro != "VERDE":
            active_hazards.append(f"Rischio Idrogeologico ({lvl_hydro.capitalize()})")
        if lvl_idr != "VERDE":
            active_hazards.append(f"Rischio Idraulico ({lvl_idr.capitalize()})")

        preview_name = "oggi" if day_type == "today" else "domani"
        preview_url = f"https://raw.githubusercontent.com/pcm-dpc/DPC-Bollettini-Criticita-Idrogeologica-Idraulica/master/files/preview/{ts_str}_{preview_name}.png" if ts_str else ""

        return {
            "level": effective_level,
            "severity": max_sev,
            "label": meta["label"],
            "short_label": meta["short"],
            "color": meta["color"],
            "badge_class": meta["badge_class"],
            "bg_class": meta["bg_class"],
            "icon": meta["icon"],
            "overall_text": overall_text or "Nessuna Allerta",
            "risks": {
                "temporali": {
                    "level": lvl_temp,
                    "label": lvl_temp.capitalize(),
                    "color": ALERT_META[lvl_temp]["color"],
                    "badge_class": ALERT_META[lvl_temp]["badge_class"],
                    "text": temp_text or "Assenza di fenomeni significativi"
                },
                "idrogeologico": {
                    "level": lvl_hydro,
                    "label": lvl_hydro.capitalize(),
                    "color": ALERT_META[lvl_hydro]["color"],
                    "badge_class": ALERT_META[lvl_hydro]["badge_class"],
                    "text": hydro_text or "Assenza di fenomeni significativi"
                },
                "idraulico": {
                    "level": lvl_idr,
                    "label": lvl_idr.capitalize(),
                    "color": ALERT_META[lvl_idr]["color"],
                    "badge_class": ALERT_META[lvl_idr]["badge_class"],
                    "text": idr_text or "Assenza di fenomeni significativi"
                }
            },
            "active_hazards": active_hazards,
            "preview_url": preview_url
        }

    def fetch_alerts(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Recupera le allerte meteo per la posizione attuale."""
        if not settings.CIVIL_PROTECTION_ENABLED:
            return {"enabled": False, "status": "disabled"}

        now = time.time()
        if not force_refresh and self._cached_data and (now - self._last_fetch_time < self.cache_ttl):
            return self._cached_data

        logger.info("Scaricamento bollettino criticità Protezione Civile...")
        bulletin_info = self._get_latest_bulletin_info()
        if not bulletin_info:
            # Imposta un backoff di 10 minuti su errore per non martellare GitHub ad ogni polling di /api/live
            self._last_fetch_time = now - self.cache_ttl + 600
            if self._cached_data:
                logger.warning("Impossibile contattare DPC, restituisco dati da cache (backoff 10m)")
                return self._cached_data
            error_res = {
                "enabled": True,
                "status": "error",
                "message": "Nessun bollettino reperibile al momento.",
                "today": self._extract_day_summary(None, "", "today"),
                "tomorrow": self._extract_day_summary(None, "", "tomorrow"),
                "zone_name": "Non identificata",
                "municipality": settings.LOCATION_NAME
            }
            self._cached_data = error_res
            return error_res

        ts_str, today_url, tomorrow_url = bulletin_info
        today_feature = None
        tomorrow_feature = None
        zone_name = "Zona non identificata"
        municipality = settings.LOCATION_NAME

        try:
            r_today = requests.get(today_url, headers={"User-Agent": "EcowittWeatherHub/1.0"}, timeout=15)
            if r_today.status_code == 200:
                data_today = r_today.json()
                today_feature = self._find_zone_feature(
                    data_today,
                    settings.LATITUDE,
                    settings.LONGITUDE,
                    settings.LOCATION_NAME,
                    settings.CIVIL_PROTECTION_ZONE_OVERRIDE
                )
                if today_feature:
                    zone_name = today_feature.get("properties", {}).get("Nome zona", zone_name)
        except Exception as e:
            logger.warning(f"Errore download today GeoJSON: {e}")

        try:
            r_tomorrow = requests.get(tomorrow_url, headers={"User-Agent": "EcowittWeatherHub/1.0"}, timeout=15)
            if r_tomorrow.status_code == 200:
                data_tomorrow = r_tomorrow.json()
                tomorrow_feature = self._find_zone_feature(
                    data_tomorrow,
                    settings.LATITUDE,
                    settings.LONGITUDE,
                    settings.LOCATION_NAME,
                    settings.CIVIL_PROTECTION_ZONE_OVERRIDE
                )
                if tomorrow_feature and zone_name == "Zona non identificata":
                    zone_name = tomorrow_feature.get("properties", {}).get("Nome zona", zone_name)
        except Exception as e:
            logger.warning(f"Errore download tomorrow GeoJSON: {e}")

        summary_today = self._extract_day_summary(today_feature, ts_str, "today")
        summary_tomorrow = self._extract_day_summary(tomorrow_feature, ts_str, "tomorrow")

        # Parsing data bollettino leggibile
        try:
            d_part, t_part = ts_str.split("_")
            dt_obj = datetime.strptime(f"{d_part}{t_part}", "%Y%m%d%H%M")
            date_bulletin_str = dt_obj.strftime("%d/%m/%Y ore %H:%M")
        except Exception:
            date_bulletin_str = ts_str

        is_alert_active = (summary_today["severity"] > 0 or summary_tomorrow["severity"] > 0)

        result = {
            "enabled": True,
            "status": "success",
            "bulletin_id": ts_str,
            "bulletin_date_str": date_bulletin_str,
            "zone_name": zone_name,
            "municipality": municipality,
            "coordinates": {"lat": settings.LATITUDE, "lon": settings.LONGITUDE},
            "today": summary_today,
            "tomorrow": summary_tomorrow,
            "is_alert_active": is_alert_active,
            "max_severity": max(summary_today["severity"], summary_tomorrow["severity"]),
            "fetched_at": now,
            "last_check_str": datetime.now(settings.get_tz()).strftime("%d/%m/%Y %H:%M")
        }

        self._cached_data = result
        self._last_fetch_time = now
        self._save_disk_cache(result)
        logger.info(f"Allerte Protezione Civile aggiornate per {zone_name}: Oggi={summary_today['level']}, Domani={summary_tomorrow['level']}")
        return result


civil_protection_service = CivilProtectionService()
