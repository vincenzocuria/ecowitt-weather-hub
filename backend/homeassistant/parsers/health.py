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


def parse_health_data(entities: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Estrae e normalizza tutti i dati sanitari e fitness rilevati da Home Assistant (Samsung Health / Health Connect).
    """
    if not entities:
        return {"is_available": False}

    device_name = "Samsung Health"
    
    # 1. Trova nome dispositivo associato
    for ent_id, ent in entities.items():
        if "samsung_s26" in ent_id or "galaxy" in ent_id:
            device_name = "Samsung Galaxy S26"
            break
        elif ent_id.startswith("person."):
            device_name = ent.get("attributes", {}).get("friendly_name") or device_name

    # 2. Mappa sensori di salute
    daily_steps = None
    odometer_steps = None
    daily_dist_m = None
    daily_floors = None
    daily_elevation_m = None

    total_calories = None
    basal_calories = None
    active_calories = None

    heart_rate = None
    resting_heart_rate = None
    respiratory_rate = None
    oxygen_saturation = None
    vo2_max = None
    hrv = None

    sleep_minutes = None

    weight_g = None
    body_fat_pct = None
    lean_mass_g = None
    body_water_g = None
    bone_mass_g = None
    hydration_ml = None
    battery_level = None

    for ent_id, ent in entities.items():
        state_val = ent.get("state")
        eid_lower = ent_id.lower()

        # Passi
        if "daily_steps" in eid_lower:
            daily_steps = _safe_int(state_val)
        elif "steps_sensor" in eid_lower or (("step" in eid_lower or "passi" in eid_lower) and daily_steps is None):
            odometer_steps = _safe_int(state_val)

        # Distanza e dislivello
        if "daily_distance" in eid_lower or "distance" in eid_lower:
            daily_dist_m = _safe_float(state_val)
        elif "daily_floors" in eid_lower or "floors" in eid_lower:
            daily_floors = _safe_int(state_val)
        elif "daily_elevation" in eid_lower or "elevation_gained" in eid_lower:
            daily_elevation_m = _safe_float(state_val)

        # Calorie
        if "total_calories" in eid_lower:
            total_calories = _safe_float(state_val)
        elif "basal_metabolic" in eid_lower or "bmr" in eid_lower:
            basal_calories = _safe_float(state_val)
        elif "active_calories" in eid_lower:
            active_calories = _safe_float(state_val)

        # Parametri cardiaci & ossigeno
        if "resting_heart_rate" in eid_lower:
            resting_heart_rate = _safe_float(state_val)
        elif "heart_rate_variability" in eid_lower or "hrv" in eid_lower:
            hrv = _safe_float(state_val)
        elif "heart_rate" in eid_lower or "pulse" in eid_lower or "battito" in eid_lower:
            heart_rate = _safe_float(state_val)
        elif "oxygen_saturation" in eid_lower or "spo2" in eid_lower:
            oxygen_saturation = _safe_float(state_val)
        elif "vo2_max" in eid_lower:
            vo2_max = _safe_float(state_val)
        elif "respiratory_rate" in eid_lower:
            respiratory_rate = _safe_float(state_val)

        # Sonno
        if "sleep_duration" in eid_lower or "sleep" in eid_lower:
            sleep_minutes = _safe_float(state_val)

        # Composizione corporea
        if ("sensor." in eid_lower and eid_lower.endswith("_weight")) or "body_weight" in eid_lower or "peso" in eid_lower:
            weight_g = _safe_float(state_val)
        elif "body_fat" in eid_lower or "grasso" in eid_lower:
            body_fat_pct = _safe_float(state_val)
        elif "lean_body_mass" in eid_lower or "massa_magra" in eid_lower:
            lean_mass_g = _safe_float(state_val)
        elif "body_water_mass" in eid_lower or "acqua_corporea" in eid_lower:
            body_water_g = _safe_float(state_val)
        elif "bone_mass" in eid_lower or "massa_ossea" in eid_lower:
            bone_mass_g = _safe_float(state_val)
        elif "daily_hydration" in eid_lower or "idratazione" in eid_lower:
            hydration_ml = _safe_float(state_val)

        # Batteria dispositivo
        if "samsung_s26_battery_level" in eid_lower or ("battery_level" in eid_lower and battery_level is None):
            battery_level = _safe_int(state_val)

    # Se non abbiamo nessun dato rilevante, ritorna non disponibile
    has_any_data = any([
        daily_steps is not None,
        odometer_steps is not None,
        heart_rate is not None,
        total_calories is not None,
        weight_g is not None,
        sleep_minutes is not None
    ])

    if not has_any_data:
        return {"is_available": False}

    # Calcoli e conversioni
    steps_val = daily_steps if daily_steps is not None else 0
    steps_goal = 8000
    steps_pct = min(100.0, round((steps_val / steps_goal) * 100, 1)) if steps_goal > 0 else 0.0

    # Distanza in km
    dist_km = None
    if daily_dist_m is not None:
        dist_km = round(daily_dist_m / 1000.0, 2)
    elif steps_val > 0:
        dist_km = round((steps_val * 0.75) / 1000.0, 2)  # Stima 75cm per passo

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

    return {
        "is_available": True,
        "device_name": device_name,
        "battery_pct": battery_level,
        "steps": {
            "daily": steps_val,
            "goal": steps_goal,
            "pct": steps_pct,
            "total_odometer": odometer_steps,
            "distance_m": daily_dist_m,
            "distance_km": dist_km,
            "floors": daily_floors or 0,
            "elevation_m": daily_elevation_m or 0.0
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
            "bone_mass_kg": bone_mass_kg
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
