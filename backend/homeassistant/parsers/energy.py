"""
Parser per entità energetiche e di accumulo (inverter, batteria, consumi) esposte in Home Assistant.
"""

from typing import Dict, Any, Optional


def parse_energy_data(entities: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Estrae dati fotovoltaici o di batteria da sensori presenti in Home Assistant
    (utile se in futuro Aton, SolarEdge, Huawei o contatori smart sono integrati direttamente in HA).
    """
    if not entities:
        return None

    solar_w = 0.0
    battery_soc = 0.0
    battery_w = 0.0
    house_w = 0.0
    found_any = False

    for entity_id, state_obj in entities.items():
        st = state_obj.get("state")
        if st in ("unavailable", "unknown", None):
            continue

        try:
            val = float(st)
        except (ValueError, TypeError):
            continue

        e_lower = entity_id.lower()
        if any(k in e_lower for k in ("solar_power", "potenza_solare", "p_solare", "pv_power", "fotovoltaico_potenza")):
            solar_w = val
            found_any = True
        elif any(k in e_lower for k in ("battery_soc", "batteria_soc", "battery_level", "livello_batteria_accumulo")) and "smartphone" not in e_lower and "phone" not in e_lower:
            battery_soc = val
            found_any = True
        elif any(k in e_lower for k in ("battery_power", "potenza_batteria", "p_batteria")):
            battery_w = val
            found_any = True
        elif any(k in e_lower for k in ("house_power", "potenza_casa", "p_utenze", "potenza_carichi")):
            house_w = val
            found_any = True

    if not found_any:
        return None

    return {
        "solar_power_w": solar_w,
        "p_solare": solar_w,
        "battery_soc_pct": battery_soc,
        "soc": battery_soc,
        "battery_power_w": battery_w,
        "p_batteria": battery_w,
        "house_load_w": house_w,
        "p_utenze": house_w
    }
