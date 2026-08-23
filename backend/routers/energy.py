import logging
from typing import Optional
from fastapi import APIRouter

from backend.config import settings
from backend.aton_service import aton_service
from backend.database import get_latest_energy, get_today_energy_summary, get_energy_timeseries
from backend.tuya_service import tuya_service
from backend.thinq_service import thinq_service
from backend.smartthings_service import smartthings_service

logger = logging.getLogger("weather_hub")

router = APIRouter(tags=["Energy & Photovoltaic"])

@router.get("/api/energy/latest")
async def api_energy_latest():
    """Restituisce l'ultima lettura energetica live da Aton Storage."""
    data = aton_service.latest_data or get_latest_energy()
    return {
        "enabled": settings.ATON_ENABLED,
        "connected": aton_service.is_connected,
        "serial_number": settings.ATON_SN,
        "data": data
    }

@router.get("/api/energy/summary")
async def api_energy_summary():
    """Restituisce il riassunto energetico odierno (produzione, autoconsumo, autosufficienza)."""
    return get_today_energy_summary()

@router.get("/api/energy/history")
async def api_energy_history(hours: int = 24):
    """Restituisce la serie storica energetica per i grafici."""
    return {"history": get_energy_timeseries(hours=hours)}

@router.get("/api/energy/house-breakdown")
async def api_energy_house_breakdown():
    """
    Restituisce la ripartizione dettagliata in tempo reale dei consumi domestici:
    potenza totale della casa, dispositivi/prese smart attive con relativo assorbimento (W, V, A),
    elettrodomestici in esecuzione, climatizzatori accesi e stima del carico di fondo/non monitorato.
    """
    energy_data = aton_service.latest_data or get_latest_energy() or {}
    summary = get_today_energy_summary() or {}

    total_house_w = float(energy_data.get("p_utenze") if energy_data.get("p_utenze") is not None else (energy_data.get("house_load_w") or 0.0))
    total_house_kwh = summary.get("total_house_kwh", "0.0")
    p_solar_w = float(energy_data.get("p_solare") or energy_data.get("solar_power_w") or 0.0)
    p_batt_w = float(energy_data.get("p_batteria") or energy_data.get("battery_power_w") or 0.0)
    p_grid_w = float(energy_data.get("p_rete") or energy_data.get("grid_power_w") or 0.0)

    active_consumers = []
    standby_devices = []

    # 1. Prese Smart ed Interruttori Tuya / Smart Life
    if settings.TUYA_ENABLED:
        tuya_sum = tuya_service.get_summary()
        all_tuya = tuya_sum.get("enabled_devices") or tuya_sum.get("devices") or []
        for dev in all_tuya:
            p_w = float(dev.get("power_w") or 0.0)
            is_on = dev.get("is_on")
            c_type = dev.get("type") or "generic"
            icon = dev.get("icon") or "🔌"
            name = dev.get("name", "Presa Smart")
            cat_label = dev.get("type_label") or "Presa Smart Life"

            status_txt = "Spento" if is_on is False else "Acceso"
            if is_on and p_w > 0:
                status_txt = f"Assorbimento: {p_w:.1f} W"
            elif is_on and dev.get("temp_current") is not None:
                status_txt = f"Temp: {dev.get('temp_current')}°C"

            entry = {
                "id": f"tuya_{dev.get('id')}",
                "raw_id": dev.get("id"),
                "ecosystem": "tuya",
                "name": name,
                "icon": icon,
                "category_label": cat_label,
                "type": c_type,
                "is_on": is_on,
                "can_toggle": (c_type != "curtain") and (is_on is not None or c_type in ("plug", "light", "irrigation")),
                "power_w": p_w,
                "voltage_v": dev.get("voltage_v"),
                "current_a": dev.get("current_a"),
                "status_text": status_txt
            }

            if is_on is True and (p_w > 0 or c_type in ("plug", "light", "switch", "thermostat")):
                active_consumers.append(entry)
            else:
                standby_devices.append(entry)

    # 2. Climatizzatori LG ThinQ
    if settings.LG_THINQ_ENABLED:
        thinq_devs = thinq_service.get_cached_devices()
        for d in thinq_devs:
            is_on = d.get("is_on", False)
            mode = d.get("mode") or d.get("job_mode", "COOL")
            mode_lbl = "Raffrescamento" if mode == "COOL" else ("Riscaldamento" if mode == "HEAT" else "Deumidificatore / Ventilazione")
            t_curr = d.get("current_temp")
            t_target = d.get("target_temp")

            stat_parts = []
            if is_on:
                stat_parts.append(f"In funzione ({mode_lbl})")
                if t_target is not None:
                    stat_parts.append(f"Impostato: {t_target}°C")
                if t_curr is not None:
                    stat_parts.append(f"Stanza: {t_curr}°C")
            else:
                stat_parts.append("Spento")
                if t_curr is not None:
                    stat_parts.append(f"Temp: {t_curr}°C")

            entry = {
                "id": f"thinq_{d.get('device_id') or d.get('deviceId')}",
                "raw_id": d.get("device_id") or d.get("deviceId"),
                "ecosystem": "thinq",
                "name": d.get("alias") or d.get("name", "Climatizzatore LG"),
                "icon": "❄️" if mode == "COOL" else ("🔥" if mode == "HEAT" else "🌬️"),
                "category_label": "Climatizzatore LG ThinQ",
                "type": "climate",
                "is_on": is_on,
                "can_toggle": True,
                "power_w": 0.0,
                "status_text": " • ".join(stat_parts)
            }
            if is_on:
                active_consumers.append(entry)
            else:
                standby_devices.append(entry)

    # 3. Samsung SmartThings (Lavatrice / Lavastoviglie)
    if settings.SMARTTHINGS_ENABLED:
        st_summary = smartthings_service.get_summary(energy_data)
        washer = st_summary.get("washer") or {}
        if washer and washer.get("device_id"):
            is_run = washer.get("is_running", False)
            is_on = washer.get("is_on", False)
            p_w = float(washer.get("power_w") or 0.0)

            st_text = washer.get("job_state_label") or ("In Lavaggio" if is_run else "In Standby")
            if washer.get("remaining_min") and washer.get("remaining_min") > 0:
                st_text += f" • {washer.get('remaining_min')} min rimasti (fine ~{washer.get('finish_estimate')})"
            if washer.get("cycle_name"):
                st_text += f" • {washer.get('cycle_name')}"

            entry = {
                "id": f"st_{washer.get('device_id')}",
                "raw_id": washer.get("device_id"),
                "ecosystem": "smartthings",
                "name": washer.get("name", "Lavatrice Samsung"),
                "icon": "🫧",
                "category_label": "Lavatrice Samsung Smart",
                "type": "appliance",
                "is_on": is_on,
                "is_running": is_run,
                "can_toggle": False,
                "power_w": p_w,
                "status_text": st_text
            }
            if is_run or is_on or p_w > 0:
                active_consumers.append(entry)
            else:
                standby_devices.append(entry)

        dish = st_summary.get("dishwasher") or {}
        if dish and dish.get("device_id"):
            is_run = dish.get("is_running", False)
            is_on = dish.get("is_on", False)
            p_w = float(dish.get("power_w") or 0.0)

            st_text = dish.get("job_state_label") or ("In Lavaggio" if is_run else "In Standby")
            if dish.get("remaining_min") and dish.get("remaining_min") > 0:
                st_text += f" • {dish.get('remaining_min')} min rimasti (fine ~{dish.get('finish_estimate')})"
            if dish.get("cycle_name"):
                st_text += f" • {dish.get('cycle_name')}"

            entry = {
                "id": f"st_{dish.get('device_id')}",
                "raw_id": dish.get("device_id"),
                "ecosystem": "smartthings",
                "name": dish.get("name", "Lavastoviglie Samsung"),
                "icon": "🍽️",
                "category_label": "Lavastoviglie Samsung Smart",
                "type": "appliance",
                "is_on": is_on,
                "is_running": is_run,
                "can_toggle": False,
                "power_w": p_w,
                "status_text": st_text
            }
            if is_run or is_on or p_w > 0:
                active_consumers.append(entry)
            else:
                standby_devices.append(entry)

    # Calcolo totali e quote
    monitored_power_w = sum(d.get("power_w", 0.0) for d in active_consumers)
    monitored_power_w = round(monitored_power_w, 1)

    unmonitored_power_w = max(0.0, total_house_w - monitored_power_w)
    unmonitored_power_w = round(unmonitored_power_w, 1)

    for d in active_consumers:
        p = d.get("power_w", 0.0)
        d["percent_of_total"] = round((p / total_house_w * 100), 1) if total_house_w > 0 else 0.0

    active_consumers.sort(key=lambda x: (x.get("power_w", 0.0), 1 if x.get("is_running") or x.get("is_on") else 0), reverse=True)

    monitored_pct = round((monitored_power_w / total_house_w * 100), 1) if total_house_w > 0 else 0.0
    unmonitored_pct = round((unmonitored_power_w / total_house_w * 100), 1) if total_house_w > 0 else 0.0

    return {
        "total_house_w": round(total_house_w, 1),
        "total_house_kwh": total_house_kwh,
        "solar_power_w": round(p_solar_w, 1),
        "battery_power_w": round(p_batt_w, 1),
        "grid_power_w": round(p_grid_w, 1),
        "monitored_power_w": monitored_power_w,
        "unmonitored_power_w": unmonitored_power_w,
        "monitored_pct": monitored_pct,
        "unmonitored_pct": unmonitored_pct,
        "active_consumers": active_consumers,
        "standby_devices": standby_devices,
        "active_count": len(active_consumers),
        "standby_count": len(standby_devices)
    }
