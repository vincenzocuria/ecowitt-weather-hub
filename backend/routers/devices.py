import time
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.config import settings
from backend.alert_engine import engine
from backend.notifier import notifier
from backend.thinq_service import thinq_service
from backend.database import (
    get_climate_automations_config, save_climate_automations_config,
    get_irrigation_automations_config, save_irrigation_automations_config,
    get_irrigation_learning_summary, log_irrigation_cycle_start,
    get_sensor_aliases, save_sensor_alias,
    get_device_aliases, save_device_alias, delete_device_alias,
    get_latest_reading, get_latest_energy, get_recent_rain_totals,
    get_tuya_local_devices, get_tuya_local_device, save_tuya_local_device, delete_tuya_local_device,
    save_tuya_device_config
)
from backend.analytics import calc_evapotranspiration, evaluate_smart_irrigation
from backend.forecast_service import forecast_service
from backend.aton_service import aton_service
from backend.homeassistant_service import homeassistant_service
from backend.device_scheduler import device_scheduler

logger = logging.getLogger("weather_hub")

router = APIRouter(tags=["Devices & Smart Home"])

# --- GESTIONE ALIAS SENSORI PERSONALIZZATI ---

@router.get("/api/sensors/aliases")
async def api_get_sensor_aliases():
    """Restituisce i nomi personalizzati assegnati ai canali dei sensori."""
    return {"aliases": get_sensor_aliases()}

@router.post("/api/sensors/aliases")
async def api_save_sensor_alias(request: Request):
    """Salva o aggiorna il nome di un canale sensore (es: soil_ch1 -> 'Giardino')."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    sensor_id = data.get("sensor_id")
    alias = data.get("alias", "")
    if not sensor_id:
        return JSONResponse({"error": "ID sensore mancante"}, status_code=400)
    save_sensor_alias(sensor_id, alias)
    return {"status": "saved", "sensor_id": sensor_id, "alias": alias, "aliases": get_sensor_aliases()}

# --- LG ThinQ Climatizzazione Endpoints ---

@router.get("/api/thinq/devices")
async def api_thinq_devices():
    """Restituisce la lista e lo stato in tempo reale dei dispositivi LG ThinQ."""
    devices = thinq_service.get_cached_devices()
    if not devices and settings.LG_THINQ_ENABLED and settings.LG_THINQ_PAT:
        devices = await thinq_service.fetch_all_devices()
    return {
        "enabled": settings.LG_THINQ_ENABLED,
        "connected": thinq_service.is_connected,
        "devices": devices
    }

@router.post("/api/thinq/device/{device_id}/control")
async def api_thinq_control(device_id: str, request: Request):
    """Invia comandi (Power, Temp, Mode, Fan Speed, Swing) a un condizionatore LG o dispositivo Home Assistant."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    # 1. Se il dispositivo corrisponde a un'entità Home Assistant (es. climate.camera_da_letto o frigorifero)
    clean_id = device_id
    if clean_id.startswith("thinq_"):
        clean_id = clean_id[6:]
    if clean_id.startswith("hass_"):
        clean_id = clean_id[5:]

    ha_entities = homeassistant_service.entities
    matched_ha_id = None
    if clean_id in ha_entities:
        matched_ha_id = clean_id
    elif f"climate.{clean_id}" in ha_entities:
        matched_ha_id = f"climate.{clean_id}"
    elif clean_id in ("frigorifero", "fridge"):
        matched_ha_id = "switch.frigorifero_express_mode"

    if matched_ha_id and homeassistant_service.enabled:
        results = []
        if "power" in payload:
            is_on = payload["power"] in (True, "POWER_ON", "on", "1")
            res = await homeassistant_service.toggle_device(matched_ha_id, is_on)
            results.append({"power": is_on, "res": res})
        if "mode" in payload:
            m = str(payload["mode"]).lower()
            res = await homeassistant_service.set_climate_hvac_mode(matched_ha_id, m)
            results.append({"mode": m, "res": res})
        if "target_temp" in payload or "temperature" in payload:
            t = float(payload.get("target_temp", payload.get("temperature")))
            res = await homeassistant_service.set_climate_temp(matched_ha_id, t)
            results.append({"target_temp": t, "res": res})
        if "fan_speed" in payload or "wind_strength" in payload:
            f_speed = str(payload.get("fan_speed", payload.get("wind_strength"))).lower()
            res = await homeassistant_service.set_climate_fan_mode(matched_ha_id, f_speed)
            results.append({"fan_speed": f_speed, "res": res})
        if "express_mode" in payload or "expressMode" in payload:
            exp_on = bool(payload.get("express_mode", payload.get("expressMode")))
            res = await homeassistant_service.toggle_device("switch.frigorifero_express_mode", exp_on)
            results.append({"express_mode": exp_on, "res": res})
        return {"status": "success", "device_id": device_id, "actions": results, "ecosystem": "homeassistant"}

    # 2. Fallback diretto su ThinQ Cloud API
    return await thinq_service.control_device(device_id, payload)


