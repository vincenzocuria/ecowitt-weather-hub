import time
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.config import settings
from backend.alert_engine import engine
from backend.notifier import notifier
from backend.thinq_service import thinq_service
from backend.smartthings_service import smartthings_service
from backend.tuya_service import tuya_service
from backend.database import (
    get_climate_automations_config, save_climate_automations_config,
    get_irrigation_automations_config, save_irrigation_automations_config,
    get_irrigation_learning_summary, log_irrigation_cycle_start,
    get_sensor_aliases, save_sensor_alias,
    get_latest_reading, get_latest_energy, get_recent_rain_totals
)
from backend.analytics import calc_evapotranspiration, evaluate_smart_irrigation
from backend.forecast_service import forecast_service
from backend.aton_service import aton_service
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
    """Invia comandi (Power, Temp, Mode, Fan Speed, Swing) a un condizionatore LG."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
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

# --- Samsung SmartThings Endpoints ---

@router.get("/api/smartthings/summary")
async def api_smartthings_summary():
    """Restituisce il riepilogo in tempo reale di lavatrice, lavastoviglie, presenza e sinergia solare."""
    from backend.routers.weather import build_analytics_context
    latest = get_latest_reading() or {}
    analytics = build_analytics_context(latest)
    energy_latest = aton_service.latest_data or get_latest_energy() or {}
    return smartthings_service.get_summary(energy_latest, analytics.get("drying_index") if analytics else None)

@router.post("/api/smartthings/sync")
@router.get("/api/smartthings/sync")
async def api_smartthings_sync():
    """Forza la risincronizzazione con il cloud Samsung SmartThings."""
    from backend.routers.weather import build_analytics_context
    await smartthings_service.sync_all()
    latest = get_latest_reading() or {}
    analytics = build_analytics_context(latest)
    energy_latest = aton_service.latest_data or get_latest_energy() or {}
    return smartthings_service.get_summary(energy_latest, analytics.get("drying_index") if analytics else None)

@router.post("/api/smartthings/device/{device_id}/command")
async def api_smartthings_command(device_id: str, request: Request):
    """Invia un comando REST (accensione, spegnimento, switch) a un dispositivo SmartThings."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    cap = payload.get("capability", "switch")
    cmd = payload.get("command", "off")
    args = payload.get("arguments", [])
    res = await smartthings_service.execute_command(device_id, cap, cmd, args)
    return {"success": res}

# --- Tuya / Smart Life Endpoints ---

@router.get("/api/tuya/summary")
async def api_tuya_summary():
    """Restituisce il riepilogo in tempo reale di tutti i dispositivi Smart Life (Tuya) abilitati."""
    return tuya_service.get_summary()

@router.post("/api/tuya/sync")
@router.get("/api/tuya/sync")
async def api_tuya_sync():
    """Forza la risincronizzazione con il cloud Tuya."""
    await tuya_service.sync_all()
    return tuya_service.get_summary()

@router.get("/api/tuya/devices")
async def api_tuya_devices():
    """Restituisce tutti i dispositivi rilevati su Tuya con relativo stato di abilitazione."""
    summary = tuya_service.get_summary()
    return {"devices": summary.get("all_devices", []), "enabled_count": summary.get("enabled_devices_count", 0)}

@router.post("/api/tuya/device/{device_id}/toggle")
async def api_tuya_toggle(device_id: str, request: Request):
    """Inverte o imposta lo stato ON/OFF del dispositivo Tuya."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    target_state = payload.get("state")
    res = await tuya_service.toggle_device(device_id, target_state)
    return res

@router.post("/api/tuya/device/{device_id}/command")
async def api_tuya_command(device_id: str, request: Request):
    """Invia un comando avanzato (es: setpoint temperatura, comandi raw) a un dispositivo Tuya."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    commands = payload.get("commands", [])
    if not commands and "temp_c" in payload:
        return await tuya_service.set_thermostat_temp(device_id, float(payload["temp_c"]))
    if not commands and ("action" in payload or "control" in payload):
        return await tuya_service.control_curtain(device_id, payload.get("action") or payload.get("control"))
    return await tuya_service.send_command(device_id, commands)

