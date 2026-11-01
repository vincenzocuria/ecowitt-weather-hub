"""
Helper per la scansione, normalizzazione e composizione del catalogo unificato dei dispositivi da Home Assistant.
Effettua il binding automatico tra entità commutabili (switch, light, valve, climate, cover) e i rispettivi sensori di potenza istantanea in Watt.
"""

import logging
from typing import Dict, Any, List

from .parsers.appliances import parse_washer_data, parse_dishwasher_data, parse_fridge_data
from .parsers.presence import parse_presence_data
from .parsers.health import parse_health_data

logger = logging.getLogger("weather_hub.homeassistant.catalog")


class CatalogHelper:
    """Costruttore del catalogo unificato dispositivi per Home Assistant."""

    @staticmethod
    def build_power_map(entities: Dict[str, Dict[str, Any]]) -> Dict[str, float]:
        """Mappa veloce dei sensori di potenza/consumo (es: sensor.cisterna_potenza -> 9.0 W)."""
        power_map: Dict[str, float] = {}
        for entity_id, state_obj in entities.items():
            if entity_id.startswith("sensor.") and any(k in entity_id for k in ("_potenza", "_power", "_consumption")):
                try:
                    p_val = float(state_obj.get("state") or 0.0)
                    base_key = (
                        entity_id.replace("sensor.", "")
                        .replace("_potenza", "")
                        .replace("_power", "")
                        .replace("_consumption", "")
                    )
                    power_map[base_key] = p_val
                except (ValueError, TypeError):
                    pass
        # Mappature logiche alias note
        if "climatizzatore" in power_map and "cucina" not in power_map:
            power_map["cucina"] = power_map["climatizzatore"]
        return power_map

    @staticmethod
    def build_telemetry_map(entities: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
        """Mappa dettagliata delle grandezze elettriche (tensione, corrente, energia totale)."""
        telemetry: Dict[str, Dict[str, float]] = {}
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

            ent_clean = entity_id.replace("sensor.", "")
            base_key = None
            field = None
            if any(k in ent_clean for k in ("_tensione", "_voltage")):
                base_key = ent_clean.replace("_tensione", "").replace("_voltage", "")
                field = "voltage_v"
            elif any(k in ent_clean for k in ("_corrente", "_current")):
                base_key = ent_clean.replace("_corrente", "").replace("_current", "")
                field = "current_a"
            elif any(k in ent_clean for k in ("_energia_totale", "_energy_total", "_total_energy")):
                base_key = ent_clean.replace("_energia_totale", "").replace("_energy_total", "").replace("_total_energy", "")
                field = "energy_total_kwh"
            elif any(k in ent_clean for k in ("_energy_today", "_energia_oggi")):
                base_key = ent_clean.replace("_energy_today", "").replace("_energia_oggi", "")
                field = "energy_today_wh"

            if base_key and field:
                if base_key not in telemetry:
                    telemetry[base_key] = {}
                telemetry[base_key][field] = val

        if "climatizzatore" in telemetry and "cucina" not in telemetry:
            telemetry["cucina"] = telemetry["climatizzatore"].copy()
        return telemetry

    @classmethod
    def get_catalog_devices(cls, entities: Dict[str, Dict[str, Any]], enabled: bool = True) -> List[Dict[str, Any]]:
        """Restituisce tutte le entità rilevanti formattate per il catalogo unificato con abbinamento potenza."""
        if not enabled or not entities:
            return []

        power_map = cls.build_power_map(entities)
        telemetry_map = cls.build_telemetry_map(entities)
        devices: List[Dict[str, Any]] = []

        # 1. Lavatrice Samsung
        washer = parse_washer_data(entities)
        if washer:
            devices.append({
                "id": "hass_washer",
                "raw_id": "lavanderia_lavatrice",
                "ecosystem": "homeassistant",
                "name": "Lavatrice Samsung",
                "icon": "🫧",
                "category": "appliances",
                "category_label": "Lavatrice Samsung • HA",
                "is_on": washer.get("is_on", False),
                "can_toggle": False,
                "is_online": washer.get("is_connected", True),
                "status_text": washer.get("job_state_label", "In Standby"),
                "power_w": washer.get("power_w", 0.0),
                "completion_time": washer.get("finish_estimate"),
                "cycle_name": washer.get("water_temp"),
                "raw": washer
            })

        # 2. Lavastoviglie Samsung
        dish = parse_dishwasher_data(entities)
        if dish:
            devices.append({
                "id": "hass_dishwasher",
                "raw_id": "cucina_lavastoviglie",
                "ecosystem": "homeassistant",
                "name": "Lavastoviglie Samsung",
                "icon": "🍽️",
                "category": "appliances",
                "category_label": "Lavastoviglie Samsung • HA",
                "is_on": dish.get("is_on", False),
                "can_toggle": False,
                "is_online": dish.get("is_connected", True),
                "status_text": dish.get("job_state_label", "In Standby"),
                "power_w": dish.get("power_w", 0.0),
                "completion_time": dish.get("finish_estimate"),
                "cycle_name": dish.get("cycle_name"),
                "raw": dish
            })

        # 3. Frigorifero Smart (LG ThinQ da HA)
        fridge = parse_fridge_data(entities)
        if fridge:
            devices.append({
                "id": "hass_frigorifero",
                "raw_id": "frigorifero",
                "ecosystem": "homeassistant",
                "name": fridge.get("name", "Frigorifero LG"),
                "icon": "🧊",
                "category": "appliances",
                "category_label": "Frigorifero LG • HA",
                "is_on": fridge.get("is_on", False),
                "can_toggle": True,
                "is_online": True,
                "status_text": fridge.get("status_text", "In funzione"),
                "power_w": fridge.get("power_w", 0.0),
                "temp_set": fridge.get("target_temp"),
                "door_open": fridge.get("door_open", False),
                "express_mode": fridge.get("express_mode", False),
                "raw": fridge
            })

        # 4. Presenza Smartphone
        presence = parse_presence_data(entities)
        devices.append({
            "id": "hass_presence",
            "raw_id": "ha_presence_phone",
            "ecosystem": "homeassistant",
            "name": presence.get("name", "Smartphone"),
            "icon": "📱",
            "category": "presence",
            "category_label": "Sensore Presenza & Posizione • HA",
            "is_on": presence.get("is_present", True),
            "can_toggle": False,
            "is_online": True,
            "status_text": f"{presence.get('presence_label', 'A Casa')}" + (f" • {presence.get('battery_pct')}%" if presence.get('battery_pct') is not None else ""),
            "power_w": 0.0,
            "battery_pct": presence.get("battery_pct"),
            "is_present": presence.get("is_present", True),
            "raw": presence
        })

        # 5. Salute & Attività Fisica (Samsung Health / Health Connect)
        health = parse_health_data(entities)
        if health.get("is_available"):
            steps_info = health.get("steps", {})
            cal_info = health.get("calories", {})
            heart_info = health.get("heart", {})
            stat_parts = []
            if steps_info.get("daily") is not None:
                stat_parts.append(f"👟 {steps_info['daily']} passi")
            if heart_info.get("rate_bpm") is not None:
                stat_parts.append(f"❤️ {heart_info['rate_bpm']} bpm")
            if cal_info.get("total_kcal") is not None:
                stat_parts.append(f"🔥 {int(cal_info['total_kcal'])} kcal")

            devices.append({
                "id": "hass_health_samsung",
                "raw_id": "samsung_health_hub",
                "ecosystem": "homeassistant",
                "name": f"Samsung Health • {health.get('device_name', 'Galaxy')}",
                "icon": "🩺",
                "category": "health",
                "category_label": "Salute & Attività Fisica • Health Connect",
                "is_on": True,
                "can_toggle": False,
                "is_online": True,
                "status_text": " • ".join(stat_parts) if stat_parts else "Sincronizzato",
                "power_w": 0.0,
                "battery_pct": health.get("battery_pct"),
                "health_data": health,
                "raw": health
            })

            # 5.1 Bilancia Smart & Analisi BIA (Tuya Smart Life / Home Assistant)
            body_info = health.get("body", {})
            if body_info and body_info.get("weight_kg") is not None:
                scale_src = body_info.get("source_label", "Tuya Smart Life")
                scale_parts = []
                if body_info.get("weight_kg") is not None:
                    scale_parts.append(f"⚖️ {body_info['weight_kg']} kg")
                if body_info.get("fat_pct") is not None:
                    scale_parts.append(f"🥩 {body_info['fat_pct']}% Grasso")
                if body_info.get("lean_mass_kg") is not None:
                    scale_parts.append(f"💪 {body_info['lean_mass_kg']} kg Magra")

                devices.append({
                    "id": "hass_smart_scale",
                    "raw_id": "smart_scale_bia_tuya",
                    "ecosystem": "tuya" if "tuya" in scale_src.lower() else "homeassistant",
                    "name": f"Bilancia Smart BIA • {scale_src}",
                    "icon": "⚖️",
                    "category": "health",
                    "type": "scale",
                    "category_label": f"Bilancia Smart • {scale_src}",
                    "is_on": True,
                    "can_toggle": False,
                    "is_online": True,
                    "status_text": " • ".join(scale_parts) if scale_parts else "Misurazione sincronizzata",
                    "power_w": 0.0,
                    "battery_pct": None,
                    "health_data": health,
                    "body_data": body_info,
                    "raw": health
                })

        # 6. Interruttori, Luci, Clima, Valvole, Tende, Media Player
        for entity_id, state_obj in entities.items():
            domain = entity_id.split(".")[0]
            if domain not in ("switch", "light", "climate", "cover", "valve", "fan", "media_player"):
                continue

            # Filtra pulsanti e switch interni secondari di configurazione ed entità duplicate
            if any(k in entity_id for k in (
                "blocco_bambini", "child_lock", "bubble_soak", "speed_booster", "sanitize",
                "_power", "_energy_saving", "frigorifero_express_mode", "_sleep_timer",
                "_schedule_turn_on", "_schedule_turn_off", "aiuola_valve_2"
            )):
                continue

            attributes = state_obj.get("attributes", {})
            friendly_name = attributes.get("friendly_name") or entity_id
            state_str = (state_obj.get("state") or "").lower()
            is_online = state_str not in ("unavailable", "unknown")

            # Estrai potenza dagli attributi o dalla mappa sensori correlata
            base_key = entity_id.split(".")[1].replace("_socket_1", "").replace("_presa", "").replace("_valve", "")
            power_w = float(attributes.get("current_power_w") or attributes.get("power") or attributes.get("current_consumption") or power_map.get(base_key, 0.0))

            # Riconoscimento avanzato tipologia tramite device_class e parole chiave
            ent_lower = entity_id.lower()
            name_lower = friendly_name.lower()
            dev_class = str(attributes.get("device_class") or "").lower()

            is_shutter = domain == "cover" or (
                domain == "switch" and (
                    dev_class in ("curtain", "blind", "shutter", "shade", "awning", "door", "window", "gate") or
                    any(k in ent_lower or k in name_lower for k in ("tenda", "persiana", "tapparella", "curtain", "shutter", "blind", "serranda"))
                )
            )
            is_irrigation = domain == "valve" or (
                domain == "switch" and (
                    dev_class == "valve" or
                    any(k in ent_lower or k in name_lower for k in ("valvola", "valve", "irrigazione", "irrigation", "aiuola", "sprinkler", "annaffiat", "irrigatore"))
                )
            )

            extra_fields: Dict[str, Any] = {}

            if domain == "climate":
                cat = "climate"
                mode = state_str.upper()
                is_on = state_str not in ("off", "unavailable", "unknown")
                icon = "❄️" if mode == "COOL" else ("🔥" if mode == "HEAT" else "🌬️")
                
                is_fujitsu = any(k in ent_lower or k in name_lower for k in ("cucina", "fujitsu", "fglair"))
                is_lg = any(k in ent_lower or k in name_lower for k in ("camera", "cameretta", "lg", "thinq"))
                is_thermostat = "termostato" in ent_lower or "thermostat" in ent_lower

                if is_fujitsu:
                    cat_label = "Climatizzatore Fujitsu FGLair"
                    model_name = "Fujitsu General FGLair (AC-UTY)"
                    brand = "Fujitsu"
                elif is_lg:
                    cat_label = "Climatizzatore LG ThinQ"
                    model_name = "LG Dual Inverter"
                    brand = "LG"
                elif is_thermostat:
                    cat_label = "Cronotermostato Smart"
                    model_name = "Cronotermostato Smart"
                    brand = "Smart Home"
                else:
                    cat_label = "Climatizzatore Inverter"
                    model_name = "Climatizzatore Inverter"
                    brand = "Smart Home"

                t_curr = attributes.get("current_temperature")
                t_target = attributes.get("temperature")
                fan_mode = attributes.get("fan_mode") or "AUTO"

                # Recupera telemetria specifica
                tel = telemetry_map.get(base_key, {})
                if is_fujitsu and not tel:
                    tel = telemetry_map.get("climatizzatore", {})
                
                volt_v = tel.get("voltage_v")
                curr_a = tel.get("current_a")
                energy_kwh = tel.get("energy_total_kwh")
                energy_wh = tel.get("energy_today_wh")

                status_parts = []
                status_parts.append("Acceso" if is_on else "Spento")
                if t_curr is not None:
                    if is_on and t_target is not None:
                        status_parts.append(f"{t_curr}°C (Set: {t_target}°C)")
                    else:
                        status_parts.append(f"{t_curr}°C")
                if is_on and power_w > 0:
                    status_parts.append(f"{power_w:.0f} W")

                status_text = " • ".join(status_parts)
                extra_fields = {
                    "current_temp": t_curr,
                    "temp_current": t_curr,
                    "target_temp": t_target,
                    "temp_set": t_target,
                    "mode": mode,
                    "job_mode": mode,
                    "fan_speed": str(fan_mode).upper(),
                    "hvac_modes": attributes.get("hvac_modes", []),
                    "fan_modes": attributes.get("fan_modes", []),
                    "swing_mode": attributes.get("swing_mode"),
                    "rotate_up_down": bool(attributes.get("swing_mode") and str(attributes.get("swing_mode")).lower() not in ("off", "none")),
                    "model_name": model_name,
                    "brand": brand,
                    "voltage_v": volt_v,
                    "current_a": curr_a,
                    "energy_total_kwh": energy_kwh,
                    "energy_today_wh": energy_wh
                }
            elif is_shutter:
                cat = "shutters"
                is_on = state_str in ("open", "on")
                icon = "🪟"
                cat_label = "Persiana / Tenda"
                status_text = f"Stato: {state_obj.get('state', 'N/D').upper()}"
            elif is_irrigation:
                cat = "irrigation"
                is_on = state_str in ("open", "on")
                icon = "💧"
                cat_label = "Elettrovalvola / Irrigazione"
                status_text = f"Stato: {state_obj.get('state', 'N/D').upper()}"
            elif domain == "light" or dev_class == "light":
                cat = "plugs"
                is_on = state_str in ("on", "open") if is_online else None
                icon = "💡"
                cat_label = "Luce Smart"
                status_text = f"Stato: {state_obj.get('state', 'N/D').upper()}"
            elif domain == "switch":
                cat = "plugs"
                is_on = state_str in ("on", "open") if is_online else None
                icon = "🔌"
                cat_label = "Presa Smart"
                status_text = f"Stato: {state_obj.get('state', 'N/D').upper()}"
            elif domain == "media_player":
                cat = "appliances"
                is_on = state_str in ("on", "playing", "idle") if is_online else None
                icon = "📺"
                cat_label = "Smart TV / Media"
                status_text = f"Stato: {state_obj.get('state', 'N/D').upper()}"
            else:
                cat = "generic"
                is_on = state_str in ("on", "open") if is_online else None
                icon = "📱"
                cat_label = "Dispositivo Smart"
                status_text = f"Stato: {state_obj.get('state', 'N/D').upper()}"

            if power_w > 0 and domain != "climate":
                status_text += f" • {power_w:.1f} W"

            dev_dict = {
                "id": f"hass_{entity_id}",
                "raw_id": entity_id,
                "ecosystem": "homeassistant",
                "name": friendly_name,
                "icon": icon,
                "category": cat,
                "category_label": f"{cat_label} • HA",
                "is_on": is_on,
                "can_toggle": domain in ("switch", "light", "valve", "cover", "media_player", "climate"),
                "is_online": is_online,
                "status_text": status_text,
                "power_w": power_w,
                "raw": state_obj
            }
            dev_dict.update(extra_fields)
            devices.append(dev_dict)

        return devices