@router.post("/api/thinq/sync")
@router.get("/api/thinq/sync")
async def api_thinq_sync():
    """Forza la risincronizzazione con il cloud LG ThinQ."""
    devices = await thinq_service.fetch_all_devices()
    return {"status": "synced", "connected": thinq_service.is_connected, "devices": devices}

# --- LG ThinQ Climate Automations Endpoints ---

@router.get("/api/climate/automations/config")
async def api_get_climate_automations_config():
    """Restituisce la configurazione attuale delle automazioni intelligenti climatizzatori."""
    cfg = get_climate_automations_config()
    devices = thinq_service.get_cached_devices() if settings.LG_THINQ_ENABLED else []
    return {
        "config": cfg,
        "thinq_enabled": settings.LG_THINQ_ENABLED,
        "thinq_connected": thinq_service.is_connected,
        "devices": devices
    }

@router.post("/api/climate/automations/config")
async def api_save_climate_automations_config(request: Request):
    """Salva le preferenze delle automazioni dei climatizzatori."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    saved = save_climate_automations_config(payload)
    return {"status": "success", "config": saved}

@router.post("/api/climate/automations/test-action")
async def api_test_climate_automation(request: Request):
    """Invia una notifica di test per verificare la ricezione su Web Push e ntfy."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    scenario = payload.get("scenario", "away")
    
    if scenario == "away":
        notifier.send_alert(
            alert_type="climate_away_reminder",
            title="🧪 TEST: Clima Acceso all'Uscita",
            message="🚗 [TEST] Sei uscito di casa ma il climatizzatore 'Soggiorno' è rimasto ACCESO (24°C). Se non c'è nessuno a casa puoi spegnerlo da qui.",
            priority="normal"
        )
    elif scenario == "night":
        notifier.send_alert(
            alert_type="climate_night_cooling",
            title="🧪 TEST: Free Cooling Notturno",
            message="🌙 [TEST] All'esterno la temperatura è scesa a 21.5°C (più fresco della stanza a 25.0°C). Puoi spegnere il clima e aprire le finestre a costo zero.",
            priority="normal"
        )
    elif scenario == "solar":
        notifier.send_alert(
            alert_type="climate_solar_opportunity",
            title="🧪 TEST: Pre-Raffrescamento Solare",
            message="☀️ [TEST] Surplus solare a 2400 W e batteria al 95%: momento ideale per avviare il climatizzatore gratis!",
            priority="normal"
        )
    elif scenario == "runtime":
        notifier.send_alert(
            alert_type="climate_runtime_warning",
            title="🧪 TEST: Max Runtime Guard",
            message="⏱️ [TEST] Il climatizzatore 'Camera' è acceso da oltre 5 ore (Temp stanza: 24.5°C).",
            priority="normal"
        )
    return {"status": "sent", "scenario": scenario}

# --- Samsung & Smart Home Summary Endpoints (Powered by Home Assistant) ---

@router.get("/api/smartthings/summary")
async def api_smartthings_summary():
    """Restituisce il riepilogo in tempo reale di lavatrice, lavastoviglie, presenza e sinergia solare da Home Assistant."""
    from backend.routers.weather import build_analytics_context
    latest = get_latest_reading() or {}
    analytics = build_analytics_context(latest)
    energy_latest = aton_service.latest_data or get_latest_energy() or {}
    return homeassistant_service.get_summary(energy_latest, analytics.get("drying_index") if analytics else None)

