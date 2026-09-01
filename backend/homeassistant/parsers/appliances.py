"""
Parser per grandi elettrodomestici smart (Lavatrice, Lavastoviglie, Asciugatrice Samsung / SmartThings).
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional

WASHER_STATE_MAP = {
    "none": "In Standby / Pronto",
    "ready": "Pronto",
    "weight_sensing": "Pesatura Carico & Bilanciamento",
    "weightsensing": "Pesatura Carico & Bilanciamento",
    "wash": "Lavaggio in Corso 🫧",
    "rinse": "Risciacquo in Corso 💧",
    "spin": "Centrifuga in Corso 🌀",
    "drying": "Asciugatura in Corso ♨️",
    "finish": "Ciclo Lavaggio Completato ✅",
    "delay_wash": "Partenza Ritardata Programmata ⏱️",
    "delayend": "Partenza Ritardata Programmata ⏱️",
    "freeze_protection": "Protezione Antigelo",
}

DISHWASHER_STATE_MAP = {
    "none": "In Standby / Pronto",
    "ready": "Pronto",
    "pre_wash": "Prelavaggio 🫧",
    "prewash": "Prelavaggio 🫧",
    "wash": "Lavaggio in Corso 🍽️",
    "rinse": "Risciacquo 💧",
    "dry": "Asciugatura Piatti ♨️",
    "drying": "Asciugatura Piatti ♨️",
    "cooling": "Raffreddamento Piatti 🌬️",
    "pre_drain": "Scarico Acqua 💧",
    "drain": "Scarico Acqua 💧",
    "sanitize": "Ciclo Igienizzante (Sanitize 🧼)",
    "finish": "Ciclo Lavastoviglie Terminato ✅",
    "delay_start": "Partenza Ritardata ⏱️",
    "delaystart": "Partenza Ritardata ⏱️",
    "paused": "In Pausa ⏸️",
    "pause": "In Pausa ⏸️",
    "running": "Lavaggio in Corso 🍽️",
    "run": "Lavaggio in Corso 🍽️",
    "stop": "In Standby / Spenta",
}


def parse_washer_data(entities: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Estrae e struttura lo stato completo della Lavatrice Samsung da Home Assistant."""
    if not entities:
        return None

    machine_state_ent = entities.get("sensor.lavanderia_lavatrice_machine_state")
    job_state_ent = entities.get("sensor.lavanderia_lavatrice_job_state")
    completion_ent = entities.get("sensor.lavanderia_lavatrice_completion_time")
    temp_ent = entities.get("select.lavanderia_lavatrice_temperatura_dell_acqua")
    spin_ent = entities.get("select.lavanderia_lavatrice_spin_level")
    detergent_ent = entities.get("select.lavanderia_lavatrice_detergent_dispense_amount")
    softener_ent = entities.get("select.lavanderia_lavatrice_flexible_compartment_dispense_amount")
    rinse_ent = entities.get("number.lavanderia_lavatrice_rinse_cycles")
    power_ent = entities.get("sensor.lavanderia_lavatrice_potenza") or entities.get("sensor.lavasciuga_potenza")
    energy_ent = entities.get("sensor.lavanderia_lavatrice_energia")
    water_ent = entities.get("sensor.lavanderia_lavatrice_water_consumption")
    bubble_switch = entities.get("switch.lavanderia_lavatrice_bubble_soak")

    if not machine_state_ent and not job_state_ent:
        return None

    machine_state = (machine_state_ent.get("state") if machine_state_ent else "stop") or "stop"
    job_state = (job_state_ent.get("state") if job_state_ent else "none") or "none"

    m_lower = machine_state.lower()
    j_lower = job_state.lower()

    is_connected = not (m_lower in ("unavailable", "unknown") and j_lower in ("unavailable", "unknown"))
    if not is_connected:
        is_running = False
        is_on = False
        job_state_label = "Disconnessa / Offline"
    else:
        is_running = m_lower in ("run", "running") and j_lower not in ("none", "finish", "delay_wash", "delayend")
        is_on = m_lower in ("run", "running", "pause", "paused", "ready") or j_lower in ("run", "wash", "rinse", "spin", "drying", "delay_wash")
        job_state_label = WASHER_STATE_MAP.get(j_lower, job_state.capitalize() if job_state != "none" else "In Standby / Pronta")

    remaining_min = None
    finish_estimate = None
    if completion_ent and completion_ent.get("state") not in ("unavailable", "unknown", None):
        try:
            comp_raw = completion_ent.get("state")
            clean_ts = str(comp_raw).replace("Z", "+00:00")
            comp_dt = datetime.fromisoformat(clean_ts)
            now_dt = datetime.now(timezone.utc)
            diff_sec = (comp_dt - now_dt).total_seconds()
            if diff_sec > 0:
                remaining_min = int(round(diff_sec / 60.0))
                local_dt = comp_dt.astimezone()
                finish_estimate = local_dt.strftime("%H:%M")
        except Exception:
            pass

    water_temp_raw = str(temp_ent.get("state")) if temp_ent and temp_ent.get("state") not in ("none", "unavailable", "unknown", None) else None
    if water_temp_raw:
        water_temp_label = water_temp_raw if ("°" in water_temp_raw or "c" in water_temp_raw.lower()) else f"{water_temp_raw}°C"
    else:
        water_temp_label = "Auto"

    spin_raw = str(spin_ent.get("state")) if spin_ent and spin_ent.get("state") not in ("none", "unavailable", "unknown", None) else None
    if spin_raw:
        spin_label = spin_raw if ("rpm" in spin_raw.lower() or "giri" in spin_raw.lower()) else f"{spin_raw} rpm"
    else:
        spin_label = "Auto"

    power_w = 0.0
    if power_ent and power_ent.get("state") not in ("unavailable", "unknown", None):
        try:
            power_w = float(power_ent.get("state") or 0.0)
        except (ValueError, TypeError):
            power_w = 0.0

    return {
        "device_id": "lavanderia_lavatrice",
        "name": "Lavatrice Samsung",
        "is_connected": is_connected,
        "is_on": is_on,
        "is_running": is_running,
        "machine_state": machine_state,
        "job_state": job_state,
        "job_state_label": job_state_label,
        "water_temp": water_temp_label,
        "spin_speed": spin_label,
        "rinse_cycles": rinse_ent.get("state") if rinse_ent else None,
        "remaining_min": remaining_min,
        "finish_estimate": finish_estimate,
        "softener_level": softener_ent.get("state") if softener_ent else "standard",
        "detergent_level": detergent_ent.get("state") if detergent_ent else "standard",
        "power_w": power_w,
        "energy_kwh": float(energy_ent.get("state") or 0.0) if energy_ent and energy_ent.get("state") not in ("unavailable", "unknown") else None,
        "water_consumption_l": float(water_ent.get("state") or 0.0) if water_ent and water_ent.get("state") not in ("unavailable", "unknown") else None,
        "bubble_soak": bubble_switch.get("state") == "on" if bubble_switch else False,
        "switch_state": "on" if is_on else "off"
    }


