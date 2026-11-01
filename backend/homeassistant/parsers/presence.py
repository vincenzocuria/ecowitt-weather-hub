"""
Parser per il tracciamento della presenza (Person / Device Tracker) e batteria smartphone.
"""

from typing import Dict, Any, Optional


def parse_presence_data(entities: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Estrae la presenza e il livello batteria dello smartphone da Home Assistant."""
    is_present = True
    device_name = "Smartphone"
    battery_pct: Optional[int] = None

    if not entities:
        return {
            "device_id": "ha_presence_phone",
            "name": device_name,
            "device_name": device_name,
            "is_present": True,
            "presence_label": "A Casa 🏠",
            "battery_percent": None,
            "battery_pct": None
        }

    # Cerca person.vincenzo_curia o qualsiasi entità person
    for ent_id, ent in entities.items():
        if ent_id.startswith("person."):
            device_name = ent.get("attributes", {}).get("friendly_name") or "Smartphone"
            st = (ent.get("state") or "").lower()
            if st == "home":
                is_present = True
            elif st in ("not_home", "away"):
                is_present = False
            break

    # Cerca sensore batteria associato a telefono o persona
    for ent_id, ent in entities.items():
        if ent_id.startswith("sensor.") and any(k in ent_id for k in ("_battery_level", "_livello_batteria", "_battery", "_batteria")):
            # Ignora sensori di dispositivi fissi
            if "aiuola" in ent_id or "backup" in ent_id:
                continue
            try:
                val = float(ent.get("state") or 0.0)
                battery_pct = int(round(val))
                break
            except (ValueError, TypeError):
                pass

    return {
        "device_id": "ha_presence_phone",
        "name": device_name,
        "device_name": device_name,
        "is_present": is_present,
        "presence_label": "A Casa 🏠" if is_present else "Fuori Casa 🚗",
        "battery_percent": battery_pct,
        "battery_pct": battery_pct
    }