@router.post("/api/tuya/device/{device_id}/curtain")
async def api_tuya_curtain(device_id: str, request: Request):
    """Invia comandi di apertura/stop/chiusura alla persiana/tenda Tuya."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    action = payload.get("action") or payload.get("control") or "stop"
    return await tuya_service.control_curtain(device_id, action)

@router.post("/api/tuya/device/{device_id}/config")
async def api_tuya_config(device_id: str, request: Request):
    """Salva le impostazioni di abilitazione (ON/OFF visibilità) e nome personalizzato per il dispositivo Tuya."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    enabled = payload.get("enabled", True)
    custom_name = payload.get("custom_name")
    await tuya_service.set_device_enabled(device_id, enabled, custom_name)
    return {"status": "ok", "device_id": device_id, "enabled": enabled, "custom_name": custom_name}

# --- SMART IRRIGATION ENDPOINTS ---

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
    """Restituisce lo stato decisionale e operativo in tempo reale dell'irrigazione."""
    cfg = get_irrigation_automations_config()
    latest_w = get_latest_reading() or {}
    tuya_summary = tuya_service.get_summary() if settings.TUYA_ENABLED else {}
    all_tuya = tuya_summary.get("all_devices") or tuya_summary.get("devices") or []
    
    target_id = cfg.get("target_device_id", "bfeb96waen2hlkvg")
    valve_dev = None
    if target_id and target_id != "auto":
        valve_dev = next((d for d in all_tuya if d.get("id") == target_id), None)
    if not valve_dev:
        valve_dev = next((d for d in all_tuya if d.get("category") == "sfkzq" or d.get("type") == "irrigation"), None)

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

    is_open = valve_dev.get("is_on") is True or valve_dev.get("work_state") in ("watering", "spray", "manual", "auto", "running") if valve_dev else False

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
    target_id = payload.get("device_id") or cfg.get("target_device_id", "bfeb96waen2hlkvg")

    tuya_summary = tuya_service.get_summary() if settings.TUYA_ENABLED else {}
    all_tuya = tuya_summary.get("all_devices") or tuya_summary.get("devices") or []
    valve_dev = None
    if target_id and target_id != "auto":
        valve_dev = next((d for d in all_tuya if d.get("id") == target_id), None)
    if not valve_dev:
        valve_dev = next((d for d in all_tuya if d.get("category") == "sfkzq" or d.get("type") == "irrigation"), None)

    if not valve_dev:
        return JSONResponse(status_code=404, content={"error": "Nessuna elettrovalvola Tuya rilevata o configurata."})

    dev_id = valve_dev.get("id")
    res = await tuya_service.open_irrigation(dev_id, duration_minutes=int(max(1, round(duration_min))))
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
            message=f"Elettrovalvola '{valve_dev.get('name')}' aperta per micro-dose di {duration_min:.1f} minuti. Monitoraggio apprendimento attivo.",
            priority="normal",
            extra_data={"device_id": dev_id, "duration_min": str(duration_min)}
        )
        return {"status": "ok", "message": f"Irrigazione vaso avviata per {duration_min:.1f} minuti. Apprendimento attivo.", "result": res}
    else:
        return JSONResponse(status_code=500, content={"error": "Impossibile aprire la valvola Tuya.", "details": res})

