"""
Parser per entità di climatizzazione e termostati (climate.*).
Supporta climatizzatori Fujitsu FGLair, LG ThinQ e termostati smart con telemetria elettrica e consumi.
"""

from typing import Dict, Any, List


def parse_climate_data(entities: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Estrae e normalizza tutti i climatizzatori e termostati presenti in Home Assistant con telemetria consumi."""
    climate_devices = []

    # Mappa sensori di consumo e potenza elettrica
    power_sensors: Dict[str, float] = {}
    energy_sensors: Dict[str, float] = {}
    voltage_sensors: Dict[str, float] = {}
    current_sensors: Dict[str, float] = {}

    for entity_id, state_obj in entities.items():
        if not entity_id.startswith("sensor."):
            continue
        st = state_obj.get("state")
        if st in ("unavailable", "unknown", None):
            continue
        try:
            val = float(st)
        except (ValueError, TypeError):
            continue

        e_clean = entity_id.replace("sensor.", "")
        if any(k in e_clean for k in ("_potenza", "_power", "_consumption")):
            k = e_clean.replace("_potenza", "").replace("_power", "").replace("_consumption", "")
            power_sensors[k] = val
        elif any(k in e_clean for k in ("_energia_totale", "_energy_total", "_total_energy", "_energy_today")):
            k = e_clean.replace("_energia_totale", "").replace("_energy_total", "").replace("_total_energy", "").replace("_energy_today", "")
            energy_sensors[k] = val
        elif any(k in e_clean for k in ("_tensione", "_voltage")):
            k = e_clean.replace("_tensione", "").replace("_voltage", "")
            voltage_sensors[k] = val
        elif any(k in e_clean for k in ("_corrente", "_current")):
            k = e_clean.replace("_corrente", "").replace("_current", "")
            current_sensors[k] = val

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
        swing_modes = attrs.get("swing_modes") or []
        preset_modes = attrs.get("preset_modes") or []
        fan_mode = attrs.get("fan_mode")
        swing_mode = attrs.get("swing_mode")
        preset_mode = attrs.get("preset_mode")

        clean_slug = entity_id.replace("climate.", "")
        is_fujitsu = any(k in clean_slug.lower() or k in friendly_name.lower() for k in ("cucina", "fujitsu", "fglair"))
        is_thermostat = "termostato" in clean_slug.lower() or "thermostat" in clean_slug.lower()

        # Telemetria elettrica associata
        p_w = 0.0
        volt_v = None
        curr_a = None
        energy_kwh = None

        if is_fujitsu:
            p_w = power_sensors.get("climatizzatore", power_sensors.get("cucina", 0.0))
            volt_v = voltage_sensors.get("climatizzatore", voltage_sensors.get("cucina"))
            curr_a = current_sensors.get("climatizzatore", current_sensors.get("cucina"))
            energy_kwh = energy_sensors.get("climatizzatore", energy_sensors.get("cucina"))
            model_name = "Fujitsu General FGLair (AC-UTY)"
            brand = "Fujitsu"
        elif "camera_da_letto" in clean_slug:
            energy_kwh = energy_sensors.get("camera_da_letto", energy_sensors.get("camera_da_letto_energy_today"))
            model_name = "LG Dual Inverter"
            brand = "LG"
        elif "cameretta" in clean_slug:
            energy_kwh = energy_sensors.get("cameretta", energy_sensors.get("cameretta_energy_today"))
            model_name = "LG Dual Inverter"
            brand = "LG"
        elif is_thermostat:
            model_name = "Cronotermostato Smart"
            brand = "Smart Home"
        else:
            model_name = "Climatizzatore Inverter"
            brand = "Smart Home"

        dev_type = "DEVICE_THERMOSTAT" if is_thermostat else "DEVICE_AIR_CONDITIONER"

        climate_devices.append({
            "id": f"hass_{entity_id}",
            "raw_id": entity_id,
            "device_id": clean_slug,
            "deviceId": clean_slug,
            "alias": friendly_name,
            "name": friendly_name,
            "brand": brand,
            "model_name": model_name,
            "device_type": dev_type,
            "is_on": is_on,
            "state": state_str,
            "mode": state_str.upper(),
            "job_mode": state_str.upper(),
            "current_temp": float(curr_temp) if curr_temp is not None else None,
            "temp_current": float(curr_temp) if curr_temp is not None else None,
            "target_temp": float(target_temp) if target_temp is not None else None,
            "temp_set": float(target_temp) if target_temp is not None else None,
            "fan_speed": str(fan_mode).upper() if fan_mode else "AUTO",
            "fan_mode": fan_mode,
            "fan_modes": fan_modes,
            "swing_mode": swing_mode,
            "swing_modes": swing_modes,
            "rotate_up_down": bool(swing_mode and str(swing_mode).lower() not in ("off", "none")),
            "preset_mode": preset_mode,
            "preset_modes": preset_modes,
            "hvac_modes": hvac_modes,
            "power_w": p_w,
            "voltage_v": volt_v,
            "current_a": curr_a,
            "energy_total_kwh": energy_kwh,
            "is_online": state_str not in ("unavailable", "unknown"),
            "raw": state_obj
        })

    return climate_devices