@router.post("/api/smartthings/sync")
@router.get("/api/smartthings/sync")
async def api_smartthings_sync():
    """Forza la risincronizzazione degli stati locali da Home Assistant."""
    from backend.routers.weather import build_analytics_context
    await homeassistant_service.fetch_states()
    latest = get_latest_reading() or {}
    analytics = build_analytics_context(latest)
    energy_latest = aton_service.latest_data or get_latest_energy() or {}
    return homeassistant_service.get_summary(energy_latest, analytics.get("drying_index") if analytics else None)

@router.post("/api/smartthings/device/{device_id}/command")
async def api_smartthings_command(device_id: str, request: Request):
    """Invia un comando a un dispositivo tramite Home Assistant."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    cmd = payload.get("command", "off")
    target_state = (cmd == "on")
    res = await homeassistant_service.toggle_device(device_id, target_state)
    return res

# --- Dispositivi Smart / Tuya Endpoints (Powered by Home Assistant) ---

@router.get("/api/tuya/summary")
async def api_tuya_summary():
    """Restituisce il riepilogo dei dispositivi tramite Home Assistant."""
    return homeassistant_service.get_summary()

@router.post("/api/tuya/sync")
@router.get("/api/tuya/sync")
async def api_tuya_sync():
    """Forza la risincronizzazione con Home Assistant."""
    await homeassistant_service.fetch_states()
    return homeassistant_service.get_summary()

@router.get("/api/tuya/devices")
async def api_tuya_devices():
    """Restituisce tutti i dispositivi rilevati su Home Assistant."""
    devs = homeassistant_service.get_catalog_devices()
    return {"devices": devs, "enabled_count": len(devs)}

@router.post("/api/tuya/device/{device_id}/toggle")
async def api_tuya_toggle(device_id: str, request: Request):
    """Inverte o imposta lo stato ON/OFF del dispositivo tramite Home Assistant."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    target_state = payload.get("state", True)
    return await homeassistant_service.toggle_device(device_id, target_state)

@router.post("/api/tuya/device/{device_id}/command")
async def api_tuya_command(device_id: str, request: Request):
    """Invia un comando a un dispositivo tramite Home Assistant."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if "temp_c" in payload:
        return await homeassistant_service.set_climate_temp(device_id, float(payload["temp_c"]))
    action = payload.get("action") or payload.get("control")
    if action:
        return await homeassistant_service.control_cover(device_id, action)
    target_state = payload.get("state", True)
    return await homeassistant_service.toggle_device(device_id, target_state)

@router.post("/api/tuya/device/{device_id}/curtain")
async def api_tuya_curtain(device_id: str, request: Request):
    """Invia comandi di apertura/stop/chiusura alla persiana/tenda tramite Home Assistant."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    action = payload.get("action") or payload.get("control") or "stop"
    return await homeassistant_service.control_cover(device_id, action)

@router.post("/api/tuya/device/{device_id}/config")
async def api_tuya_config(device_id: str, request: Request):
    """Salva le impostazioni per il dispositivo."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    enabled = payload.get("enabled", True)
    custom_name = payload.get("custom_name")
    return {"status": "ok", "device_id": device_id, "enabled": enabled, "custom_name": custom_name}

# --- SMART IRRIGATION ENDPOINTS (POWERED BY HOME ASSISTANT) ---

@router.get("/api/irrigation/config")
async def api_get_irrigation_config():
    """Restituisce la configurazione attuale dell'irrigazione intelligente."""
    cfg = get_irrigation_automations_config()
    return {"config": cfg}