@router.post("/api/irrigation/stop")
async def api_irrigation_stop(request: Request):
    """Arresta immediatamente l'irrigazione."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    
    cfg = get_irrigation_automations_config()
    target_id = payload.get("device_id") or engine.irrigation_active_device_id or cfg.get("target_device_id", "bfeb96waen2hlkvg")

    tuya_summary = tuya_service.get_summary() if settings.TUYA_ENABLED else {}
    all_tuya = tuya_summary.get("all_devices") or tuya_summary.get("devices") or []
    valve_dev = None
    if target_id and target_id != "auto":
        valve_dev = next((d for d in all_tuya if d.get("id") == target_id), None)
    if not valve_dev:
        valve_dev = next((d for d in all_tuya if d.get("category") == "sfkzq" or d.get("type") == "irrigation"), None)

    if not valve_dev:
        return JSONResponse(status_code=404, content={"error": "Nessuna elettrovalvola Tuya rilevata."})

    dev_id = valve_dev.get("id")
    res = await tuya_service.close_irrigation(dev_id)
    now = time.time()
    engine.is_irrigating = False
    engine.last_irrigation_stop_time = now
    engine._save_state()
    notifier.send_alert(
        alert_type="irrigation_manual_stop",
        title=f"🛑 Irrigazione Arrestata",
        message=f"Elettrovalvola '{valve_dev.get('name')}' chiusa con successo.",
        priority="normal",
        extra_data={"device_id": dev_id}
    )
    return {"status": "ok", "message": "Valvola chiusa.", "result": res}

# --- Unified Devices Hub Endpoints ---

def build_devices_catalog() -> Dict[str, Any]:
    """Genera l'elenco normalizzato e aggregato di tutti i dispositivi smart (Tuya, LG ThinQ, SmartThings, Aton Solar)."""
    devices = []
    
    # 1. Tuya / Smart Life
    tuya_summary = tuya_service.get_summary() if settings.TUYA_ENABLED else {}
    tuya_dev_list = tuya_summary.get("enabled_devices") or tuya_summary.get("devices") or []
    for dev in tuya_dev_list:
        c_type = dev.get("type") or dev.get("category_meta", {}).get("type", "generic")
        
        ui_category = "plugs"
        if c_type in ("thermostat",):
            ui_category = "climate"
        elif c_type in ("irrigation",):
            ui_category = "irrigation"
        elif c_type in ("curtain",):
            ui_category = "curtains"
        elif c_type in ("plug", "light"):
            ui_category = "plugs"
        else:
            ui_category = "other"
            
        status_parts = []
        if c_type == "curtain":
            c_state = dev.get("curtain_state")
            if c_state:
                status_parts.append(str(c_state).capitalize())
            else:
                status_parts.append("Pronta")
        elif c_type == "irrigation":
            if dev.get("is_on") is True or dev.get("work_state") in ("watering", "spray", "manual", "auto", "running"):
                status_parts.append("In Irrigazione 💧")
            else:
                status_parts.append("In Standby / Pronta")
            if dev.get("battery_pct") is not None:
                status_parts.append(f"🔋 {dev.get('battery_pct')}%")
        elif dev.get("is_on") is True:
            p_w = dev.get("power_w", 0.0) or 0.0
            if p_w > 0:
                status_parts.append(f"Acceso ({p_w:.1f} W)")
            else:
                status_parts.append("Acceso")
        elif dev.get("is_on") is False:
            status_parts.append("Spento")
        else:
            status_parts.append("Online" if dev.get("online") else "Offline")

        if dev.get("temp_current") is not None:
            status_parts.append(f"{dev.get('temp_current')}°C")

        devices.append({
            "id": f"tuya_{dev.get('id')}",
            "raw_id": dev.get("id"),
            "ecosystem": "tuya",
            "name": dev.get("name", "Dispositivo Tuya"),
            "icon": dev.get("icon") or dev.get("category_meta", {}).get("icon", "🔌"),
            "category": ui_category,
            "category_label": dev.get("type_label") or dev.get("category_meta", {}).get("label", "Smart Life"),
            "is_on": dev.get("is_on"),
            "can_toggle": (c_type != "curtain") and (dev.get("is_on") is not None or c_type in ("plug", "light", "irrigation")),
            "is_online": dev.get("online", True),
            "status_text": " • ".join(status_parts) if status_parts else "Stato Sconosciuto",
            "power_w": dev.get("power_w", 0.0) or 0.0,
            "voltage_v": dev.get("voltage_v"),
            "current_a": dev.get("current_a"),
            "temp_current": dev.get("temp_current"),
            "temp_set": dev.get("temp_set"),
            "battery_pct": dev.get("battery_pct"),
            "work_state": dev.get("work_state"),
            "curtain_state": dev.get("curtain_state"),
            "raw": dev
        })

    # 2. LG ThinQ Dispositivi (Climatizzatori & Frigorifero)
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

    # 3. Samsung SmartThings
    if settings.SMARTTHINGS_ENABLED:
        energy_latest = aton_service.latest_data or get_latest_energy() or {}
        st_summary = smartthings_service.get_summary(energy_latest)
        
        # Lavatrice
        washer = st_summary.get("washer", {})
        if washer and washer.get("is_connected") is not False and washer.get("device_id"):
            is_running = washer.get("is_running", False)
            p_w = washer.get("power_w", 0.0) or 0.0
            devices.append({
                "id": f"st_{washer.get('device_id')}",
                "raw_id": washer.get("device_id"),
                "ecosystem": "smartthings",
                "name": washer.get("name", "Lavatrice Smart"),
                "icon": "🫧",
                "category": "appliances",
                "category_label": "Lavatrice Samsung",
                "is_on": is_running or (washer.get("switch_state") == "on"),
                "can_toggle": bool(washer.get("switch_state")),
                "is_online": True,
                "status_text": washer.get("state_text", "In Standby"),
                "power_w": p_w,
                "completion_time": washer.get("completion_time"),
                "cycle_name": washer.get("cycle_name"),
                "raw": washer
            })
            
        # Lavastoviglie
        dish = st_summary.get("dishwasher", {})
        if dish and dish.get("is_connected") is not False and dish.get("device_id"):
            is_running = dish.get("is_running", False)
            p_w = dish.get("power_w", 0.0) or 0.0
            devices.append({
                "id": f"st_{dish.get('device_id')}",
                "raw_id": dish.get("device_id"),
                "ecosystem": "smartthings",
                "name": dish.get("name", "Lavastoviglie Smart"),
                "icon": "🍽️",
                "category": "appliances",
                "category_label": "Lavastoviglie Samsung",
                "is_on": is_running or (dish.get("switch_state") == "on"),
                "can_toggle": bool(dish.get("switch_state")),
                "is_online": True,
                "status_text": dish.get("state_text", "In Standby"),
                "power_w": p_w,
                "completion_time": dish.get("completion_time"),
                "cycle_name": dish.get("cycle_name"),
                "raw": dish
            })

        # Presenza / Smartphone
        presence = st_summary.get("presence", {})
        if presence and presence.get("device_id"):
            is_present = presence.get("is_present", True)
            batt = presence.get("battery_percent")
            stat = "A Casa 🟢" if is_present else "Fuori Casa 📍"
            if batt is not None:
                stat += f" • {batt}%"
            devices.append({
                "id": f"st_{presence.get('device_id')}",
                "raw_id": presence.get("device_id"),
                "ecosystem": "smartthings",
                "name": presence.get("name", "Smartphone Galaxy"),
                "icon": "📱",
                "category": "presence",
                "category_label": "Sensore Presenza & Posizione",
                "is_on": is_present,
                "can_toggle": False,
                "is_online": True,
                "status_text": stat,
                "power_w": 0.0,
                "battery_pct": batt,
                "is_present": is_present,
                "raw": presence
            })

    # 4. Aton Storage Fotovoltaico & Batteria
    if settings.ATON_ENABLED:
        e_latest = aton_service.latest_data or get_latest_energy() or {}
        p_solar = float(e_latest.get("solar_power_w", 0) or 0)
        p_batt = float(e_latest.get("battery_power_w", 0) or 0)
        soc = float(e_latest.get("battery_soc_pct", 0) or 0)
        load = float(e_latest.get("house_load_w", 0) or 0)
        grid = float(e_latest.get("grid_power_w", 0) or 0)
        
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

    # 5. Associa eventuali timer/programmazioni attive a ciascun dispositivo
    try:
        active_schedules = device_scheduler.get_schedules()
    except Exception:
        active_schedules = []

    schedules_by_device: Dict[str, List[Dict[str, Any]]] = {}
    for s in active_schedules:
        d_raw = s["device_id"]
        if d_raw not in schedules_by_device:
            schedules_by_device[d_raw] = []
        schedules_by_device[d_raw].append(s)

    for dev in devices:
        raw_id = str(dev.get("raw_id"))
        dev_scheds = schedules_by_device.get(raw_id, [])
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

    # 1. Tuya
    if settings.TUYA_ENABLED:
        tuya_summary = tuya_service.get_summary()
        tuya_devs = tuya_summary.get("enabled_devices") or tuya_summary.get("devices") or []
        for dev in tuya_devs:
            c_type = dev.get("type") or dev.get("category_meta", {}).get("type", "generic")
            if c_type in ("plug", "light", "irrigation") and (category in ("all", "plugs")):
                if dev.get("is_on") != target_state:
                    res = await tuya_service.toggle_device(dev.get("id"), target_state)
                    results.append({"name": dev.get("name"), "res": res})

    # 2. LG ThinQ
    if settings.LG_THINQ_ENABLED and (category in ("all", "climate")):
        for d in thinq_service.get_cached_devices():
            if d.get("is_on") != target_state:
                dev_id = d.get("device_id") or d.get("deviceId")
                res = await thinq_service.control_device(dev_id, {"power": target_state})
                results.append({"name": d.get("alias"), "res": res})

    return {"status": "ok", "target_state": target_state, "updated_count": len(results), "details": results}

