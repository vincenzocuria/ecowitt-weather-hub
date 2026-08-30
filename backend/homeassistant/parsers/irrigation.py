"""
Parser per elettrovalvole di irrigazione e timer dedicati (valve.*, switch.*_irrigazione, number.*_duration).
"""

from typing import Dict, Any, List


def parse_irrigation_data(entities: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Estrae lo stato delle elettrovalvole di irrigazione reali da Home Assistant."""
    valves: List[Dict[str, Any]] = []
    valve_is_open = False

    if not entities:
        return {"is_open": False, "valves": []}

    for entity_id, state_obj in entities.items():
        domain = entity_id.split(".")[0]
        attrs = state_obj.get("attributes", {})
        friendly_name = attrs.get("friendly_name") or entity_id
        ent_lower = entity_id.lower()
        name_lower = friendly_name.lower()
        device_class = str(attrs.get("device_class") or "").lower()

        is_irrigation_entity = domain == "valve" or (
            domain == "switch" and (
                device_class == "valve" or
                any(k in ent_lower or k in name_lower for k in (
                    "valvola", "valve", "irrigazione", "irrigation", "aiuola", "sprinkler", "annaffiat", "irrigatore"
                ))
            )
        )

        if is_irrigation_entity:
            st = (state_obj.get("state") or "closed").lower()
            is_open = st in ("open", "on")
            if is_open:
                valve_is_open = True

            valves.append({
                "id": entity_id,
                "name": friendly_name,
                "state": st,
                "is_open": is_open,
                "raw": state_obj
            })

    return {
        "is_open": valve_is_open,
        "valves": valves
    }