@router.post("/api/irrigation/config")
async def api_save_irrigation_config(request: Request):
    """Salva la configurazione dell'irrigazione intelligente."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    updated = save_irrigation_automations_config(payload)
    return {"status": "ok", "config": updated}

@router.get("/api/irrigation/status")
async def api_get_irrigation_status():
    """Restituisce lo stato decisionale e operativo in tempo reale dell'irrigazione da Home Assistant."""
    cfg = get_irrigation_automations_config()
    latest_w = get_latest_reading() or {}
    ha_summary = homeassistant_service.get_summary()
    irrigation_info = ha_summary.get("irrigation", {})
    valves = irrigation_info.get("valves", [])
    
    target_id = cfg.get("target_device_id", "valve.aiuola_valve")
    if target_id == "auto" or not target_id:
        target_id = "valve.aiuola_valve"
    valve_dev = next((v for v in valves if v.get("id") == target_id), None)
    if not valve_dev and valves:
        valve_dev = valves[0]
    if not valve_dev:
        valve_dev = {"id": "valve.aiuola_valve", "name": "Elettrovalvola Aiuola", "state": "closed"}

    # Parametri agrometeo
    soil_ch = cfg.get("soil_moisture_channel", "ch1")
    soil_data = latest_w.get("soil_moisture") or {}
    soil_pct = soil_data.get(soil_ch)
    if soil_pct is None and soil_data:
        soil_pct = next(iter(soil_data.values()), None)

    fc_rain = 0.0
    try:
        fc_data = forecast_service.fetch_open_meteo() or {}
        fc_rain = float(fc_data.get("rain_24h_sum", 0.0) or 0.0)
    except Exception:
        pass

    recent_rain = 0.0
    try:
        rr = get_recent_rain_totals() or {}
        recent_rain = float(rr.get("rain_48h", 0.0) or 0.0)
    except Exception:
        pass

    et_mm = calc_evapotranspiration(latest_w.get("temp_c"), latest_w.get("humidity", 50.0), latest_w.get("solar_radiation"))
    advice = evaluate_smart_irrigation(
        soil_moisture_pct=soil_pct,
        temp_c=latest_w.get("temp_c"),
        solar_rad=latest_w.get("solar_radiation"),
        rain_forecast_24h_mm=fc_rain,
        recent_rain_48h_mm=recent_rain,
        et_mm=et_mm,
        dry_threshold=float(cfg.get("soil_dry_threshold", 48.0)),
        target_threshold=float(cfg.get("soil_target_threshold", 75.0)),
        crop_label=str(cfg.get("crop_label", "Aiuola Orto: Pomodori & Zucchine 🍅🥒"))
    )

    is_open = valve_dev.get("state") == "open" or engine.is_irrigating

    return {
        "config": cfg,
        "valve_device": valve_dev,
        "valve_is_open": is_open,
        "is_irrigating": engine.is_irrigating,
        "irrigation_started_at": engine.irrigation_started_at,
        "planned_duration_min": engine.irrigation_planned_duration_min,
        "soil_moisture_pct": soil_pct,
        "soil_channel": soil_ch,
        "et_mm": et_mm,
        "rain_forecast_24h_mm": fc_rain,
        "recent_rain_48h_mm": recent_rain,
        "advice": advice,
        "learning_summary": get_irrigation_learning_summary()
    }

