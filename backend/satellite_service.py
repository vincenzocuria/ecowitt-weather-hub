"""
Nuvole dal satellite Meteosat (EUMETSAT, servizio WMS pubblico).

La mappa carica le immagini direttamente da EUMETSAT; qui si legge solo l'ora dell'ultima
immagine disponibile per ogni livello (cache di 5 minuti), da mostrare sul radar e da usare
come parametro TIME, così le tessere si aggiornano quando arriva un'immagine nuova.
"""
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict

import requests

from backend.config import settings

logger = logging.getLogger(__name__)

WMS_URL = "https://view.eumetsat.int/geoserver/wms"
SATELLITE_LAYERS = {
    "ir": {"layer": "mtg_fd:ir105_hrfi", "label": "Infrarosso (giorno e notte)"},
    "color": {"layer": "mtg_fd:rgb_geocolour", "label": "Colori reali"},
}
CACHE_S = 300


class SatelliteService:
    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._at = 0.0

    def _latest_time(self, layer: str) -> str:
        ns, name = layer.split(":", 1)
        resp = requests.get(f"https://view.eumetsat.int/geoserver/{ns}/{name}/ows",
                            params={"service": "WMS", "request": "GetCapabilities", "version": "1.3.0"},
                            timeout=15, headers={"User-Agent": "WeatherHub/1.0"})
        resp.raise_for_status()
        m = re.search(r'<Dimension name="time"[^>]*default="([^"]+)"', resp.text)
        if not m:
            raise ValueError("ora dell'immagine non trovata")
        return m.group(1)

    def info(self) -> Dict[str, Any]:
        if self._cache and time.time() - self._at < CACHE_S:
            return self._cache
        layers = {}
        for key, cfg in SATELLITE_LAYERS.items():
            item = {"layer": cfg["layer"], "label": cfg["label"], "time": None, "local_time": None}
            try:
                t = self._latest_time(cfg["layer"])
                item["time"] = t
                item["local_time"] = datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(settings.get_tz()).strftime("%H:%M")
            except Exception as e:
                logger.warning(f"Satellite {cfg['layer']}: ora non disponibile ({e})")
            layers[key] = item
        self._cache = {"wms_url": WMS_URL, "layers": layers, "source": "EUMETSAT Meteosat"}
        self._at = time.time()
        return self._cache


satellite_service = SatelliteService()
