"""
Helper per il calcolo delle sinergie domotiche ed energetiche:
- Sinergia Solare Aton per avvio lavatrice / lavastoviglie a costo zero
- Sinergia Lavatrice in funzione + Indice Asciugatura Bucato meteo
- Riepilogo integrato per dashboard e automazioni
"""

from typing import Dict, Any, Optional

from .parsers.appliances import parse_washer_data, parse_dishwasher_data
from .parsers.presence import parse_presence_data
from .parsers.irrigation import parse_irrigation_data
from .parsers.health import parse_health_data


class SynergiesHelper:
    """Valutatore delle sinergie tra meteo, fotovoltaico e dispositivi Home Assistant."""

    @staticmethod
    def calculate_solar_synergy(p_solare: float, soc: float) -> Dict[str, Any]:
        """Calcola se sussistono condizioni ottimali di produzione solare o carica batteria."""
        solar_optimal = False
        solar_message = "Produzione solare assente o insufficiente per avvio elettrodomestici a costo zero."
        solar_badge_class = "badge-neutral"

        if p_solare >= 1500 or (p_solare >= 800 and soc >= 60) or soc >= 85:
            solar_optimal = True
            solar_badge_class = "badge-success"
            if p_solare >= 1800:
                solar_message = f"Momento Ideale: Surplus Solare Fotovoltaico ({int(p_solare)} W) sufficiente per lavaggi a Costo Zero!"
            elif soc >= 70:
                solar_message = f"Momento Favorevole: Batteria Aton carica ({int(soc)}%) e {int(p_solare)} W solari disponibili."
            else:
                solar_message = f"Energia Solare disponibile ({int(p_solare)} W)."

        return {
            "solar_optimal": solar_optimal,
            "solar_message": solar_message,
            "solar_badge_class": solar_badge_class,
            "p_solare": p_solare,
            "soc": soc
        }

    @staticmethod
    def calculate_drying_synergy(
        washer_data: Optional[Dict[str, Any]],
        drying_index: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Calcola la sinergia tra lavaggio in corso e condizioni esterne per stendere il bucato."""
        if not washer_data or not drying_index:
            return None

        dry_score = drying_index.get("score", 0)
        dry_desc = drying_index.get("desc", "")

        if washer_data.get("is_running"):
            if dry_score >= 60:
                return {
                    "optimal": True,
                    "badge": "🟢 Stendi all'aperto",
                    "text": f"Il lavaggio terminerà a breve e le condizioni meteo esterne sono ottime per asciugare il bucato all'aperto ({dry_desc})."
                }
            else:
                return {
                    "optimal": False,
                    "badge": "🟡 Asciugatura lenta / sconsigliata",
                    "text": f"Attenzione: clima esterno poco favorevole per stendere ({dry_desc})."
                }
        return None

    @classmethod
    def get_summary(
        cls,
        entities: Dict[str, Dict[str, Any]],
        enabled: bool,
        is_connected: bool,
        last_sync_time: float,
        sync_error: Optional[str],
        energy_latest: Optional[Dict[str, Any]] = None,
        drying_index: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Produce un riepilogo strutturato per dashboard, alert engine e automazioni."""
        washer_data = parse_washer_data(entities)
        dishwasher_data = parse_dishwasher_data(entities)
        presence_data = parse_presence_data(entities)
        irrigation_data = parse_irrigation_data(entities)
        health_data = parse_health_data(entities)

        p_solare = 0.0
        soc = 0.0
        if energy_latest:
            p_solare = float(energy_latest.get("p_solare") if energy_latest.get("p_solare") is not None else (energy_latest.get("solar_power_w") or 0.0))
            soc = float(energy_latest.get("soc") if energy_latest.get("soc") is not None else (energy_latest.get("battery_soc_pct") or 0.0))

        solar_synergy = cls.calculate_solar_synergy(p_solare, soc)
        laundry_synergy = cls.calculate_drying_synergy(washer_data, drying_index)

        from .catalog import CatalogHelper
        catalog_devs = CatalogHelper.get_catalog_devices(entities, enabled)

        enabled_devs = []
        total_plug_power_w = 0.0

        for d in catalog_devs:
            cat = d.get("category")
            if cat in ("presence", "health", "appliances"):
                continue

            raw_id_lower = str(d.get("raw_id") or "").lower()
            name_lower = str(d.get("name") or "").lower()

            if cat == "plugs":
                cat_code = "cz"
                type_label = "Presa Smart"
                if d.get("is_on"):
                    total_plug_power_w += float(d.get("power_w") or 0.0)
            elif cat == "climate":
                cat_code = "wk"
                type_label = "Cronotermostato" if "termostato" in raw_id_lower or "termostato" in name_lower else "Climatizzatore"
            elif cat == "irrigation":
                cat_code = "sfkzq"
                type_label = "Elettrovalvola Irrigazione"
            elif cat == "shutters":
                cat_code = "clkg"
                type_label = "Persiana / Tenda"
            elif cat == "lights":
                cat_code = "dj"
                type_label = "Luce Smart"
            else:
                cat_code = "cz"
                type_label = "Dispositivo Smart"

            dev_id = str(d.get("raw_id") or d.get("id"))
            enabled_devs.append({
                "id": dev_id,
                "raw_id": dev_id,
                "name": d.get("name"),
                "icon": d.get("icon", "🔌"),
                "category": cat_code,
                "type_label": type_label,
                "product_name": d.get("category_label", "Home Assistant"),
                "is_on": d.get("is_on"),
                "power_w": round(float(d.get("power_w") or 0.0), 1),
                "voltage_v": d.get("voltage_v"),
                "current_a": d.get("current_a"),
                "temp_current": d.get("current_temp"),
                "temp_set": d.get("target_temp"),
                "battery_pct": d.get("battery_pct"),
                "curtain_state": "aperta" if d.get("is_on") else "chiusa",
                "work_state": "In funzione" if d.get("is_on") else "In riposo",
                "raw_status": {}
            })

        plugs = [d for d in enabled_devs if d.get("category") == "cz"]
        climates = [d for d in enabled_devs if d.get("category") == "wk"]
        irrigations = [d for d in enabled_devs if d.get("category") == "sfkzq"]
        curtains = [d for d in enabled_devs if d.get("category") == "clkg"]
        lights = [d for d in enabled_devs if d.get("category") == "dj"]

        return {
            "enabled": enabled,
            "is_connected": is_connected,
            "last_sync": last_sync_time,
            "error": sync_error,
            "washer": washer_data,
            "dishwasher": dishwasher_data,
            "presence": presence_data,
            "solar_synergy": solar_synergy,
            "laundry_drying_synergy": laundry_synergy,
            "irrigation": irrigation_data,
            "health": health_data,
            "total_plug_power_w": round(total_plug_power_w, 1),
            "total_devices_count": len(enabled_devs),
            "enabled_devices_count": len(enabled_devs),
            "enabled_devices": enabled_devs,
            "devices": enabled_devs,
            "plugs": plugs,
            "climates": climates,
            "irrigations": irrigations,
            "curtains": curtains,
            "lights": lights
        }