@router.post("/api/irrigation/start")
async def api_irrigation_start(request: Request):
    """Avvia un ciclo di irrigazione manuale / test con durata personalizzata (default 2 min)."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    
    cfg = get_irrigation_automations_config()
    duration_min = float(payload.get("duration_minutes") or cfg.get("duration_minutes", 2.0))
    target_id = payload.get("device_id") or cfg.get("target_device_id", "valve.aiuola_valve")
    if target_id == "auto" or not target_id:
        target_id = "valve.aiuola_valve"

    dev_id = target_id
    dev_name = "Elettrovalvola Aiuola"
    res = await homeassistant_service.open_irrigation(dev_id, duration_minutes=int(max(1, round(duration_min))))
    if res.get("success"):
        now = time.time()
        engine.is_irrigating = True
        engine.irrigation_started_at = now
        engine.last_irrigation_start_time = now
        engine.irrigation_planned_duration_min = duration_min
        engine.irrigation_active_device_id = dev_id
        
        # Registra ciclo di test per apprendimento percolazione
        latest_w = get_latest_reading() or {}
        soil_ch = cfg.get("soil_moisture_channel", "ch1")
        soil_pct = (latest_w.get("soil_moisture") or {}).get(soil_ch)
        if soil_pct is not None:
            et_mm = calc_evapotranspiration(latest_w.get("temp_c"), latest_w.get("humidity", 50.0), latest_w.get("solar_radiation"))
            cid = log_irrigation_cycle_start(duration_min, float(soil_pct), latest_w.get("temp_c"), et_mm)
            engine.active_learning_cycle_id = cid
            engine.learning_monitoring_until = now + (60 * 60) # 60 minuti di monitoraggio percolazione

        engine._save_state()
        notifier.send_alert(
            alert_type="irrigation_manual_start",
            title=f"💧 Irrigazione Vaso Avviata ({duration_min:.1f} min)",
            message=f"Elettrovalvola '{dev_name}' aperta per micro-dose di {duration_min:.1f} minuti. Monitoraggio apprendimento attivo.",
            priority="normal",
            extra_data={"device_id": dev_id, "duration_min": str(duration_min)}
        )
        return {"status": "ok", "message": f"Irrigazione vaso avviata per {duration_min:.1f} minuti. Apprendimento attivo.", "result": res}
    else:
        return JSONResponse(status_code=500, content={"error": "Impossibile aprire la valvola su Home Assistant.", "details": res})

@router.post("/api/irrigation/stop")
async def api_irrigation_stop(request: Request):
    """Arresta immediatamente l'irrigazione su Home Assistant."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    
    cfg = get_irrigation_automations_config()
    target_id = payload.get("device_id") or engine.irrigation_active_device_id or cfg.get("target_device_id", "valve.aiuola_valve")
    if target_id == "auto" or not target_id:
        target_id = "valve.aiuola_valve"

    dev_id = target_id
    dev_name = "Elettrovalvola Aiuola"
    res = await homeassistant_service.close_irrigation(dev_id)
    now = time.time()
    engine.is_irrigating = False
    engine.last_irrigation_stop_time = now
    engine._save_state()
    notifier.send_alert(
        alert_type="irrigation_manual_stop",
        title=f"🛑 Irrigazione Arrestata",
        message=f"Elettrovalvola '{dev_name}' chiusa con successo.",
        priority="normal",
        extra_data={"device_id": dev_id}
    )
    return {"status": "ok", "message": "Valvola chiusa.", "result": res}

# --- Unified Devices Hub Endpoints ---

def build_devices_catalog() -> Dict[str, Any]:
    """Genera l'elenco normalizzato e aggregato di tutti i dispositivi smart (LG ThinQ, Aton Solar, Home Assistant)."""
    devices = []

    # 1. LG ThinQ Dispositivi (Climatizzatori & Frigorifero)
    thinq_devices = thinq_service.get_cached_devices() if settings.LG_THINQ_ENABLED else []
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
                "raw": d
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
                "raw": d
            })

    # 2. Aton Storage Fotovoltaico & Batteria
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
            "raw": e_latest
        })

    # 3. Home Assistant (Hub Domotico Locale: Samsung Lavatrice/Lavastoviglie/Presenza + Prese, Valvole, Clima, Luci)
    if settings.HASS_ENABLED and homeassistant_service.enabled:
        for hd in homeassistant_service.get_catalog_devices():
            devices.append(hd)

    # 4. Applica eventuali alias/nomi personalizzati salvati dall'utente
    try:
        device_aliases = get_device_aliases()
    except Exception:
        device_aliases = {}

    for dev in devices:
        raw_id = str(dev.get("raw_id", ""))
        dev_id = str(dev.get("id", ""))
        # Match per ID normalizzato o raw_id
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

    # 7. Associa eventuali timer/programmazioni attive a ciascun dispositivo
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
        # Sincronizza il nome del dispositivo nelle notifiche/schedules
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
            "scheduled_tasks_count": len(active_schedules)
        }
    }

@router.get("/api/devices/all")
async def api_devices_all():
    """Restituisce la lista aggregata e normalizzata di tutti i dispositivi smart."""
    return build_devices_catalog()

# --- Nomi Personalizzati / Alias Dispositivi Endpoints ---

