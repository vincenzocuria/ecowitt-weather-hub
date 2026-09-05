"""
Parser specializzato per dati biometrici, attività fisica e salute da Samsung Health e Google Health Connect via Home Assistant.
Estrae e normalizza:
- Passi giornalieri, odometro totale, distanza, piani saliti, dislivello
- Calorie totali, metabolismo basale (BMR), calorie attive stimate
- Frequenza cardiaca istantanea, a riposo, SpO2 (ossigeno), VO2 Max, frequenza respiratoria
- Sonno (durata totale in ore/minuti)
- Composizione corporea (peso in kg, % massa grassa, massa magra kg, massa idrica kg, massa ossea kg)
- Idratazione giornaliera
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("weather_hub.homeassistant.parsers.health")


def _safe_float(val: Any) -> Optional[float]:
    """Converte un valore in float in modo sicuro, restituendo None se non valido."""
    if val is None:
        return None
    try:
        s = str(val).strip().lower()
        if s in ("unknown", "unavailable", "none", "null", ""):
            return None
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val: Any) -> Optional[int]:
    """Converte un valore in int in modo sicuro."""
    f = _safe_float(val)
    return int(round(f)) if f is not None else None


def _clean_watch_friendly_name(name: str) -> str:
    """Rimuove suffissi tipici dei sensori HA Wear OS (es. 'Current time zone', 'Battery level', etc.)."""
    if not name:
        return "Galaxy Watch"
    import re
    cleaned = re.sub(
        r'\s+(Current\s*time\s*zone|Battery\s*(level|state)?|Daily\s*(steps|floors|calories|distance)?|Steps\s*sensor|Heart\s*rate|Activity\s*state|Next\s*alarm|Pressure\s*sensor|On-body\s*sensor|Volume.*|NFC.*|Bedtime.*|Wet\s*mode).*$',
        '',
        name,
        flags=re.IGNORECASE
    ).strip()
    return cleaned or "Galaxy Watch"


def _format_health_datetime(iso_str: Optional[str]) -> Optional[str]:
    """Formatta timestamp ISO in etichetta leggibile italiana (es. 'Oggi 08:33')."""
    if not iso_str:
        return None
    try:
        from datetime import datetime
        import zoneinfo
        s = str(iso_str).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        try:
            rome_tz = zoneinfo.ZoneInfo("Europe/Rome")
            local_dt = dt.astimezone(rome_tz)
            now = datetime.now(rome_tz)
        except Exception:
            local_dt = dt
            now = datetime.now()
        if local_dt.date() == now.date():
            return f"Oggi {local_dt.strftime('%H:%M')}"
        elif (now.date() - local_dt.date()).days == 1:
            return f"Ieri {local_dt.strftime('%H:%M')}"
        months = ["", "Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]
        return f"{local_dt.day} {months[local_dt.month]} {local_dt.strftime('%H:%M')}"
    except Exception:
        return str(iso_str)[:16].replace("T", " ")


def parse_health_data(entities: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Estrae e normalizza tutti i dati sanitari e fitness rilevati da Home Assistant (Samsung Health / Health Connect).
    """
    if not entities:
        return {"is_available": False}

    device_name = "Samsung Health"
    
    # 1. Trova dispositivi associati (Smartphone Samsung & Smartwatch Galaxy Watch / Wear OS)
    has_watch = False
    watch_name = None
    has_phone = False
    phone_name = "Samsung Galaxy S26"

    for ent_id, ent in entities.items():
        eid_lower = ent_id.lower()
        if any(w in eid_lower for w in ("watch", "wear", "gear", "sm_r")):
            has_watch = True
            friendly = ent.get("attributes", {}).get("friendly_name")
            if friendly and any(k in friendly.lower() for k in ("watch", "galaxy", "orologio")):
                watch_name = _clean_watch_friendly_name(friendly)
            elif not watch_name:
                watch_name = "Galaxy Watch"
        if "samsung_s26" in eid_lower or "s26" in eid_lower or ("galaxy" in eid_lower and not any(w in eid_lower for w in ("watch", "wear", "gear", "sm_r"))):
            has_phone = True
            friendly = ent.get("attributes", {}).get("friendly_name")
            if friendly and any(k in friendly.lower() for k in ("s26", "galaxy", "telefono")):
                phone_name = friendly
        elif ent_id.startswith("person.") and not has_phone:
            phone_name = ent.get("attributes", {}).get("friendly_name") or phone_name

    if has_watch and has_phone:
        device_name = f"Samsung Galaxy S26 • {watch_name or 'Galaxy Watch'}"
    elif has_watch:
        device_name = watch_name or "Galaxy Watch"
    elif has_phone:
        device_name = phone_name
    else:
        device_name = "Samsung Health"

    # 2. Mappa sensori di salute con supporto multi-dispositivo (Smartwatch + Smartphone + Health Connect)
    daily_step_candidates = []  # Tuples: (steps_int, source_label, entity_id)
    watch_steps = None
    phone_steps = None
    health_connect_steps = None
    odometer_candidates = []

    daily_dist_candidates = []
    daily_floors_candidates = []
    daily_elevation_m = None

    total_cal_candidates = []
    basal_calories = None
    active_cal_candidates = []

    heart_rate = None
    resting_heart_rate = None
    respiratory_rate = None
    oxygen_saturation = None
    vo2_max = None
    hrv = None

    sleep_candidates = []

    weight_g = None
    body_fat_pct = None
    lean_mass_g = None
    body_water_g = None
    bone_mass_g = None
    hydration_ml = None
    battery_level = None
    watch_battery_level = None
    body_source_pkg = None
    body_date = None

    for ent_id, ent in entities.items():
        state_val = ent.get("state")
        eid_lower = ent_id.lower()
        attrs = ent.get("attributes", {})
        unit = str(attrs.get("unit_of_measurement", "")).lower()

        # Identificazione origine entità
        is_watch_entity = any(w in eid_lower for w in ("watch", "wear", "gear", "sm_r"))
        is_phone_entity = any(p in eid_lower for p in ("s26", "phone", "mobile", "smartphone")) or (
            "samsung" in eid_lower and not is_watch_entity
        )
        is_hc_entity = any(h in eid_lower for h in ("health_connect", "shealth", "samsung_health"))

        # --- PASSI ---
        # A) Sensori espliciti di passi giornalieri (Health Connect o template HA)
        if "daily_steps" in eid_lower:
            val = _safe_int(state_val)
            if val is not None:
                if is_watch_entity:
                    watch_steps = max(watch_steps or 0, val)
                    daily_step_candidates.append((val, "Smartwatch (Galaxy Watch)", ent_id))
                elif is_hc_entity:
                    health_connect_steps = max(health_connect_steps or 0, val)
                    daily_step_candidates.append((val, "Samsung Health / Health Connect", ent_id))
                elif is_phone_entity:
                    phone_steps = max(phone_steps or 0, val)
                    daily_step_candidates.append((val, "Telefono S26 (Health Connect)", ent_id))
                else:
                    daily_step_candidates.append((val, "Passi Giornalieri", ent_id))

        # B) Sensori hardware contapassi (Android Steps Sensor / Odometer)
        elif "steps_sensor" in eid_lower:
            val = _safe_int(state_val)
            if val is not None:
                odometer_candidates.append(val)
                # NOTA: su Android smartphone, steps_sensor (TYPE_STEP_COUNTER) è un contatore cumulativo
                # che si azzera solo al riavvio hardware del telefono, NON a mezzanotte.
                # Lo consideriamo candidato giornaliero SOLO per uno smartwatch se quest'ultimo non espone
                # un sensore 'daily_steps' separato (es. orologi Wear OS legacy con solo steps_sensor).
                if is_watch_entity and watch_steps is None and val <= 80000:
                    watch_steps = val
                    daily_step_candidates.append((val, "Smartwatch (Galaxy Watch)", ent_id))

        # C) Altri sensori con 'step' o 'passi' nel nome o nell'unità
        elif any(k in eid_lower for k in ("step", "passi")) or unit in ("steps", "passi", "step"):
            val = _safe_int(state_val)
            if val is not None:
                if "daily" in eid_lower:
                    if is_watch_entity:
                        watch_steps = max(watch_steps or 0, val)
                        daily_step_candidates.append((val, "Smartwatch (Galaxy Watch)", ent_id))
                    elif is_phone_entity:
                        phone_steps = max(phone_steps or 0, val)
                        daily_step_candidates.append((val, "Telefono S26", ent_id))
                    else:
                        daily_step_candidates.append((val, "Contapassi", ent_id))
                else:
                    odometer_candidates.append(val)

        # --- DISTANZA E DISLIVELLO ---
        if "daily_distance" in eid_lower or ("distance" in eid_lower and any(k in eid_lower for k in ("samsung", "health", "s26", "watch", "wear"))):
            val = _safe_float(state_val)
            if val is not None and val > 0:
                daily_dist_candidates.append(val)
        elif "daily_floors" in eid_lower or ("floors" in eid_lower and any(k in eid_lower for k in ("samsung", "health", "s26", "watch", "wear"))):
            val = _safe_int(state_val)
            if val is not None:
                daily_floors_candidates.append(val)
        elif "daily_elevation" in eid_lower or "elevation_gained" in eid_lower:
            daily_elevation_m = _safe_float(state_val)

        # --- CALORIE ---
        if "total_calories" in eid_lower:
            val = _safe_float(state_val)
            if val is not None and val > 0:
                total_cal_candidates.append(val)
        elif "basal_metabolic" in eid_lower or "bmr" in eid_lower:
            basal_calories = _safe_float(state_val)
        elif "active_calories" in eid_lower:
            val = _safe_float(state_val)
            if val is not None and val > 0:
                active_cal_candidates.append(val)

        # --- PARAMETRI CARDIACI & OSSIGENO ---
        if "resting_heart_rate" in eid_lower:
            resting_heart_rate = _safe_float(state_val)
        elif "heart_rate_variability" in eid_lower or "hrv" in eid_lower:
            hrv = _safe_float(state_val)
        elif "heart_rate" in eid_lower or "pulse" in eid_lower or "battito" in eid_lower:
            val = _safe_float(state_val)
            if val is not None and val > 0:
                # Se è da smartwatch ha priorità perché misura al polso in tempo reale
                if is_watch_entity or heart_rate is None:
                    heart_rate = val
        elif "oxygen_saturation" in eid_lower or "spo2" in eid_lower:
            val = _safe_float(state_val)
            if val is not None and val > 0:
                oxygen_saturation = val
        elif "vo2_max" in eid_lower:
            vo2_max = _safe_float(state_val)
        elif "respiratory_rate" in eid_lower:
            respiratory_rate = _safe_float(state_val)

        # --- SONNO ---
        if "sleep_duration" in eid_lower or "sleep" in eid_lower or "sonno" in eid_lower:
            val = _safe_float(state_val)
            if val is not None and val > 0:
                sleep_candidates.append(val)

        # --- COMPOSIZIONE CORPOREA & BILANCIA SMART ---
        if ("sensor." in eid_lower and eid_lower.endswith("_weight")) or "body_weight" in eid_lower or "peso" in eid_lower:
            weight_g = _safe_float(state_val)
            if attrs.get("source"):
                body_source_pkg = attrs["source"]
            if attrs.get("date"):
                body_date = attrs["date"]
        elif "body_fat" in eid_lower or "grasso" in eid_lower:
            body_fat_pct = _safe_float(state_val)
            if not body_source_pkg and attrs.get("source"):
                body_source_pkg = attrs["source"]
            if not body_date and attrs.get("date"):
                body_date = attrs["date"]
        elif "lean_body_mass" in eid_lower or "massa_magra" in eid_lower:
            lean_mass_g = _safe_float(state_val)
        elif "body_water_mass" in eid_lower or "acqua_corporea" in eid_lower:
            body_water_g = _safe_float(state_val)
        elif "bone_mass" in eid_lower or "massa_ossea" in eid_lower:
            bone_mass_g = _safe_float(state_val)
        elif "daily_hydration" in eid_lower or "idratazione" in eid_lower:
            hydration_ml = _safe_float(state_val)

        # --- BATTERIE DISPOSITIVI ---
        if is_watch_entity and ("battery_level" in eid_lower or (attrs.get("device_class") == "battery" and "state" not in eid_lower)):
            val = _safe_int(state_val)
            if val is not None and 0 <= val <= 100:
                watch_battery_level = val
        elif not is_watch_entity and ("battery_level" in eid_lower or (attrs.get("device_class") == "battery" and "state" not in eid_lower)):
            val = _safe_int(state_val)
            if val is not None and 0 <= val <= 100:
                if "s26" in eid_lower or battery_level is None:
                    battery_level = val

    # Consolidamento metriche multi-sorgente:
    # Per i passi, scegliamo il valore massimo tra le letture giornaliere valide.
    # Questo evita di mostrare il conteggio parziale del solo smartphone se l'utente ha camminato con lo smartwatch,
    # o viceversa se l'orologio si stava ricaricando.
    daily_steps = None
    steps_source = "Samsung Health"
    steps_source_entity = None
    steps_last_updated = None
    steps_sources_list = []
    if daily_step_candidates:
        best_candidate = max(daily_step_candidates, key=lambda c: c[0])
        daily_steps = best_candidate[0]
        steps_source = best_candidate[1]
        steps_source_entity = best_candidate[2]
        if steps_source_entity in entities:
            ent = entities[steps_source_entity]
            raw_lu = ent.get("last_updated") or ent.get("last_changed")
            steps_last_updated = _format_health_datetime(raw_lu)
            steps_sources_list = ent.get("attributes", {}).get("sources", [])

    odometer_steps = max(odometer_candidates) if odometer_candidates else None
    daily_dist_m = max(daily_dist_candidates) if daily_dist_candidates else None
    daily_floors = max(daily_floors_candidates) if daily_floors_candidates else None
    total_calories = max(total_cal_candidates) if total_cal_candidates else None
    active_calories = max(active_cal_candidates) if active_cal_candidates else None
    sleep_minutes = max(sleep_candidates) if sleep_candidates else None

    # Label sorgente bilancia (es. Tuya Smart Life vs Samsung Health)
    body_source_label = "Tuya Smart Life"
    if body_source_pkg:
        if "tuya" in body_source_pkg.lower() or "smartlife" in body_source_pkg.lower():
            body_source_label = "Tuya Smart Life"
        elif "shealth" in body_source_pkg.lower() or "samsung" in body_source_pkg.lower():
            body_source_label = "Samsung Health"
        elif "fitness" in body_source_pkg.lower() or "google" in body_source_pkg.lower():
            body_source_label = "Google Health Connect"
        else:
            body_source_label = body_source_pkg

    # Verifica se ci sono entità Samsung/Health/Watch presenti nel sistema HA
    has_health_entities = any(
        any(k in eid_lower for k in ("samsung", "daily_steps", "steps_sensor", "body_fat", "total_calories", "watch", "wear", "shealth"))
        for eid_lower in [e.lower() for e in entities.keys()]
    )

    # Se mancano valori live (es. app in background o appena inizializzata), recupera ultimo snapshot da DB
    try:
        from backend.database import get_health_daily_history, seed_health_baseline_if_empty
        seed_health_baseline_if_empty()
        db_history = get_health_daily_history(days=1)
        latest_db = db_history[-1] if db_history else None
    except Exception as e:
        logger.warning(f"Errore recupero baseline sanitaria da DB: {e}")
        latest_db = None

    # Fallback con i dati memorizzati nel DB se il sensore live è None
    if latest_db:
        if daily_steps is None:
            daily_steps = latest_db.get("steps")
        if odometer_steps is None and daily_steps is not None:
            odometer_steps = daily_steps
        if daily_dist_m is None and latest_db.get("distance_km") is not None:
            daily_dist_m = float(latest_db["distance_km"]) * 1000.0
        if daily_floors is None:
            daily_floors = latest_db.get("floors", 0)
        if total_calories is None:
            total_calories = latest_db.get("total_calories")
        if basal_calories is None:
            basal_calories = latest_db.get("basal_calories", 1617.5)
        if active_calories is None:
            if total_calories is not None and basal_calories is not None:
                active_calories = max(0.0, round(total_calories - basal_calories, 1))
            else:
                active_calories = latest_db.get("active_calories")
        if heart_rate is None:
            heart_rate = latest_db.get("heart_rate_avg")
        if oxygen_saturation is None:
            oxygen_saturation = latest_db.get("spo2_avg")
        if vo2_max is None:
            vo2_max = latest_db.get("vo2_max")
        if sleep_minutes is None:
            sleep_minutes = latest_db.get("sleep_minutes")
        if weight_g is None and latest_db.get("weight_kg") is not None:
            weight_g = float(latest_db["weight_kg"])
        if body_fat_pct is None:
            body_fat_pct = latest_db.get("body_fat_pct")
        if lean_mass_g is None and latest_db.get("lean_mass_kg") is not None:
            lean_mass_g = float(latest_db["lean_mass_kg"])
        if body_water_g is None and latest_db.get("water_mass_kg") is not None:
            body_water_g = float(latest_db["water_mass_kg"])
        if bone_mass_g is None and latest_db.get("bone_mass_kg") is not None:
            bone_mass_g = float(latest_db["bone_mass_kg"])
        if hydration_ml is None and latest_db.get("hydration_ml") is not None:
            hydration_ml = float(latest_db["hydration_ml"])

    # Se non abbiamo nessun dato rilevante né da HA né da DB, ritorna non disponibile
    has_any_data = any([
        daily_steps is not None,
        odometer_steps is not None,
        heart_rate is not None,
        total_calories is not None,
        weight_g is not None,
        sleep_minutes is not None,
        has_health_entities
    ])

    if not has_any_data:
        return {"is_available": False}

    # Calcoli e conversioni
    steps_val = daily_steps if daily_steps is not None else 0
    steps_goal = 8000
    steps_pct = min(100.0, round((steps_val / steps_goal) * 100, 1)) if steps_goal > 0 else 0.0

    # Distanza in km (usa il dato sensore se coerente, oppure stima 75cm a passo)
    step_est_dist_km = round((steps_val * 0.75) / 1000.0, 2) if steps_val > 0 else 0.0
    dist_km = None
    if daily_dist_m is not None:
        sensor_dist_km = round(daily_dist_m / 1000.0, 2)
        # Se il sensore riporta una distanza irrealistica rispetto ai passi (es. solo 500m per 6000 passi), usa la stima coerente
        if steps_val > 1000 and sensor_dist_km < (step_est_dist_km * 0.4):
            dist_km = step_est_dist_km
        else:
            dist_km = sensor_dist_km
    elif steps_val > 0:
        dist_km = step_est_dist_km

    # Calorie attive stimate se non fornite direttamente
    if active_calories is None and total_calories is not None and basal_calories is not None:
        diff_cal = total_calories - basal_calories
        active_calories = max(0.0, round(diff_cal, 1))

    # Sonno formattato (es. 84 min -> 1h 24m)
    sleep_formatted = "--"
    sleep_hours = 0.0
    if sleep_minutes is not None and sleep_minutes > 0:
        tot_m = int(round(sleep_minutes))
        h = tot_m // 60
        m = tot_m % 60
        sleep_hours = round(sleep_minutes / 60.0, 1)
        sleep_formatted = f"{h}h {m:02d}m" if h > 0 else f"{m}m"

    # Pesi convertiti da grammi a kg se > 500
    def _to_kg(g_val: Optional[float]) -> Optional[float]:
        if g_val is None:
            return None
        return round(g_val / 1000.0, 1) if g_val > 500 else round(g_val, 1)

    weight_kg = _to_kg(weight_g)
    lean_mass_kg = _to_kg(lean_mass_g)
    water_mass_kg = _to_kg(body_water_g)
    bone_mass_kg = _to_kg(bone_mass_g)

    # Indicatore di stato frequenza cardiaca
    heart_status = "Normale"
    heart_badge_class = "badge-success"
    if heart_rate is not None:
        if heart_rate < 55:
            heart_status = "Bradicardia / Riposo"
            heart_badge_class = "badge-info"
        elif heart_rate <= 95:
            heart_status = "Ottimale a riposo"
            heart_badge_class = "badge-success"
        elif heart_rate <= 125:
            heart_status = "Attività moderata"
            heart_badge_class = "badge-warning"
        else:
            heart_status = "Attività intensa / Cardio"
            heart_badge_class = "badge-danger"

    result = {
        "is_available": True,
        "device_name": device_name,
        "battery_pct": battery_level,
        "watch_battery_pct": watch_battery_level,
        "has_smartwatch": has_watch,
        "steps": {
            "daily": steps_val,
            "goal": steps_goal,
            "pct": steps_pct,
            "total_odometer": odometer_steps,
            "distance_m": daily_dist_m,
            "distance_km": dist_km,
            "floors": daily_floors or 0,
            "elevation_m": daily_elevation_m or 0.0,
            "source": steps_source,
            "source_entity": steps_source_entity,
            "last_updated_formatted": steps_last_updated,
            "sources": steps_sources_list,
            "watch_steps": watch_steps,
            "phone_steps": phone_steps,
            "health_connect_steps": health_connect_steps,
            "has_smartwatch": has_watch
        },
        "calories": {
            "total_kcal": round(total_calories, 1) if total_calories is not None else None,
            "basal_kcal": round(basal_calories, 1) if basal_calories is not None else None,
            "active_kcal": round(active_calories, 1) if active_calories is not None else None,
            "active_goal": 500,
            "active_pct": min(100.0, round(((active_calories or 0) / 500) * 100, 1)) if active_calories else 0.0
        },
        "heart": {
            "rate_bpm": int(round(heart_rate)) if heart_rate is not None else None,
            "resting_bpm": int(round(resting_heart_rate)) if resting_heart_rate is not None else None,
            "status": heart_status,
            "badge_class": heart_badge_class,
            "spo2_pct": round(oxygen_saturation, 1) if oxygen_saturation is not None else None,
            "vo2_max": round(vo2_max, 1) if vo2_max is not None else None,
            "respiratory_rate": int(round(respiratory_rate)) if respiratory_rate is not None else None,
            "hrv_ms": round(hrv, 1) if hrv is not None else None
        },
        "sleep": {
            "duration_min": int(round(sleep_minutes)) if sleep_minutes is not None else None,
            "duration_hours": sleep_hours,
            "duration_formatted": sleep_formatted
        },
        "body": {
            "weight_kg": weight_kg,
            "fat_pct": round(body_fat_pct, 1) if body_fat_pct is not None else None,
            "lean_mass_kg": lean_mass_kg,
            "water_mass_kg": water_mass_kg,
            "bone_mass_kg": bone_mass_kg,
            "source_label": body_source_label,
            "source_pkg": body_source_pkg,
            "measured_at": body_date,
            "measured_at_formatted": _format_health_datetime(body_date)
        },
            "hydration": {
            "daily_ml": int(round(hydration_ml)) if hydration_ml is not None else 0,
            "goal_ml": 2000,
            "pct": min(100.0, round(((hydration_ml or 0) / 2000) * 100, 1)) if hydration_ml else 0.0
        }
    }

    # Persistenza snapshot su SQLite e aggregazione statistiche
    try:
        from backend.database import record_health_snapshot, get_health_stats_summary
        record_health_snapshot(result)
        result["analytics"] = get_health_stats_summary()
    except Exception as e:
        logger.warning(f"[HEALTH] Errore integrazione statistiche DB salute: {e}")
        result["analytics"] = {}

    return result