def parse_dishwasher_data(entities: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Estrae e struttura lo stato completo della Lavastoviglie Samsung da Home Assistant."""
    if not entities:
        return None

    machine_state_ent = entities.get("sensor.cucina_lavastoviglie_machine_state")
    job_state_ent = entities.get("sensor.cucina_lavastoviglie_job_state")
    completion_ent = entities.get("sensor.cucina_lavastoviglie_completion_time")
    zone_ent = entities.get("select.cucina_lavastoviglie_selected_zone")
    power_ent = entities.get("sensor.lavastoviglie_potenza")
    energy_ent = entities.get("sensor.lavastoviglie_energia_totale")

    if not machine_state_ent and not job_state_ent:
        return None

    machine_state = (machine_state_ent.get("state") if machine_state_ent else "stop") or "stop"
    job_state = (job_state_ent.get("state") if job_state_ent else "none") or "none"

    m_lower = machine_state.lower()
    j_lower = job_state.lower()

    is_connected = not (m_lower in ("unavailable", "unknown") and j_lower in ("unavailable", "unknown"))
    if not is_connected:
        is_running = False
        is_paused = False
        is_on = False
        job_state_label = "Disconnessa / Offline"
    else:
        is_running = m_lower in ("run", "running") or j_lower in ("pre_wash", "prewash", "wash", "rinse", "dry", "drying", "cooling", "drain", "pre_drain", "sanitize")
        is_paused = m_lower in ("pause", "paused") or j_lower in ("pause", "paused")
        is_on = is_running or is_paused or m_lower in ("ready", "delay_start")

        if is_running and j_lower in ("none", "ready"):
            job_state_label = "Lavaggio in Corso 🍽️"
        elif is_paused:
            job_state_label = "In Pausa ⏸️"
        else:
            job_state_label = DISHWASHER_STATE_MAP.get(j_lower, job_state.capitalize() if job_state != "none" else "In Standby / Pronta")

    remaining_min = None
    finish_estimate = None
    if completion_ent and completion_ent.get("state") not in ("unavailable", "unknown", None):
        try:
            comp_raw = completion_ent.get("state")
            clean_ts = str(comp_raw).replace("Z", "+00:00")
            comp_dt = datetime.fromisoformat(clean_ts)
            now_dt = datetime.now(timezone.utc)
            diff_sec = (comp_dt - now_dt).total_seconds()
            if diff_sec > 0:
                remaining_min = int(round(diff_sec / 60.0))
                local_dt = comp_dt.astimezone()
                finish_estimate = local_dt.strftime("%H:%M")
        except Exception:
            pass

    power_w = 0.0
    if power_ent and power_ent.get("state") not in ("unavailable", "unknown", None):
        try:
            power_w = float(power_ent.get("state") or 0.0)
        except (ValueError, TypeError):
            power_w = 0.0

    return {
        "device_id": "cucina_lavastoviglie",
        "name": "Lavastoviglie Samsung",
        "is_connected": is_connected,
        "is_on": is_on,
        "is_running": is_running,
        "is_paused": is_paused,
        "machine_state": machine_state,
        "job_state": job_state,
        "job_state_label": job_state_label,
        "cycle_name": zone_ent.get("state", "Auto / Eco") if zone_ent else "Auto / Eco",
        "remaining_min": remaining_min,
        "finish_estimate": finish_estimate,
        "power_w": power_w,
        "energy_kwh": float(energy_ent.get("state") or 0.0) if energy_ent and energy_ent.get("state") not in ("unavailable", "unknown") else None,
        "switch_state": "on" if is_on else "off"
    }


def parse_fridge_data(entities: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Estrae e struttura lo stato del Frigorifero Smart (LG ThinQ) da Home Assistant."""
    if not entities:
        return None

    door_ent = entities.get("binary_sensor.frigorifero_porta") or entities.get("binary_sensor.fridge_door")
    temp_ent = entities.get("number.frigorifero_temperatura_fridge") or entities.get("number.fridge_temperature")
    express_ent = entities.get("switch.frigorifero_express_mode") or entities.get("switch.fridge_express_mode")

    if not door_ent and not temp_ent and not express_ent:
        return None

    door_open = (door_ent.get("state") == "on") if door_ent else False
    express_mode = (express_ent.get("state") == "on") if express_ent else False

    target_temp = 4
    if temp_ent and temp_ent.get("state") not in ("unavailable", "unknown", None):
        try:
            target_temp = int(float(temp_ent.get("state")))
        except (ValueError, TypeError):
            target_temp = 4

    status_parts = []
    if door_open:
        status_parts.append("🔴 Porta Aperta ⚠️")
    else:
        status_parts.append("🟢 Porta Chiusa")
    status_parts.append(f"Set: {target_temp}°C")
    if express_mode:
        status_parts.append("Express Cool ❄️")

    return {
        "device_id": "frigorifero_lg",
        "raw_id": "frigorifero",
        "name": "Frigorifero LG",
        "is_connected": True,
        "is_on": express_mode,
        "can_toggle": True,
        "is_online": True,
        "door_open": door_open,
        "express_mode": express_mode,
        "target_temp": target_temp,
        "temp_set": target_temp,
        "status_text": " • ".join(status_parts),
        "power_w": 0.0
    }

