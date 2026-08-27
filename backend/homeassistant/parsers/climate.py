"""
Parser per entità di climatizzazione e termostati (climate.*).
"""

from typing import Dict, Any, List


def parse_climate_data(entities: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Estrae e normalizza tutti i climatizzatori e termostati presenti in Home Assistant."""
    climate_devices = []

    for entity_id, state_obj in entities.items():
        if not entity_id.startswith("climate."):
            continue

        attrs = state_obj.get("attributes", {})
        friendly_name = attrs.get("friendly_name") or entity_id
        state_str = (state_obj.get("state") or "off").lower()
        is_on = state_str not in ("off", "unavailable", "unknown")

        curr_temp = attrs.get("current_temperature")
        target_temp = attrs.get("temperature")
        hvac_modes = attrs.get("hvac_modes") or []
        fan_modes = attrs.get("fan_modes") or []

        climate_devices.append({
            "id": f"hass_{entity_id}",
            "raw_id": entity_id,
            "name": friendly_name,
            "is_on": is_on,
            "state": state_str,
            "current_temp": float(curr_temp) if curr_temp is not None else None,
            "target_temp": float(target_temp) if target_temp is not None else None,
            "hvac_modes": hvac_modes,
            "fan_modes": fan_modes,
            "is_online": state_str not in ("unavailable", "unknown"),
            "raw": state_obj
        })

    return climate_devices
