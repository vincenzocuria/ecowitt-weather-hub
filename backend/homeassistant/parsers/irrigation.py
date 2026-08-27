"""
Parser per elettrovalvole di irrigazione e timer dedicati (valve.*, number.*_duration).
"""

from typing import Dict, Any, List


def parse_irrigation_data(entities: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Estrae lo stato delle elettrovalvole di irrigazione da Home Assistant."""
    valves: List[Dict[str, Any]] = []
    valve_is_open = False

    for entity_id, state_obj in entities.items():
        if entity_id.startswith("valve."):
            attrs = state_obj.get("attributes", {})
            friendly_name = attrs.get("friendly_name") or entity_id
            st = (state_obj.get("state") or "closed").lower()
            if st == "open":
                valve_is_open = True

            valves.append({
                "id": entity_id,
                "name": friendly_name,
                "state": st,
                "is_open": st == "open",
                "raw": state_obj
            })

    # Fallback su aiuola specifica se non già trovata
    if not valves:
        valve_aiuola = entities.get("valve.aiuola_valve", {})
        valve_aiuola_2 = entities.get("valve.aiuola_valve_2", {})
        valve_is_open = valve_aiuola.get("state") == "open" or valve_aiuola_2.get("state") == "open"
        valves = [
            {"id": "valve.aiuola_valve", "name": "Aiuola", "state": valve_aiuola.get("state", "closed"), "is_open": valve_aiuola.get("state") == "open"},
            {"id": "valve.aiuola_valve_2", "name": "Aiuola 2", "state": valve_aiuola_2.get("state", "closed"), "is_open": valve_aiuola_2.get("state") == "open"}
        ]

    return {
        "is_open": valve_is_open,
        "valves": valves
    }