@router.get("/api/devices/aliases")
async def api_get_device_aliases():
    """Restituisce la mappa di tutti gli alias personalizzati assegnati ai dispositivi."""
    return {"aliases": get_device_aliases()}

@router.post("/api/devices/rename")
@router.post("/api/devices/{device_id}/rename")
async def api_rename_device(request: Request, device_id: Optional[str] = None):
    """Rinomina o assegna un alias personalizzato a un qualsiasi dispositivo smart (Tuya, HA, LG ThinQ, SmartThings, Aton)."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    target_id = str(device_id or payload.get("device_id") or "").strip()
    alias = str(payload.get("alias") or payload.get("name") or "").strip()
    ecosystem = str(payload.get("ecosystem") or "").lower()

    if not target_id:
        return JSONResponse({"error": "ID dispositivo mancante"}, status_code=400)

    # Salva l'alias sia sull'ID fornito che sull'eventuale raw_id
    save_device_alias(target_id, alias)
    
    # Se il target_id ha prefisso tuya_ / thinq_ / st_ / hass_, salva anche la chiave raw
    for prefix in ("tuya_", "thinq_", "st_", "hass_"):
        if target_id.startswith(prefix):
            raw_k = target_id.replace(prefix, "")
            save_device_alias(raw_k, alias)

    catalog = build_devices_catalog()
    return {
        "status": "ok",
        "device_id": target_id,
        "alias": alias,
        "aliases": get_device_aliases(),
        "devices": catalog["devices"]
    }

# --- Programmazione & Timer Dispositivi Endpoints ---

@router.get("/api/devices/schedules")
async def api_get_schedules(device_id: Optional[str] = None):
    """Restituisce l'elenco delle programmazioni e timer attivi (o filtrati per dispositivo)."""
    schedules = device_scheduler.get_schedules(device_id)
    return {"schedules": schedules, "count": len(schedules)}

@router.post("/api/devices/schedule")
async def api_create_schedule(request: Request):
    """Crea una nuova programmazione / timer di accensione o spegnimento."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
        
    ecosystem = payload.get("ecosystem", "tuya")
    device_id = payload.get("device_id")
    device_name = payload.get("device_name") or "Dispositivo Smart"
    action = payload.get("action", "turn_off")  # turn_on | turn_off
    delay_minutes = payload.get("delay_minutes")
    target_time_iso = payload.get("target_time_iso")
    extra_payload = payload.get("payload") or {}

    if not device_id:
        return JSONResponse({"error": "ID dispositivo mancante"}, status_code=400)
        
    try:
        task = device_scheduler.create_schedule(
            ecosystem=ecosystem,
            device_id=device_id,
            device_name=device_name,
            action=action,
            delay_minutes=delay_minutes,
            target_time_iso=target_time_iso,
            payload=extra_payload
        )
        return {"status": "ok", "task": task}
    except Exception as e:
        logger.error(f"Errore creazione timer/schedule: {e}")
        return JSONResponse({"error": str(e)}, status_code=400)

@router.delete("/api/devices/schedule/{task_id}")
async def api_cancel_schedule(task_id: str):
    """Annulla una programmazione / timer pendente."""
    success = device_scheduler.cancel_schedule(task_id)
    if success:
        return {"status": "cancelled", "task_id": task_id}
    return JSONResponse({"error": "Task non trovato o già eseguito/annullato"}, status_code=404)

@router.post("/api/devices/turn-all")
async def api_devices_turn_all(request: Request):
    """Accende o spegne in blocco tutti i dispositivi commutabili (Prese, Luci, Clima)."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    
    target_state = payload.get("state", False)
    category = payload.get("category", "all")
    results = []

    # 1. Home Assistant (Prese, Luci, Elettrovalvole)
    if settings.HASS_ENABLED and homeassistant_service.enabled:
        for hd in homeassistant_service.get_catalog_devices():
            cat = hd.get("category")
            if cat in ("plugs", "lighting", "irrigation") and (category in ("all", "plugs")):
                if hd.get("is_on") != target_state and hd.get("can_toggle"):
                    res = await homeassistant_service.toggle_device(hd.get("raw_id"), target_state)
                    results.append({"name": hd.get("name"), "res": res})

    # 2. LG ThinQ
    if settings.LG_THINQ_ENABLED and (category in ("all", "climate")):
        for d in thinq_service.get_cached_devices():
            if d.get("is_on") != target_state:
                dev_id = d.get("device_id") or d.get("deviceId")
                res = await thinq_service.control_device(dev_id, {"power": target_state})
                results.append({"name": d.get("alias"), "res": res})

    return {"status": "ok", "target_state": target_state, "updated_count": len(results), "details": results}

