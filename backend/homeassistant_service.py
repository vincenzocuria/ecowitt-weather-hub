"""
Modulo di integrazione unificato per Home Assistant (Hub Domotico Locale).
Gestisce in tempo reale e in locale:
- Elettrodomestici Samsung (Lavatrice, Lavastoviglie, TV)
- Dispositivi Tuya & Zigbee (Prese smart, Elettrovalvole, Clima, Persiane)
- Sensore Presenza e Batteria Smartphone (Companion App / Person / Device Tracker)
- Calcolo Sinergia Solare Aton per avvio carichi ottimali
- Controllo irrigazione con timer e spegnimento d'emergenza pioggia
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
import aiohttp

from backend.config import settings

logger = logging.getLogger("weather_hub.homeassistant")

# Mappe etichette in italiano
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


class HomeAssistantService:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.entities: Dict[str, Dict[str, Any]] = {}
        self.is_connected: bool = False
        self.last_sync_time: float = 0.0
        self.sync_error: Optional[str] = None
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return settings.HASS_ENABLED and bool(settings.HASS_TOKEN)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.HASS_TOKEN}",
            "Content-Type": "application/json"
        }

    async def get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=8.0)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    async def check_connection(self) -> bool:
        """Verifica se Home Assistant è raggiungibile e il token è valido."""
        if not self.enabled:
            self.is_connected = False
            return False

        try:
            session = await self.get_session()
            url = f"{settings.HASS_URL}/api/"
            async with session.get(url, headers=self._headers()) as resp:
                if resp.status == 200:
                    self.is_connected = True
                    self.sync_error = None
                    return True
                else:
                    self.is_connected = False
                    self.sync_error = f"HTTP {resp.status}"
                    return False
        except Exception as e:
            self.is_connected = False
            self.sync_error = str(e)
            return False

    async def fetch_states(self) -> List[Dict[str, Any]]:
        """Recupera tutti gli stati delle entità da Home Assistant."""
        if not self.enabled:
            return []

        try:
            session = await self.get_session()
            url = f"{settings.HASS_URL}/api/states"
            async with session.get(url, headers=self._headers()) as resp:
                if resp.status == 200:
                    states = await resp.json()
                    self.is_connected = True
                    self.last_sync_time = time.time()
                    self.sync_error = None
                    
                    async with self._lock:
                        self.entities = {s["entity_id"]: s for s in states if "entity_id" in s}
                    return states
                else:
                    self.is_connected = False
                    self.sync_error = f"HTTP {resp.status}"
                    return []
        except Exception as e:
            logger.warning("Errore comunicazione Home Assistant: %s", e)
            self.is_connected = False
            self.sync_error = str(e)
            return []

    # ---------------------------------------------------------
    # PARSER ELETTRODOMESTICI SAMSUNG (LAVATRICE & LAVASTOVIGLIE)
    # ---------------------------------------------------------
    def parse_washer_data(self) -> Optional[Dict[str, Any]]:
        """Estrae e struttura lo stato completo della Lavatrice Samsung da Home Assistant."""
        if not self.entities:
            return None

        # Cerca entità rilevanti della lavatrice
        machine_state_ent = self.entities.get("sensor.lavanderia_lavatrice_machine_state")
        job_state_ent = self.entities.get("sensor.lavanderia_lavatrice_job_state")
        completion_ent = self.entities.get("sensor.lavanderia_lavatrice_completion_time")
        temp_ent = self.entities.get("select.lavanderia_lavatrice_temperatura_dell_acqua")
        spin_ent = self.entities.get("select.lavanderia_lavatrice_spin_level")
        detergent_ent = self.entities.get("select.lavanderia_lavatrice_detergent_dispense_amount")
        softener_ent = self.entities.get("select.lavanderia_lavatrice_flexible_compartment_dispense_amount")
        rinse_ent = self.entities.get("number.lavanderia_lavatrice_rinse_cycles")
        power_ent = self.entities.get("sensor.lavanderia_lavatrice_potenza") or self.entities.get("sensor.lavasciuga_potenza")
        energy_ent = self.entities.get("sensor.lavanderia_lavatrice_energia")
        water_ent = self.entities.get("sensor.lavanderia_lavatrice_water_consumption")
        bubble_switch = self.entities.get("switch.lavanderia_lavatrice_bubble_soak")

        if not machine_state_ent and not job_state_ent:
            # Nessuna entità lavatrice trovata
            return None

        machine_state = (machine_state_ent.get("state") if machine_state_ent else "stop") or "stop"
        job_state = (job_state_ent.get("state") if job_state_ent else "none") or "none"
        
        m_lower = machine_state.lower()
        j_lower = job_state.lower()

        is_running = m_lower in ("run", "running") and j_lower not in ("none", "finish", "delay_wash", "delayend")
        is_on = m_lower in ("run", "running", "pause", "paused", "ready") or j_lower in ("run", "wash", "rinse", "spin", "drying", "delay_wash")

        job_state_label = WASHER_STATE_MAP.get(j_lower, job_state.capitalize())

        # Calcolo tempo residuo e completamento stimato
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

        # Temperatura e Centrifuga
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

        # Potenza istantanea
        power_w = 0.0
        if power_ent and power_ent.get("state") not in ("unavailable", "unknown", None):
            try:
                power_w = float(power_ent.get("state") or 0.0)
            except (ValueError, TypeError):
                power_w = 0.0

        return {
            "device_id": "lavanderia_lavatrice",
            "name": "Lavatrice Samsung",
            "is_connected": True,
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

    def parse_dishwasher_data(self) -> Optional[Dict[str, Any]]:
        """Estrae e struttura lo stato completo della Lavastoviglie Samsung da Home Assistant."""
        if not self.entities:
            return None

        machine_state_ent = self.entities.get("sensor.cucina_lavastoviglie_machine_state")
        job_state_ent = self.entities.get("sensor.cucina_lavastoviglie_job_state")
        completion_ent = self.entities.get("sensor.cucina_lavastoviglie_completion_time")
        zone_ent = self.entities.get("select.cucina_lavastoviglie_selected_zone")
        power_ent = self.entities.get("sensor.lavastoviglie_potenza")
        energy_ent = self.entities.get("sensor.lavastoviglie_energia_totale")

        if not machine_state_ent and not job_state_ent:
            return None

        machine_state = (machine_state_ent.get("state") if machine_state_ent else "stop") or "stop"
        job_state = (job_state_ent.get("state") if job_state_ent else "none") or "none"
        
        m_lower = machine_state.lower()
        j_lower = job_state.lower()

        is_running = m_lower in ("run", "running") or j_lower in ("pre_wash", "prewash", "wash", "rinse", "dry", "drying", "cooling", "drain", "pre_drain", "sanitize")
        is_paused = m_lower in ("pause", "paused") or j_lower in ("pause", "paused")
        is_on = is_running or is_paused or m_lower in ("ready", "delay_start")

        if is_running and j_lower in ("none", "ready"):
            job_state_label = "Lavaggio in Corso 🍽️"
        elif is_paused:
            job_state_label = "In Pausa ⏸️"
        else:
            job_state_label = DISHWASHER_STATE_MAP.get(j_lower, job_state.capitalize() if job_state else "In Standby / Pronto")

        # Completamento e tempo residuo
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
            "is_connected": True,
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

    # ---------------------------------------------------------
    # PARSER PRESENZA & BATTERIA SMARTPHONE (PERSON / COMPANION)
    # ---------------------------------------------------------
    def parse_presence_data(self) -> Dict[str, Any]:
        """Estrae la presenza e il livello batteria dello smartphone da Home Assistant."""
        is_present = True
        device_name = "Smartphone"
        battery_pct: Optional[int] = None

        # Cerca person.vincenzo_curia o qualsiasi entità person
        person_ent = None
        for ent_id, ent in self.entities.items():
            if ent_id.startswith("person."):
                person_ent = ent
                device_name = ent.get("attributes", {}).get("friendly_name") or "Smartphone"
                st = (ent.get("state") or "").lower()
                if st == "home":
                    is_present = True
                elif st in ("not_home", "away"):
                    is_present = False
                break

        # Cerca sensore batteria associato a telefono o persona
        for ent_id, ent in self.entities.items():
            if ent_id.startswith("sensor.") and any(k in ent_id for k in ("_battery_level", "_livello_batteria", "_battery", "_batteria")):
                # Ignora sensori di dispositivi fissi (es. aiuola)
                if "aiuola" in ent_id or "backup" in ent_id:
                    continue
                try:
                    val = float(ent.get("state") or 0.0)
                    battery_pct = int(round(val))
                    break
                except (ValueError, TypeError):
                    pass

        return {
            "device_id": "ha_presence_phone",
            "name": device_name,
            "device_name": device_name,
            "is_present": is_present,
            "presence_label": "A Casa 🏠" if is_present else "Fuori Casa 🚗",
            "battery_percent": battery_pct,
            "battery_pct": battery_pct
        }

    # ---------------------------------------------------------
    # RIEPILOGO UNIFICATO (SINERGIE SOLARI, ELETTRODOMESTICI, METEO)
    # ---------------------------------------------------------
    def get_summary(
        self,
        energy_latest: Optional[Dict[str, Any]] = None,
        drying_index: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Produce un riepilogo strutturato per dashboard, alert engine e automazioni."""
        washer_data = self.parse_washer_data()
        dishwasher_data = self.parse_dishwasher_data()
        presence_data = self.parse_presence_data()

        p_solare = 0.0
        soc = 0.0
        if energy_latest:
            p_solare = float(energy_latest.get("p_solare") if energy_latest.get("p_solare") is not None else (energy_latest.get("solar_power_w") or 0.0))
            soc = float(energy_latest.get("soc") if energy_latest.get("soc") is not None else (energy_latest.get("battery_soc_pct") or 0.0))

        # Sinergia Solare Aton per Elettrodomestici
        solar_optimal = False
        solar_message = "Produzione solare assente o insufficiente per avvio elettrodomestici a costo zero."
        solar_badge_class = "badge-neutral"

        if p_solare >= 1500 or (p_solare >= 800 and soc >= 60) or soc >= 85:
            solar_optimal = True
            solar_badge_class = "badge-success"
            if p_solare >= 1800:
                solar_message = f"Momento Ideale: Surplus Solare Fotovoltaico ({int(p_solare)} W) sufficiente per lavaggi a Costo Zero!"
            elif soc >= 70:
                solar_message = f"Momento Favorevole: Batteria Aton carica ({int(soc)}%) e {int(p_solare)} W solari disponibili."
            else:
                solar_message = f"Energia Solare disponibile ({int(p_solare)} W)."

        # Sinergia Lavatrice + Meteo Asciugatura Bucato
        laundry_drying_synergy = None
        if washer_data and drying_index:
            dry_score = drying_index.get("score", 0)
            dry_desc = drying_index.get("desc", "")
            
            if washer_data.get("is_running"):
                if dry_score >= 60:
                    laundry_drying_synergy = {
                        "optimal": True,
                        "badge": "🟢 Stendi all'aperto",
                        "text": f"Il lavaggio terminerà a breve e le condizioni meteo esterne sono ottime per asciugare il bucato all'aperto ({dry_desc})."
                    }
                else:
                    laundry_drying_synergy = {
                        "optimal": False,
                        "badge": "🟡 Asciugatura lenta / sconsigliata",
                        "text": f"Attenzione: clima esterno poco favorevole per stendere ({dry_desc})."
                    }

        # Riepilogo Irrigazione
        valve_aiuola = self.entities.get("valve.aiuola_valve", {})
        valve_aiuola_2 = self.entities.get("valve.aiuola_valve_2", {})
        valve_is_open = valve_aiuola.get("state") == "open" or valve_aiuola_2.get("state") == "open"

        return {
            "enabled": self.enabled,
            "is_connected": self.is_connected,
            "last_sync": self.last_sync_time,
            "error": self.sync_error,
            "washer": washer_data,
            "dishwasher": dishwasher_data,
            "presence": presence_data,
            "solar_synergy": {
                "solar_optimal": solar_optimal,
                "solar_message": solar_message,
                "solar_badge_class": solar_badge_class,
                "p_solare": p_solare,
                "soc": soc
            },
            "laundry_drying_synergy": laundry_drying_synergy,
            "irrigation": {
                "is_open": valve_is_open,
                "valves": [
                    {"id": "valve.aiuola_valve", "name": "Aiuola", "state": valve_aiuola.get("state", "closed")},
                    {"id": "valve.aiuola_valve_2", "name": "Aiuola 2", "state": valve_aiuola_2.get("state", "closed")}
                ]
            }
        }

    # ---------------------------------------------------------
    # CATALOGO COMPLETO DEI DISPOSITIVI DI CASA
    # ---------------------------------------------------------
    def get_catalog_devices(self) -> List[Dict[str, Any]]:
        """Restituisce le entità rilevanti formattate per il catalogo unificato con abbinamento potenza."""
        if not self.enabled or not self.entities:
            return []

        # Mappa veloce sensori di potenza/consumo (es: sensor.cisterna_potenza -> 9.0 W)
        power_map: Dict[str, float] = {}
        for entity_id, state_obj in self.entities.items():
            if entity_id.startswith("sensor.") and any(k in entity_id for k in ("_potenza", "_power", "_consumption")):
                try:
                    p_val = float(state_obj.get("state") or 0.0)
                    base_key = entity_id.replace("sensor.", "").replace("_potenza", "").replace("_power", "").replace("_consumption", "")
                    power_map[base_key] = p_val
                except (ValueError, TypeError):
                    pass

        devices = []

        # 1. Lavatrice Samsung
        washer = self.parse_washer_data()
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
                "is_online": True,
                "status_text": washer.get("job_state_label", "In Standby"),
                "power_w": washer.get("power_w", 0.0),
                "completion_time": washer.get("finish_estimate"),
                "cycle_name": washer.get("water_temp"),
                "raw": washer
            })

        # 2. Lavastoviglie Samsung
        dish = self.parse_dishwasher_data()
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
                "is_online": True,
                "status_text": dish.get("job_state_label", "In Standby"),
                "power_w": dish.get("power_w", 0.0),
                "completion_time": dish.get("finish_estimate"),
                "cycle_name": dish.get("cycle_name"),
                "raw": dish
            })

        # 3. Presenza Smartphone
        presence = self.parse_presence_data()
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

        # 4. Interruttori, Luci, Clima, Valvole, Tende
        for entity_id, state_obj in self.entities.items():
            domain = entity_id.split(".")[0]
            if domain not in ("switch", "light", "climate", "cover", "valve", "fan", "media_player"):
                continue

            # Filtra pulsanti e switch interni secondari di configurazione
            if any(k in entity_id for k in ("blocco_bambini", "child_lock", "bubble_soak", "speed_booster", "sanitize")):
                continue

            attributes = state_obj.get("attributes", {})
            friendly_name = attributes.get("friendly_name") or entity_id
            state_str = (state_obj.get("state") or "").lower()
            is_on = state_str in ("on", "open", "cleaning", "cooling", "heating", "playing") if state_str not in ("unavailable", "unknown") else None
            is_online = state_str not in ("unavailable", "unknown")

            # Estrai potenza dagli attributi o dalla mappa sensori correlata
            base_key = entity_id.split(".")[1].replace("_socket_1", "").replace("_presa", "").replace("_valve", "")
            power_w = float(attributes.get("current_power_w") or attributes.get("power") or attributes.get("current_consumption") or power_map.get(base_key, 0.0))

            if domain in ("switch", "light"):
                cat = "plugs"
                icon = "💡" if domain == "light" else "🔌"
                cat_label = "Luce Smart" if domain == "light" else "Presa Smart"
            elif domain == "valve":
                cat = "irrigation"
                icon = "💧"
                cat_label = "Elettrovalvola / Irrigazione"
            elif domain == "climate":
                cat = "climate"
                icon = "❄️"
                cat_label = "Climatizzatore / Termostato"
            elif domain == "cover":
                cat = "shutters"
                icon = "🪟"
                cat_label = "Persiana / Tenda"
            elif domain == "media_player":
                cat = "appliances"
                icon = "📺"
                cat_label = "Smart TV / Media"
            else:
                cat = "generic"
                icon = "📱"
                cat_label = "Dispositivo Smart"

            status_text = f"Stato: {state_obj.get('state', 'N/D').upper()}"
            if power_w > 0:
                status_text += f" • {power_w:.1f} W"

            devices.append({
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
            })
        return devices

    # ---------------------------------------------------------
    # CONTROLLO COMANDI & SERVIZI HOME ASSISTANT
    # ---------------------------------------------------------
    async def call_service(self, domain: str, service: str, entity_id: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Chiama un servizio su Home Assistant (es. switch/turn_on, climate/set_temperature)."""
        if not self.enabled:
            return {"success": False, "error": "Home Assistant non configurato o disabilitato"}

        payload = {"entity_id": entity_id}
        if data:
            payload.update(data)

        try:
            session = await self.get_session()
            url = f"{settings.HASS_URL}/api/services/{domain}/{service}"
            async with session.post(url, headers=self._headers(), json=payload) as resp:
                if resp.status in (200, 201):
                    res_json = await resp.json()
                    logger.info("✅ [HASS] Servizio %s.%s eseguito su %s", domain, service, entity_id)
                    await self.fetch_states()
                    return {"success": True, "result": res_json}
                else:
                    err_txt = await resp.text()
                    logger.error("❌ [HASS] Errore chiamata servizio %s.%s (HTTP %s): %s", domain, service, resp.status, err_txt)
                    return {"success": False, "error": f"HTTP {resp.status}: {err_txt}"}
        except Exception as e:
            logger.error("❌ [HASS] Errore connessione servizio %s: %s", entity_id, e)
            return {"success": False, "error": str(e)}

    async def toggle_device(self, entity_id: str, target_state: bool) -> Dict[str, Any]:
        """Accende o spegne un'entità su Home Assistant."""
        # Se entity_id non contiene il punto, prova a risolverlo
        if "." not in entity_id:
            resolved = self.find_entity_by_tuya_id(entity_id)
            if resolved:
                entity_id = resolved
            else:
                entity_id = f"switch.{entity_id}"

        domain = entity_id.split(".")[0]
        if domain in ("switch", "light", "fan"):
            service = "turn_on" if target_state else "turn_off"
            return await self.call_service(domain, service, entity_id)
        elif domain == "valve":
            service = "open_valve" if target_state else "close_valve"
            return await self.call_service(domain, service, entity_id)
        elif domain == "cover":
            service = "open_cover" if target_state else "close_cover"
            return await self.call_service(domain, service, entity_id)
        elif domain == "climate":
            service = "turn_on" if target_state else "turn_off"
            return await self.call_service(domain, service, entity_id)
        elif domain == "media_player":
            service = "turn_on" if target_state else "turn_off"
            return await self.call_service(domain, service, entity_id)
        return {"success": False, "error": f"Dominio {domain} non supporta toggle diretto"}

    async def open_irrigation(self, entity_id: str = "valve.aiuola_valve", duration_minutes: int = 10) -> Dict[str, Any]:
        """Apre l'elettrovalvola di irrigazione specificata su Home Assistant."""
        clean_id = entity_id if "." in entity_id else "valve.aiuola_valve"
        # Se presente entità durata su HA, impostala prima
        if "aiuola" in clean_id and "number.aiuola_irrigation_duration" in self.entities:
            try:
                await self.call_service("number", "set_value", "number.aiuola_irrigation_duration", {"value": float(duration_minutes * 60)})
            except Exception:
                pass
        return await self.call_service("valve", "open_valve", clean_id)

    async def close_irrigation(self, entity_id: str = "valve.aiuola_valve") -> Dict[str, Any]:
        """Chiude l'elettrovalvola di irrigazione su Home Assistant."""
        clean_id = entity_id if "." in entity_id else "valve.aiuola_valve"
        return await self.call_service("valve", "close_valve", clean_id)

    async def control_cover(self, entity_id: str = "cover.persiana_tenda", action: str = "open") -> Dict[str, Any]:
        """Controlla persiane/tende su Home Assistant (open, close, stop, set_position)."""
        clean_id = entity_id if "." in entity_id else "cover.persiana_tenda"
        if action == "open":
            return await self.call_service("cover", "open_cover", clean_id)
        elif action == "close":
            return await self.call_service("cover", "close_cover", clean_id)
        elif action == "stop":
            return await self.call_service("cover", "stop_cover", clean_id)
        return {"success": False, "error": f"Azione {action} non riconosciuta per cover"}

    async def set_climate_temp(self, entity_id: str = "climate.termostato", temp_c: float = 21.0) -> Dict[str, Any]:
        """Imposta la temperatura del termostato su Home Assistant."""
        clean_id = entity_id if "." in entity_id else "climate.termostato"
        return await self.call_service("climate", "set_temperature", clean_id, {"temperature": float(temp_c)})

    def find_entity_by_tuya_id(self, device_id: str) -> Optional[str]:
        """Mappa un vecchio ID Tuya o nome dispositivo alla corrispondente entità Home Assistant."""
        tuya_id_map = {
            "04564850cc50e3d1ca35": "switch.cisterna_presa",
            "bfe099fb503c352edeq28i": "switch.lavasciuga_socket_1",
            "bfb7123e755a2ce701p0xd": "switch.lavastoviglie_socket_1",
            "bf0d071d55d193bc3fxwmp": "switch.climatizzatore_socket_1",
            "bf4a39d41904562ce8gssc": "valve.aiuola_valve",
            "30148414807d3a287c81": "cover.persiana_tenda",
            "5402285098f4abbc53a3": "climate.termostato"
        }
        if device_id in tuya_id_map:
            return tuya_id_map[device_id]

        for ent_id in self.entities:
            if device_id in ent_id:
                return ent_id
        return None

    async def worker_loop(self):
        """Loop di polling periodico per mantenere aggiornato lo stato delle entità locali."""
        logger.info("🏠 [HASS] Worker loop Home Assistant avviato (intervallo: %ss)", settings.HASS_POLL_INTERVAL_SEC)
        while True:
            try:
                if self.enabled:
                    await self.fetch_states()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Errore nel ciclo di aggiornamento Home Assistant: %s", e)
            await asyncio.sleep(max(5, settings.HASS_POLL_INTERVAL_SEC))

    def stop(self):
        pass

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

homeassistant_service = HomeAssistantService()

