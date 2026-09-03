"""
Modulo unificato per la generazione del catalogo dispositivi smart (Smart Devices Hub).
Aggrega ed armonizza lo stato di:
- Console Stazione Meteo Ecowitt & Sensori Wireless (Gateway, WH57 Fulmini, WH51 Umidità Suolo)
- Impianto Fotovoltaico & Accumulo Aton Storage
- Home Assistant (Hub Domotico Locale Unico: Samsung, LG ThinQ, Tuya, Presenza S26, Condizionatori, Prese, Luci)
- Fallback cloud diretto su LG ThinQ
- Gestione alias personalizzati e timer/programmazioni attive
"""

import logging
from typing import Dict, Any, List

from backend.config import settings
from backend.database import (
    get_latest_reading,
    get_station_status,
    get_soil_moisture_summary,
    get_latest_energy,
    get_device_aliases,
)
from backend.aton_service import aton_service
from backend.homeassistant_service import homeassistant_service
from backend.thinq_service import thinq_service
from backend.device_scheduler import device_scheduler

logger = logging.getLogger("weather_hub.devices_catalog")


def build_devices_catalog() -> Dict[str, Any]:
    """Genera l'elenco normalizzato e aggregato di tutti i dispositivi smart (Ecowitt Meteo, Aton Solar, Home Assistant)."""
    devices: List[Dict[str, Any]] = []

    # 0. Stazione Meteo Ecowitt & Sensori Wireless (Gateway, WH57 Fulmini, WH51 Suolo)
    try:
        w_latest = get_latest_reading() or {}
        stat_info = get_station_status()
        st_online = bool(stat_info.get("is_online", False))

        # 0.1 Console Gateway Ecowitt
        t_out = w_latest.get("temp_c")
        t_in = w_latest.get("temp_in_c")
        hum_out = w_latest.get("humidity")
        wind_spd = w_latest.get("wind_speed_kmh")

        gw_status_parts = []
        if st_online:
            gw_status_parts.append("Connessa & Live 🟢")
            if t_out is not None:
                gw_status_parts.append(f"Est: {t_out}°C ({hum_out or '--'}%)")
            if t_in is not None:
                gw_status_parts.append(f"Int: {t_in}°C")
            if wind_spd is not None:
                gw_status_parts.append(f"Vento: {wind_spd} km/h")
        else:
            gw_status_parts.append(stat_info.get("text", "🔴 Stazione Offline"))

        devices.append({
            "id": "ecowitt_station_gateway",
            "raw_id": "ecowitt_gateway",
            "ecosystem": "ecowitt",
            "name": settings.STATION_NAME or "Console Stazione Meteo Ecowitt",
            "icon": "🌦️",
            "category": "weather",
            "category_label": "Stazione Meteo & Gateway",
            "is_on": st_online,
            "can_toggle": False,
            "is_online": st_online,
            "status_text": " • ".join(gw_status_parts),
            "power_w": 0.0,
            "temp_out_c": t_out,
            "temp_in_c": t_in,
            "humidity_out": hum_out,
            "wind_speed_kmh": wind_spd,
            "raw": w_latest,
        })

        # 0.2 Rilevatore Fulmini WH57
        l_dist = w_latest.get("lightning_distance_km")
        l_count = w_latest.get("lightning_count")
        l_time = w_latest.get("lightning_last_time")

        l_status = "In ascolto attivo • 0 Scariche"
        l_active = False
        if l_dist is not None:
            l_status = f"⚡ Rilevato fulmine a {l_dist} km ({l_count or 0} totali)"
            l_active = True
        elif not st_online:
            l_status = "In attesa segnale gateway"

        devices.append({
            "id": "ecowitt_wh57_lightning",
            "raw_id": "ecowitt_wh57",
            "ecosystem": "ecowitt",
            "name": "Rilevatore Fulmini WH57",
            "icon": "⚡",
            "category": "weather",
            "category_label": "Sensore Fulmini & Tempeste",
            "is_on": l_active,
            "can_toggle": False,
            "is_online": st_online,
            "status_text": l_status,
            "power_w": 0.0,
            "lightning_distance_km": l_dist,
            "lightning_count": l_count,
            "lightning_last_time": l_time,
            "raw": w_latest,
        })

        # 0.3 Sensori Umidità Suolo WH51
        s_summary = get_soil_moisture_summary()
        s_channels = (s_summary.get("channels") if s_summary else {}) or {}
        if s_channels:
            for ch, ch_data in s_channels.items():
                val = ch_data.get("value")
                name = ch_data.get("name") or f"Sensore Suolo {ch.upper()}"
                devices.append({
                    "id": f"ecowitt_wh51_{ch}",
                    "raw_id": f"soil_{ch}",
                    "ecosystem": "ecowitt",
                    "name": name,
                    "icon": "🌱",
                    "category": "weather",
                    "category_label": f"Umidità Suolo WH51 ({ch.upper()})",
                    "is_on": bool(st_online and val is not None),
                    "can_toggle": False,
                    "is_online": bool(st_online and val is not None),
                    "status_text": f"Umidità: {val}% • {ch_data.get('status_label', 'Normale')}" if val is not None else "In attesa dati",
                    "power_w": 0.0,
                    "soil_moisture_pct": val,
                    "raw": ch_data,
                })
        else:
            devices.append({
                "id": "ecowitt_wh51_general",
                "raw_id": "soil_ch1",
                "ecosystem": "ecowitt",
                "name": "Sensore Umidità Terreno WH51",
                "icon": "🌱",
                "category": "weather",
                "category_label": "Umidità Suolo WH51",
                "is_on": False,
                "can_toggle": False,
                "is_online": st_online,
                "status_text": "In ascolto canali radio (CH 1-8)",
                "power_w": 0.0,
                "raw": {},
            })
    except Exception as e:
        logger.warning(f"Errore aggiunta dispositivi Ecowitt al catalogo: {e}")

    # 1. Aton Storage Fotovoltaico & Batteria
    if settings.ATON_ENABLED:
        e_latest = aton_service.latest_data or get_latest_energy() or {}
        p_solar = float(e_latest.get("p_solare") if e_latest.get("p_solare") is not None else (e_latest.get("solar_power_w") or 0))
        p_batt = float(e_latest.get("p_batteria") if e_latest.get("p_batteria") is not None else (e_latest.get("battery_power_w") or 0))
        soc = float(e_latest.get("soc") if e_latest.get("soc") is not None else (e_latest.get("battery_soc_pct") or 0))
        load = float(e_latest.get("p_utenze") if e_latest.get("p_utenze") is not None else (e_latest.get("house_load_w") or 0))
        grid = float(e_latest.get("p_rete") if e_latest.get("p_rete") is not None else (e_latest.get("grid_power_w") or 0))

        stat = f"Solare: {int(p_solar)} W • Batteria: {int(soc)}%"
        devices.append({
            "id": "aton_storage_hub",
            "raw_id": "aton_storage_hub",
            "ecosystem": "aton",
            "name": "Impianto Solare & Accumulo Aton",
            "icon": "☀️",
            "category": "energy",
            "category_label": "Fotovoltaico & Batteria",
            "is_on": p_solar > 20 or soc > 10,
            "can_toggle": False,
            "is_online": True,
            "status_text": stat,
            "power_w": load,
            "solar_power_w": p_solar,
            "battery_soc_pct": soc,
            "battery_power_w": p_batt,
            "house_load_w": load,
            "grid_power_w": grid,
            "raw": e_latest,
        })

    # 2. Home Assistant (Samsung, LG ThinQ, Tuya, Presenza, Clima, Prese, Luci)
    if settings.HASS_ENABLED and homeassistant_service.enabled:
        for hd in homeassistant_service.get_catalog_devices():
            devices.append(hd)
    elif settings.LG_THINQ_ENABLED:
        # Fallback diretto su cloud LG ThinQ solo se Home Assistant non è attivo
        thinq_devices = thinq_service.get_cached_devices()
        for d in thinq_devices:
            dev_id = d.get("device_id") or d.get("deviceId") or "unknown"
            dev_type = d.get("device_type", "DEVICE_AIR_CONDITIONER")

            if dev_type == "DEVICE_REFRIGERATOR":
                door_open = d.get("door_open", False)
                express_mode = d.get("express_mode", False)
                target_temp = d.get("target_temp", 4)
                status_parts = []
                if door_open:
                    status_parts.append("🔴 Porta Aperta ⚠️")
                else:
                    status_parts.append("🟢 Porta Chiusa")
                status_parts.append(f"Set: {target_temp}°C")
                if express_mode:
                    status_parts.append("Express Cool ❄️")

                devices.append({
                    "id": f"thinq_{dev_id}",
                    "raw_id": dev_id,
                    "ecosystem": "thinq",
                    "name": d.get("alias") or "Frigorifero LG",
                    "icon": "🧊",
                    "category": "appliances",
                    "category_label": "Frigorifero LG ThinQ",
                    "is_on": express_mode,
                    "can_toggle": True,
                    "is_online": d.get("is_online", True),
                    "status_text": " • ".join(status_parts),
                    "power_w": 0.0,
                    "temp_set": target_temp,
                    "door_open": door_open,
                    "express_mode": express_mode,
                    "raw": d,
                })
            elif dev_type == "DEVICE_AIR_CONDITIONER":
                is_on = d.get("is_on", False)
                t_curr = d.get("current_temp")
                t_target = d.get("target_temp")
                mode = d.get("mode") or d.get("job_mode", "COOL")

                status_txt = "Acceso" if is_on else "Spento"
                if is_on and t_curr is not None:
                    status_txt += f" • {t_curr}°C (Set: {t_target}°C)"
                elif t_curr is not None:
                    status_txt += f" • {t_curr}°C"

                devices.append({
                    "id": f"thinq_{dev_id}",
                    "raw_id": dev_id,
                    "ecosystem": "thinq",
                    "name": d.get("alias") or d.get("name", "Climatizzatore LG"),
                    "icon": "❄️" if mode == "COOL" else ("🔥" if mode == "HEAT" else "🌬️"),
                    "category": "climate",
                    "category_label": "Climatizzatore LG ThinQ",
                    "is_on": is_on,
                    "can_toggle": True,
                    "is_online": d.get("is_online", True),
                    "status_text": status_txt,
                    "power_w": 0.0,
                    "temp_current": t_curr,
                    "temp_set": t_target,
                    "job_mode": mode,
                    "fan_speed": d.get("fan_speed", "LOW"),
                    "swing_vertical": d.get("rotate_up_down", False),
                    "swing_horizontal": d.get("rotate_left_right", False),
                    "raw": d,
                })

    # 3. Applica eventuali alias/nomi personalizzati salvati dall'utente
    try:
        device_aliases = get_device_aliases()
    except Exception:
        device_aliases = {}

    for dev in devices:
        raw_id = str(dev.get("raw_id", ""))
        dev_id = str(dev.get("id", ""))
        matched_alias = (
            device_aliases.get(dev_id)
            or device_aliases.get(raw_id)
            or (device_aliases.get(dev_id.replace("tuya_", "")) if dev_id.startswith("tuya_") else None)
            or (device_aliases.get(dev_id.replace("hass_", "")) if dev_id.startswith("hass_") else None)
            or (device_aliases.get(dev_id.replace("thinq_", "")) if dev_id.startswith("thinq_") else None)
            or (device_aliases.get(dev_id.replace("st_", "")) if dev_id.startswith("st_") else None)
        )
        if matched_alias:
            dev["original_name"] = dev.get("original_name") or dev.get("name")
            dev["name"] = matched_alias

    # 4. Associa eventuali timer/programmazioni attive a ciascun dispositivo
    try:
        active_schedules = device_scheduler.get_schedules()
    except Exception:
        active_schedules = []

    schedules_by_device: Dict[str, List[Dict[str, Any]]] = {}
    for s in active_schedules:
        d_raw = str(s.get("device_id", ""))
        if d_raw not in schedules_by_device:
            schedules_by_device[d_raw] = []
        schedules_by_device[d_raw].append(s)

    for dev in devices:
        raw_id = str(dev.get("raw_id", ""))
        dev_id = str(dev.get("id", ""))
        dev_scheds = (
            schedules_by_device.get(raw_id)
            or schedules_by_device.get(dev_id)
            or schedules_by_device.get(f"tuya_{raw_id}")
            or schedules_by_device.get(f"thinq_{raw_id}")
            or schedules_by_device.get(f"st_{raw_id}")
            or schedules_by_device.get(f"hass_{raw_id}")
            or (schedules_by_device.get(dev_id.replace("tuya_", "")) if dev_id.startswith("tuya_") else None)
            or (schedules_by_device.get(dev_id.replace("hass_", "")) if dev_id.startswith("hass_") else None)
            or (schedules_by_device.get(dev_id.replace("thinq_", "")) if dev_id.startswith("thinq_") else None)
            or (schedules_by_device.get(dev_id.replace("st_", "")) if dev_id.startswith("st_") else None)
            or []
        )
        for s in dev_scheds:
            s["device_name"] = dev["name"]
        dev["active_schedules"] = dev_scheds
        dev["active_schedule"] = dev_scheds[0] if dev_scheds else None

    # Statistiche di sintesi
    total_count = len(devices)
    active_count = sum(1 for d in devices if d.get("is_on") is True)
    total_power = sum(d.get("power_w", 0.0) for d in devices if d.get("is_on") is True)
    online_count = sum(1 for d in devices if d.get("is_online", True))

    return {
        "devices": devices,
        "active_schedules": active_schedules,
        "stats": {
            "total": total_count,
            "active": active_count,
            "total_power_w": round(total_power, 1),
            "online": online_count,
            "scheduled_tasks_count": len(active_schedules),
        },
    }


__all__ = ["build_devices_catalog"]