# --- TUYA LOCAL API (Zero Cloud LAN Management) ---

@router.get("/api/tuya/local/devices")
async def api_get_tuya_local_devices():
    """Restituisce la lista dei dispositivi Tuya configurati per il controllo locale LAN."""
    return {"devices": get_tuya_local_devices()}

@router.post("/api/tuya/local/device")
async def api_save_tuya_local_device(request: Request):
    """Salva o aggiorna un dispositivo Tuya per il controllo locale LAN."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Payload non valido"}, status_code=400)

    device_id = body.get("device_id")
    name = body.get("name") or "Dispositivo Tuya"
    local_key = body.get("local_key")
    ip_address = body.get("ip_address")
    version = body.get("version") or "3.3"
    category = body.get("category") or "cz"

    if not device_id or not local_key:
        return JSONResponse({"error": "ID dispositivo e Local Key sono obbligatori"}, status_code=400)

    save_tuya_local_device(device_id, name, local_key, ip_address, version, category)
    return {"status": "ok", "device_id": device_id}

@router.delete("/api/tuya/local/device/{device_id}")
async def api_delete_tuya_local_device(device_id: str):
    """Elimina un dispositivo dalla configurazione locale."""
    success = delete_tuya_local_device(device_id)
    return {"status": "ok" if success else "not_found"}

@router.post("/api/tuya/local/scan")
async def api_scan_tuya_lan():
    """Esegue una scansione veloce della subnet locale per trovare dispositivi Tuya su porta 6668."""
    found = await tuya_service.scan_lan_devices()
    return {"status": "ok", "found_devices": found, "count": len(found)}

@router.post("/api/tuya/local/import-cloud-keys")
async def api_import_tuya_cloud_keys():
    """Scarica e salva permanentemente in locale tutte le local_key dei dispositivi dal Cloud Tuya."""
    res = await tuya_service.import_keys_from_cloud()
    return res

# --- HOME ASSISTANT API (Hub Domotico Locale) ---

@router.get("/api/homeassistant/status")
async def api_get_homeassistant_status():
    """Restituisce lo stato di connessione e presenza di Home Assistant locale."""
    is_ok = await homeassistant_service.check_connection()
    return {
        "enabled": homeassistant_service.enabled,
        "is_connected": is_ok,
        "url": settings.HASS_URL,
        "entities_count": len(homeassistant_service.entities),
        "error": homeassistant_service.sync_error
    }

@router.get("/api/homeassistant/states")
async def api_get_homeassistant_states():
    """Recupera tutti gli stati attuali delle entità di Home Assistant."""
    states = await homeassistant_service.fetch_states()
    return {"states": states, "count": len(states)}

@router.post("/api/homeassistant/device/{entity_id}/toggle")
async def api_homeassistant_toggle_device(entity_id: str, request: Request):
    """Accende o spegne un'entità Home Assistant."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    target_state = payload.get("state", True)
    res = await homeassistant_service.toggle_device(entity_id, target_state)
    return res

@router.post("/api/homeassistant/service")
async def api_homeassistant_call_service(request: Request):
    """Chiama un servizio generico Home Assistant (es. light.turn_on, climate.set_temperature)."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Payload JSON non valido"}, status_code=400)
    domain = body.get("domain")
    service = body.get("service")
    entity_id = body.get("entity_id")
    data = body.get("data") or {}
    if not domain or not service or not entity_id:
        return JSONResponse({"error": "domain, service e entity_id sono obbligatori"}, status_code=400)
    res = await homeassistant_service.call_service(domain, service, entity_id, data)
    return res



