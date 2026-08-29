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
            "health": health_data
        }
