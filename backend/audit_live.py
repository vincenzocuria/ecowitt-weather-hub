import os
import sys
import json
import time
import asyncio
from datetime import datetime, timezone

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import settings

async def run_audit():
    print("=" * 60)
    print("🔬 AUDIT DIAGNOSTICO COMPLETO DISPOSITIVI & SERVIZI LIVE")
    print("=" * 60)
    
    results = {}
    
    # 1. Ecowitt Weather Station
    print("\n1. Controllo Stazione Meteo Ecowitt / Sainlogic...")
    try:
        from backend.database import get_latest_reading, get_station_status
        latest = get_latest_reading()
        stat = get_station_status()
        if latest:
            results["ecowitt"] = {
                "status": "ONLINE 🟢" if stat.get("is_online") else "OFFLINE ⚪",
                "temp_c": latest.get("temp_c"),
                "humidity": latest.get("humidity"),
                "pressure_rel_hpa": latest.get("pressure_rel_hpa"),
                "wind_speed_kmh": latest.get("wind_speed_kmh"),
                "solar_rad_wm2": latest.get("solar_rad_wm2"),
                "uv_index": latest.get("uv_index"),
                "last_seen": stat.get("last_seen")
            }
            print(f"   ✅ Ecowitt OK: {latest.get('temp_c')}°C, {latest.get('humidity')}%, {latest.get('pressure_rel_hpa')} hPa (Stato: {results['ecowitt']['status']})")
        else:
            results["ecowitt"] = {"status": "NO_DATA ⚠️"}
            print("   ⚠️ Nessun dato meteo recente nel database.")
    except Exception as e:
        results["ecowitt"] = {"status": "ERROR ❌", "error": str(e)}
        print(f"   ❌ Errore Ecowitt: {e}")

    # 2. Aton Storage Solar
    print("\n2. Controllo Fotovoltaico & Batteria Aton Storage...")
    try:
        from backend.aton_service import aton_service
        from backend.database import get_latest_energy
        aton_data = aton_service.latest_data or get_latest_energy() or {}
        is_conn = aton_service.is_connected
        if settings.ATON_ENABLED:
            results["aton"] = {
                "enabled": True,
                "connected": is_conn,
                "solar_power_w": aton_data.get("solar_power_w", 0.0),
                "battery_soc_pct": aton_data.get("battery_soc_pct", 0.0),
                "house_load_w": aton_data.get("house_load_w", 0.0),
                "grid_power_w": aton_data.get("grid_power_w", 0.0),
                "last_update": aton_data.get("timestamp")
            }
            print(f"   ✅ Aton Solar OK: FV {results['aton']['solar_power_w']} W, Batteria {results['aton']['battery_soc_pct']}%, Carico Casa {results['aton']['house_load_w']} W (Rete: {results['aton']['grid_power_w']} W)")
        else:
            results["aton"] = {"enabled": False, "status": "DISABILITATO"}
            print("   ⚪ Aton Storage disabilitato da config.")
    except Exception as e:
        results["aton"] = {"status": "ERROR ❌", "error": str(e)}
        print(f"   ❌ Errore Aton: {e}")

    # 3. LG ThinQ (Climatizzatori & Frigorifero)
    print("\n3. Controllo Climatizzatori & Frigorifero LG ThinQ...")
    try:
        from backend.thinq_service import thinq_service
        thinq_devs = thinq_service.get_cached_devices()
        results["lg_thinq"] = {
            "enabled": settings.LG_THINQ_ENABLED,
            "connected": thinq_service.is_connected,
            "devices_count": len(thinq_devs),
            "devices": []
        }
        for d in thinq_devs:
            d_info = {
                "id": d.get("device_id") or d.get("deviceId"),
                "name": d.get("alias") or "LG Device",
                "type": d.get("device_type"),
                "is_on": d.get("is_on"),
                "current_temp": d.get("temp_current"),
                "target_temp": d.get("target_temp"),
                "mode": d.get("op_mode")
            }
            results["lg_thinq"]["devices"].append(d_info)
            print(f"   ❄️ LG [{d_info['name']}]: ON={d_info['is_on']}, T_curr={d_info['current_temp']}°C, Set={d_info['target_temp']}°C ({d_info['type']})")
    except Exception as e:
        results["lg_thinq"] = {"status": "ERROR ❌", "error": str(e)}
        print(f"   ❌ Errore LG ThinQ: {e}")

    # 4. Samsung SmartThings
    print("\n4. Controllo Elettrodomestici & Presenza Samsung SmartThings...")
    try:
        from backend.smartthings_service import smartthings_service
        st_summary = smartthings_service.get_summary()
        w = st_summary.get("washer")
        dw = st_summary.get("dishwasher")
        p = st_summary.get("presence")
        
        results["smartthings"] = {
            "enabled": settings.SMARTTHINGS_ENABLED,
            "connected": st_summary.get("is_connected"),
            "washer": w,
            "dishwasher": dw,
            "presence": p
        }
        if w:
            print(f"   🫧 Lavatrice: {w.get('state_label')} (Running: {w.get('is_running')})")
        if dw:
            print(f"   🍽️ Lavastoviglie: {dw.get('state_label')} (Running: {dw.get('is_running')})")
        if p:
            print(f"   📍 Presenza [{p.get('name')}]: {p.get('presence_label')}")
        if not w and not dw and not p:
            print("   ⚪ Nessun elettrodomestico SmartThings attualmente in esecuzione o rilevato.")
    except Exception as e:
        results["smartthings"] = {"status": "ERROR ❌", "error": str(e)}
        print(f"   ❌ Errore SmartThings: {e}")

    # 5. Tuya (Cloud & Local LAN)
    print("\n5. Controllo Prese & Dispositivi Tuya (Cloud & Local LAN)...")
    try:
        from backend.tuya_service import tuya_service
        from backend.database import get_tuya_local_devices
        local_devs = get_tuya_local_devices()
        tuya_sum = tuya_service.get_summary()
        
        results["tuya"] = {
            "enabled": tuya_service.enabled,
            "cloud_initialized": bool(tuya_service.cloud),
            "cached_devices_count": len(tuya_sum.get("all_devices", [])),
            "local_lan_devices_count": len(local_devs),
            "local_lan_devices": local_devs,
            "devices": []
        }
        for d in tuya_sum.get("all_devices", []):
            d_info = {
                "id": d.get("id"),
                "name": d.get("name"),
                "category": d.get("category"),
                "is_on": d.get("is_on"),
                "power_w": d.get("power_w"),
                "voltage_v": d.get("voltage_v"),
                "current_a": d.get("current_a")
            }
            results["tuya"]["devices"].append(d_info)
            print(f"   🔌 Tuya [{d_info['name']} - ID: {d_info['id']}]: ON={d_info['is_on']}, P={d_info['power_w']} W, V={d_info['voltage_v']} V")
    except Exception as e:
        results["tuya"] = {"status": "ERROR ❌", "error": str(e)}
        print(f"   ❌ Errore Tuya: {e}")

    # 6. Device Scheduler
    print("\n6. Controllo Device Scheduler & Timer...")
    try:
        from backend.device_scheduler import device_scheduler
        scheds = device_scheduler.get_schedules()
        results["scheduler"] = {
            "active_tasks_count": len(scheds),
            "tasks": scheds
        }
        print(f"   ⏱️ Device Scheduler attivo: {len(scheds)} timer pendenti")
        for s in scheds:
            print(f"      - {s['action'].upper()} '{s['device_name']}' alle {s['execute_at_local']} ({s['remaining_label']})")
    except Exception as e:
        results["scheduler"] = {"status": "ERROR ❌", "error": str(e)}
        print(f"   ❌ Errore Scheduler: {e}")

    # 7. Catalogo Globale Dispositivi Aggregato
    print("\n7. Verifica Catalogo Globale Dispositivi Aggregato (/api/devices/all)...")
    try:
        from backend.routers.devices import build_devices_catalog
        catalog = build_devices_catalog()
        stats = catalog.get("stats", {})
        results["catalog"] = {
            "total": stats.get("total"),
            "active": stats.get("active"),
            "total_power_w": stats.get("total_power_w"),
            "online": stats.get("online"),
            "scheduled_count": stats.get("scheduled_tasks_count")
        }
        print(f"   📊 Catalogo OK: {stats.get('total')} Dispositivi Totali | {stats.get('active')} Attivi | {stats.get('total_power_w')} W Carico | {stats.get('online')} Online")
    except Exception as e:
        results["catalog"] = {"status": "ERROR ❌", "error": str(e)}
        print(f"   ❌ Errore Catalogo: {e}")

    print("\n" + "=" * 60)
    print("🎯 AUDIT COMPLETATO CON SUCCESSO!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_audit())
