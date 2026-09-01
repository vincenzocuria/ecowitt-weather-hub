import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter

from backend.config import settings
from backend.aton_service import aton_service
from backend.database import (
    get_latest_energy, get_today_energy_summary, get_energy_timeseries,
    get_tuya_local_devices, get_device_aliases
)
from backend.thinq_service import thinq_service
from backend.homeassistant_service import homeassistant_service

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
    Aggrega Tuya Cloud, Tuya Local LAN, Home Assistant, SmartThings ed LG con deduplicazione automatica.
    """
    energy_data = aton_service.latest_data or get_latest_energy() or {}
    summary = get_today_energy_summary() or {}

    total_house_w = float(energy_data.get("p_utenze") if energy_data.get("p_utenze") is not None else (energy_data.get("house_load_w") or 0.0))
    total_house_kwh = summary.get("total_house_kwh", "0.0")
    p_solar_w = float(energy_data.get("p_solare") or energy_data.get("solar_power_w") or 0.0)
    p_batt_w = float(energy_data.get("p_batteria") or energy_data.get("battery_power_w") or 0.0)
    p_grid_w = float(energy_data.get("p_rete") or energy_data.get("grid_power_w") or 0.0)

    try:
        aliases = get_device_aliases()
    except Exception:
        aliases = {}

    seen_keys = set()
    active_consumers = []
    standby_devices = []

    def _normalize_dedup_key(entry: Dict[str, Any]) -> str:
        raw_id = str(entry.get("raw_id", "")).lower()
        d_id = str(entry.get("id", "")).lower()
        name = str(entry.get("name", "")).lower()
        c_type = str(entry.get("type", "")).lower()

        if "camera_da_letto" in raw_id or "camera da letto" in name:
            return "climate_camera_da_letto"
        if "cameretta" in raw_id or "cameretta" in name:
            return "climate_cameretta"
        if "cucina" in raw_id or "fujitsu" in raw_id or "fglair" in raw_id or "cucina" in name:
            if c_type == "climate" or "clima" in name or "climate" in raw_id:
                return "climate_cucina"
        if "frigorifero" in raw_id or "fridge" in raw_id or "frigorifero" in name:
            return "appliance_frigorifero"
        if "lavatrice" in raw_id or "washer" in raw_id or "lavatrice" in name:
            return "appliance_lavatrice"
        if "lavastoviglie" in raw_id or "dishwasher" in raw_id or "lavastoviglie" in name:
            return "appliance_lavastoviglie"

        clean_raw = raw_id.replace("tuya_", "").replace("hass_", "").replace("thinq_", "").replace("st_", "")
        return entry.get("dedup_key") or clean_raw or d_id

    def _add_consumer(entry: Dict[str, Any]):
        raw_id = str(entry.get("raw_id", ""))
        d_id = str(entry.get("id", ""))
        clean_raw = raw_id.replace("tuya_", "").replace("hass_", "").replace("thinq_", "").replace("st_", "")

        # Escludi esplicitamente entità non elettriche o puramente sensoriali
        c_type = entry.get("type", "generic")
        if c_type in ("presence", "health", "scale", "sensor", "shutter", "irrigation", "generic") and float(entry.get("power_w") or 0.0) <= 0:
            return

        # Deduplicazione intelligente tra Tuya, Home Assistant e ThinQ
        dedup_key = _normalize_dedup_key(entry)
        if dedup_key in seen_keys:
            # Se abbiamo già registrato questa chiave ma la nuova voce ha potenza > 0 e la precedente no, aggiorna
            p_curr = float(entry.get("power_w") or 0.0)
            if p_curr > 0:
                for idx, existing in enumerate(active_consumers):
                    if _normalize_dedup_key(existing) == dedup_key and float(existing.get("power_w") or 0.0) == 0:
                        active_consumers[idx] = entry
                        return
                for idx, existing in enumerate(standby_devices):
                    if _normalize_dedup_key(existing) == dedup_key and float(existing.get("power_w") or 0.0) == 0:
                        standby_devices.pop(idx)
                        active_consumers.append(entry)
                        return
            return
        seen_keys.add(dedup_key)

        # Applica alias personalizzato se presente
        matched_alias = aliases.get(d_id) or aliases.get(raw_id) or aliases.get(clean_raw)
        if matched_alias:
            entry["name"] = matched_alias

        is_on = entry.get("is_on")
        p_w = float(entry.get("power_w") or 0.0)
        is_running = entry.get("is_running", False)

        # Trattamento climatizzatori attivi senza wattmetro dedicato
        if c_type in ("climate", "thermostat") and is_on is True:
            if p_w <= 0.0:
                entry["is_unmetered_active"] = True
                if "Incluso nel totale casa" not in entry.get("status_text", ""):
                    entry["status_text"] = f"{entry.get('status_text', '')} • Carico nel totale casa".strip(" •")
            active_consumers.append(entry)
        elif p_w > 1.0:
            # Qualsiasi dispositivo con assorbimento reale > 1 W è un consumatore attivo
            active_consumers.append(entry)
        elif is_running is True:
            # Elettrodomestici in ciclo anche con potenza non ancora rilevata
            entry["is_unmetered_active"] = True
            active_consumers.append(entry)
        else:
            # Prese con 0 W, luci spente, carichi a riposo
            standby_devices.append(entry)

    # 1. Dispositivi Home Assistant (Prese smart, Elettrodomestici Samsung, Valvole, Clima)
    if settings.HASS_ENABLED and homeassistant_service.enabled:
        for hd in homeassistant_service.get_catalog_devices():
            hd_cat = hd.get("category", "")
            # Esclusione sensori biometrici, presenza e salute
            if hd_cat in ("presence", "health", "scale", "sensor"):
                continue

            p_w = float(hd.get("power_w") or 0.0)
            is_on = hd.get("is_on")
            is_running = hd.get("raw", {}).get("is_running", False) if isinstance(hd.get("raw"), dict) else False

            if hd_cat == "appliances":
                c_type = "appliance"
            elif hd_cat == "climate":
                c_type = "climate"
            elif hd_cat in ("shutters", "irrigation"):
                c_type = "shutter" if hd_cat == "shutters" else "irrigation"
            elif hd_cat == "plugs":
                c_type = "plug"
            else:
                c_type = "generic"

            _add_consumer({
                "id": hd.get("id"),
                "raw_id": hd.get("raw_id"),
                "dedup_key": str(hd.get("raw_id")),
                "ecosystem": "homeassistant",
                "name": hd.get("name"),
                "icon": hd.get("icon", "🔌"),
                "category_label": hd.get("category_label", "Home Assistant"),
                "type": c_type,
                "is_on": is_on,
                "is_running": is_running,
                "can_toggle": hd.get("can_toggle", False),
                "power_w": p_w,
                "voltage_v": None,
                "current_a": None,
                "status_text": hd.get("status_text", "")
            })

    # 2. Climatizzatori LG ThinQ
    if settings.LG_THINQ_ENABLED:
        thinq_devs = thinq_service.get_cached_devices()
        for d in thinq_devs:
            d_type = d.get("device_type")
            if d_type not in ("DEVICE_AIR_CONDITIONER", "DEVICE_THERMOSTAT", "AIR_CONDITIONER"):
                continue

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

            _add_consumer({
                "id": f"thinq_{d.get('device_id') or d.get('deviceId')}",
                "raw_id": d.get("device_id") or d.get("deviceId"),
                "dedup_key": f"thinq_{d.get('device_id') or d.get('deviceId')}",
                "ecosystem": "thinq",
                "name": d.get("alias") or d.get("name", "Climatizzatore LG"),
                "icon": "❄️" if mode == "COOL" else ("🔥" if mode == "HEAT" else "🌬️"),
                "category_label": "Climatizzatore LG ThinQ",
                "type": "climate",
                "is_on": is_on,
                "can_toggle": True,
                "power_w": 0.0,
                "status_text": " • ".join(stat_parts)
            })

    # Calcolo totali e quote
    monitored_power_w = sum(d.get("power_w", 0.0) for d in active_consumers)
    monitored_power_w = round(monitored_power_w, 1)

    unmonitored_power_w = max(0.0, total_house_w - monitored_power_w)
    unmonitored_power_w = round(unmonitored_power_w, 1)

    for d in active_consumers:
        p = d.get("power_w", 0.0)
        d["percent_of_total"] = min(100.0, round((p / total_house_w * 100), 1)) if total_house_w > 0 and p > 0 else 0.0

    active_consumers.sort(key=lambda x: (x.get("power_w", 0.0), 1 if x.get("is_running") or x.get("is_on") else 0), reverse=True)

    monitored_pct = min(100.0, round((monitored_power_w / total_house_w * 100), 1)) if total_house_w > 0 else 0.0
    unmonitored_pct = max(0.0, round(100.0 - monitored_pct, 1)) if total_house_w > 0 else 0.0

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
