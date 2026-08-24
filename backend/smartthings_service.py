"""
Modulo di integrazione per Samsung SmartThings Cloud API.
Gestisce il monitoraggio e il controllo degli elettrodomestici smart (Lavatrice, Lavastoviglie)
e sensori di presenza (S25 Ultra), calcolando sinergie energetiche in tempo reale
con l'impianto fotovoltaico / accumulo Aton e la stazione meteo Ecowitt.
"""

import asyncio
import logging
import ssl
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
import aiohttp

from backend.config import settings

logger = logging.getLogger("SmartThingsService")

SMARTTHINGS_API_BASE = "https://api.smartthings.com/v1"


# Mappe etichette in italiano
WASHER_STATE_MAP = {
    "none": "In Standby / Pronto",
    "weightSensing": "Pesatura Carico & Bilanciamento",
    "wash": "Lavaggio in Corso 🫧",
    "rinse": "Risciacquo in Corso 💧",
    "spin": "Centrifuga in Corso 🌀",
    "drying": "Asciugatura in Corso ♨️",
    "finish": "Ciclo Lavaggio Completato ✅",
    "delayEnd": "Partenza Ritardata Programmata ⏱️",
    "freezePrevent": "Protezione Antigelo",
}

DISHWASHER_STATE_MAP = {
    "none": "In Standby / Pronto",
    "ready": "Pronto",
    "prewash": "Prelavaggio 🫧",
    "wash": "Lavaggio in Corso 🍽️",
    "rinse": "Risciacquo 💧",
    "dry": "Asciugatura Piatti ♨️",
    "cooling": "Raffreddamento Piatti 🌬️",
    "drain": "Scarico Acqua 💧",
    "sanitize": "Ciclo Igienizzante (Sanitize 🧼)",
    "finish": "Ciclo Lavastoviglie Terminato ✅",
    "delayStart": "Partenza Ritardata ⏱️",
    "paused": "In Pausa ⏸️",
    "pause": "In Pausa ⏸️",
    "running": "Lavaggio in Corso 🍽️",
    "run": "Lavaggio in Corso 🍽️",
}

DISHWASHER_CYCLE_MAP = {
    "auto": "Auto",
    "eco": "Eco",
    "standard": "Standard / Normale",
    "normal": "Normale",
    "intensive": "Intensivo / Pentole",
    "quick": "Rapido / Express",
    "delicate": "Delicato / Cristalli",
    "sanitize": "Igienizzante ad Alta Temp 🧼",
    "rinseAndDry": "Risciacquo & Asciugatura",
    "selfClean": "Autopulizia Macchina",
    "rinsePlus": "Risciacquo Plus",
    "babyCare": "Baby Care",
}


import os
import json
import base64

class SmartThingsService:
    def __init__(self):
        self.token = settings.SMARTTHINGS_PAT
        self.refresh_token_str = settings.SMARTTHINGS_REFRESH_TOKEN
        self.client_id = settings.SMARTTHINGS_CLIENT_ID
        self.client_secret = settings.SMARTTHINGS_CLIENT_SECRET

        self.enabled = settings.SMARTTHINGS_ENABLED and (bool(self.token) or bool(self.refresh_token_str))
        self.poll_interval = settings.SMARTTHINGS_POLL_INTERVAL_SEC
        self.devices: List[Dict[str, Any]] = []

        self.device_statuses: Dict[str, Dict[str, Any]] = {}
        self.last_sync_time: Optional[float] = None
        self.sync_error: Optional[str] = None
        self.is_connected = False
        self._session: Optional[aiohttp.ClientSession] = None
        self.cache_file = os.path.join(settings.DATA_DIR, "smartthings_cache.json")
        self._load_cache()

    def _load_cache(self):
        """Carica lo stato dei dispositivi e le chiavi OAuth persistiti su disco."""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.devices = data.get("devices", [])
                    self.device_statuses = data.get("device_statuses", {})
                    self.last_sync_time = data.get("last_sync_time")
                    saved_token = data.get("access_token")
                    saved_refresh = data.get("refresh_token")
                    if saved_token:
                        self.token = saved_token
                    if saved_refresh:
                        self.refresh_token_str = saved_refresh
                    if self.devices:
                        logger.info(f"📂 [SmartThings] Caricati {len(self.devices)} dispositivi dalla cache locale persistente.")
        except Exception as e:
            logger.warning(f"⚠️ [SmartThings] Impossibile caricare la cache da disco: {e}")

    def _save_cache(self):
        """Salva lo stato dei dispositivi e le chiavi OAuth su file JSON in modo atomico."""
        try:
            os.makedirs(settings.DATA_DIR, exist_ok=True)
            tmp_path = f"{self.cache_file}.tmp"
            payload = {
                "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "devices": self.devices,
                "device_statuses": self.device_statuses,
                "last_sync_time": self.last_sync_time,
                "access_token": self.token,
                "refresh_token": self.refresh_token_str
            }
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.cache_file)
        except Exception as e:
            logger.warning(f"⚠️ [SmartThings] Impossibile salvare la cache su disco: {e}")

    async def refresh_access_token(self) -> bool:
        """Rinnova in automatico l'access_token SmartThings usando il refresh_token OAuth 2.0 in background."""
        ref_tok = self.refresh_token_str or settings.SMARTTHINGS_REFRESH_TOKEN
        c_id = self.client_id or settings.SMARTTHINGS_CLIENT_ID
        c_sec = self.client_secret or settings.SMARTTHINGS_CLIENT_SECRET
        
        if not ref_tok or not c_id or not c_sec:
            return False

        try:
            url = "https://api.smartthings.com/oauth/token"
            auth_header = base64.b64encode(f"{c_id}:{c_sec}".encode()).decode()
            headers = {
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            data = {
                "grant_type": "refresh_token",
                "refresh_token": ref_tok,
                "client_id": c_id
            }

            await self.close()
            session = await self.get_session()

            async with session.post(url, headers=headers, data=data) as resp:
                if resp.status == 200:
                    res_json = await resp.json()
                    new_acc = res_json.get("access_token")
                    new_ref = res_json.get("refresh_token")
                    if new_acc:
                        self.token = new_acc
                        if new_ref:
                            self.refresh_token_str = new_ref
                        self.is_connected = True
                        self.sync_error = None
                        self._save_cache()
                        logger.info("✅ [SmartThings] Token OAuth 2.0 rinnovato in automatico con successo!")
                        return True
                else:
                    err_body = await resp.text()
                    logger.warning(f"⚠️ [SmartThings] Rinnovo OAuth 2.0 non riuscito (HTTP {resp.status}): {err_body[:180]}")
        except Exception as e:
            logger.error(f"❌ [SmartThings] Eccezione durante il rinnovo token OAuth 2.0: {e}")
        return False

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                resolver=aiohttp.ThreadedResolver(),
                ssl=True
            )
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            self._session = aiohttp.ClientSession(
                connector=connector,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15)
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def fetch_devices_list(self) -> List[Dict[str, Any]]:
        """Recupera l'elenco completo dei dispositivi associati all'account."""
        if not self.enabled:
            return self.devices

        session = await self.get_session()
        try:
            url = f"{SMARTTHINGS_API_BASE}/devices"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self.devices = data.get("items", [])
                    self.is_connected = True
                    self.sync_error = None
                    self._save_cache()
                    return self.devices
                elif resp.status == 401:
                    # Tenta il rinnovo automatico tramite OAuth2 Refresh Token
                    if await self.refresh_access_token():
                        session_retry = await self.get_session()
                        async with session_retry.get(url) as resp_retry:
                            if resp_retry.status == 200:
                                data_retry = await resp_retry.json()
                                self.devices = data_retry.get("items", [])
                                self.is_connected = True
                                self.sync_error = None
                                self._save_cache()
                                return self.devices

                    err_txt = await resp.text()
                    self.is_connected = False
                    self.sync_error = f"HTTP {resp.status}: {err_txt[:150]}"
                    logger.error(f"Errore recupero lista dispositivi SmartThings: {self.sync_error}")
                    return self.devices
                else:
                    err_txt = await resp.text()
                    self.is_connected = False
                    self.sync_error = f"HTTP {resp.status}: {err_txt[:150]}"
                    logger.error(f"Errore recupero lista dispositivi SmartThings: {self.sync_error}")
                    return self.devices
        except Exception as e:
            self.is_connected = False
            self.sync_error = str(e)
            logger.error(f"Eccezione durante fetch_devices_list SmartThings: {e}")
            return self.devices

    async def fetch_device_status(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Recupera lo stato attuale delle capability di un singolo dispositivo."""
        session = await self.get_session()
        try:
            url = f"{SMARTTHINGS_API_BASE}/devices/{device_id}/status"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self.device_statuses[device_id] = data
                    self._save_cache()
                    return data
                elif resp.status == 401:
                    if await self.refresh_access_token():
                        session_retry = await self.get_session()
                        async with session_retry.get(url) as resp_retry:
                            if resp_retry.status == 200:
                                data_retry = await resp_retry.json()
                                self.device_statuses[device_id] = data_retry
                                self._save_cache()
                                return data_retry
                    logger.warning(f"Status per dispositivo {device_id} ha risposto HTTP {resp.status}")
                    return self.device_statuses.get(device_id)
                else:
                    logger.warning(f"Status per dispositivo {device_id} ha risposto HTTP {resp.status}")
                    return self.device_statuses.get(device_id)
        except Exception as e:
            logger.warning(f"Errore recupero status dispositivo {device_id}: {e}")
            return self.device_statuses.get(device_id)

    async def sync_all(self):
        """Sincronizza tutti i dispositivi SmartThings monitorati."""
        if not self.enabled:
            return

        devs = await self.fetch_devices_list()
        if not devs:
            return

        tasks = []
        for d in devs:
            dev_id = d.get("deviceId")
            if dev_id:
                tasks.append(self.fetch_device_status(dev_id))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self.last_sync_time = time.time()
        self._save_cache()
        logger.info(f"Sincronizzazione SmartThings completata: {len(self.device_statuses)} stati aggiornati.")

    def parse_washer_data(self, status: Dict[str, Any], dev_info: Dict[str, Any]) -> Dict[str, Any]:
        """Estrae e normalizza i dati della Lavatrice Samsung."""
        main_comp = status.get("components", {}).get("main", {})
        
        switch_val = main_comp.get("switch", {}).get("switch", {}).get("value", "off")
        is_on = switch_val == "on"

        # Stato operativo
        op_comp = main_comp.get("washerOperatingState", {})
        job_state = op_comp.get("washerJobState", {}).get("value", "none") or "none"
        machine_state = op_comp.get("machineState", {}).get("value", "stop") or "stop"
        
        job_state_label = WASHER_STATE_MAP.get(job_state, job_state.capitalize())

        # Temperatura acqua
        water_temp = main_comp.get("custom.washerWaterTemperature", {}).get("washerWaterTemperature", {}).get("value")
        water_temp_label = f"{water_temp}°C" if water_temp and water_temp != "none" and water_temp != "cold" else ("Fredda" if water_temp == "cold" else "Auto")

        # Centrifuga e risciacqui
        spin_speed = main_comp.get("custom.washerSpinSpeed", {}).get("washerSpinSpeed", {}).get("value")
        spin_label = f"{spin_speed} rpm" if spin_speed and spin_speed not in ["none", "noSpin"] else ("Senza centrifuga" if spin_speed == "noSpin" else "Auto")
        
        rinse_cycles = main_comp.get("custom.washerRinseCycles", {}).get("washerRinseCycles", {}).get("value")

        # Tempo rimanente
        delay_end = main_comp.get("samsungce.washerDelayEnd", {}).get("remainingTime", {}).get("value")
        comp_remaining = op_comp.get("completionTime", {}).get("value")
        
        remaining_min = delay_end if delay_end is not None else None
        
        finish_estimate = None
        if remaining_min and remaining_min > 0:
            finish_dt = datetime.now() + timedelta(minutes=remaining_min)
            finish_estimate = finish_dt.strftime("%H:%M")

        # Detersivo & Ammorbidente
        softener_amount = main_comp.get("samsungce.autoDispenseSoftener", {}).get("remainingAmount", {}).get("value", "standard")
        detergent_amount = main_comp.get("samsungce.flexibleAutoDispenseDetergent", {}).get("remainingAmount", {}).get("value", "standard")

        is_running = is_on and machine_state in ["run", "running"] and job_state not in ["none", "finish", "delayEnd"]

        return {
            "device_id": dev_info.get("deviceId"),
            "name": dev_info.get("label") or dev_info.get("name") or "Lavatrice",
            "is_on": is_on,
            "is_running": is_running,
            "machine_state": machine_state,
            "job_state": job_state,
            "job_state_label": job_state_label,
            "water_temp": water_temp_label,
            "spin_speed": spin_label,
            "rinse_cycles": rinse_cycles,
            "remaining_min": remaining_min,
            "finish_estimate": finish_estimate,
            "softener_level": softener_amount,
            "detergent_level": detergent_amount
        }

    def parse_dishwasher_data(self, status: Dict[str, Any], dev_info: Dict[str, Any]) -> Dict[str, Any]:
        """Estrae e normalizza i dati della Lavastoviglie Samsung SmartThings."""
        components = status.get("components", {})
        main_comp = components.get("main", {}) if "main" in components else (status if "dishwasherOperatingState" in status else {})
        
        # 1. Stato switch (se presente)
        switch_val = main_comp.get("switch", {}).get("switch", {}).get("value", "")
        
        # 2. Stato operativo
        op_comp = main_comp.get("dishwasherOperatingState", {}) or main_comp.get("samsungce.dishwasherOperatingState", {})
        job_state = (
            op_comp.get("dishwasherJobState", {}).get("value")
            or main_comp.get("custom.dishwasherJobState", {}).get("dishwasherJobState", {}).get("value")
            or "none"
        )
        machine_state = (
            op_comp.get("machineState", {}).get("value")
            or main_comp.get("custom.dishwasherMachineState", {}).get("dishwasherMachineState", {}).get("value")
            or "stop"
        )
        
        job_state_str = str(job_state).lower() if job_state else "none"
        machine_state_str = str(machine_state).lower() if machine_state else "stop"

        # 3. Determinazione di is_running, is_paused, is_on
        is_running = machine_state_str in ["run", "running"] or job_state_str in ["prewash", "wash", "rinse", "dry", "cooling", "drain", "sanitize"]
        is_paused = machine_state_str in ["pause", "paused"] or job_state_str in ["pause", "paused"]
        is_on = switch_val == "on" or is_running or is_paused or machine_state_str in ["delaystart", "ready"] or job_state_str in ["ready", "delaystart"]

        if is_running and job_state_str in ["none", "ready"]:
            job_state_label = "Lavaggio in Corso 🍽️"
        elif is_paused:
            job_state_label = "In Pausa ⏸️"
        else:
            job_state_label = DISHWASHER_STATE_MAP.get(job_state, DISHWASHER_STATE_MAP.get(job_state_str, job_state.capitalize() if job_state else "In Standby / Pronto"))

        # 4. Programma / Ciclo
        cycle_raw = (
            main_comp.get("samsungce.dishwasherCycle", {}).get("dishwasherCycle", {}).get("value")
            or main_comp.get("custom.dishwasherCycle", {}).get("dishwasherCycle", {}).get("value")
            or main_comp.get("dishwasherCycle", {}).get("dishwasherCycle", {}).get("value")
        )
        cycle_name = "Auto / Eco"
        if cycle_raw:
            cycle_key = str(cycle_raw).lower()
            cycle_name = DISHWASHER_CYCLE_MAP.get(cycle_key, str(cycle_raw).capitalize())

        # 5. Tempo residuo e stima di fine
        remaining_raw = (
            op_comp.get("remainingTime", {}).get("value")
            or main_comp.get("samsungce.dishwasherDelayStart", {}).get("remainingTime", {}).get("value")
            or main_comp.get("samsungce.dishwasherCycle", {}).get("remainingTime", {}).get("value")
        )
        completion_raw = (
            op_comp.get("completionTime", {}).get("value")
            or main_comp.get("samsungce.dishwasherCycle", {}).get("completionTime", {}).get("value")
        )

        remaining_min = None
        finish_estimate = None

        if remaining_raw is not None:
            try:
                val_num = float(remaining_raw)
                # Se è espresso in secondi (> 300), converti in minuti
                if val_num > 300:
                    remaining_min = int(round(val_num / 60.0))
                else:
                    remaining_min = int(round(val_num))
            except (ValueError, TypeError):
                remaining_min = None

        # Se remaining_min non c'è ancora o è 0 ma c'è completionTime ISO timestamp
        if (remaining_min is None or remaining_min <= 0) and completion_raw:
            try:
                clean_ts = str(completion_raw).replace("Z", "+00:00")
                comp_dt = datetime.fromisoformat(clean_ts)
                if comp_dt.tzinfo is not None:
                    now_dt = datetime.now(timezone.utc)
                else:
                    now_dt = datetime.now()
                diff_sec = (comp_dt - now_dt).total_seconds()
                if diff_sec > 0:
                    remaining_min = int(round(diff_sec / 60.0))
            except Exception:
                pass

        if remaining_min and remaining_min > 0:
            finish_dt = datetime.now() + timedelta(minutes=remaining_min)
            finish_estimate = finish_dt.strftime("%H:%M")

        return {
            "device_id": dev_info.get("deviceId"),
            "name": dev_info.get("label") or dev_info.get("name") or "Lavastoviglie",
            "is_on": is_on,
            "is_running": is_running,
            "is_paused": is_paused,
            "machine_state": machine_state,
            "job_state": job_state,
            "job_state_label": job_state_label,
            "cycle_name": cycle_name,
            "remaining_min": remaining_min,
            "finish_estimate": finish_estimate
        }

    def parse_presence_data(self, status: Dict[str, Any], dev_info: Dict[str, Any]) -> Dict[str, Any]:
        """Estrae lo stato di presenza dello smartphone (S26 Ultra / S25 Ultra / Mobile)."""
        main_comp = status.get("components", {}).get("main", {})
        presence_val = main_comp.get("presenceSensor", {}).get("presence", {}).get("value", "not present")
        is_present = presence_val == "present"

        # Estrazione percentuale batteria se fornita da SmartThings
        battery_val = (
            main_comp.get("battery", {}).get("battery", {}).get("value")
            or main_comp.get("samsungce.battery", {}).get("battery", {}).get("value")
        )
        battery_pct = None
        if battery_val is not None:
            try:
                battery_pct = int(round(float(battery_val)))
            except (ValueError, TypeError):
                battery_pct = None

        raw_name = dev_info.get("label") or dev_info.get("name") or "S26 Ultra"
        clean_name = raw_name.replace("di Vincenzo", "").strip()

        return {
            "device_id": dev_info.get("deviceId"),
            "name": raw_name,
            "device_name": clean_name or "S26 Ultra",
            "is_present": is_present,
            "presence_label": "A Casa 🏠" if is_present else "Fuori Casa 🚗",
            "battery_percent": battery_pct,
            "battery_pct": battery_pct
        }

    def get_summary(
        self,
        energy_latest: Optional[Dict[str, Any]] = None,
        drying_index: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Produce un riepilogo completo e strutturato degli elettrodomestici,
        presenza e sinergia energetica/solare per la dashboard.
        """
        washer_data: Optional[Dict[str, Any]] = None
        dishwasher_data: Optional[Dict[str, Any]] = None
        presence_data: Optional[Dict[str, Any]] = None
        presence_candidates: List[Any] = []
        other_devices: List[Dict[str, Any]] = []

        for dev in self.devices:
            if not isinstance(dev, dict):
                continue
            dev_id = dev.get("deviceId")
            lbl = (dev.get("label") or dev.get("name") or "").lower()
            dev_type = (dev.get("deviceTypeName") or dev.get("type") or "").lower()
            status = self.device_statuses.get(dev_id)
            if not status or not isinstance(status, dict):
                continue

            main_comp = status.get("components", {}).get("main", {})

            if "lavatrice" in lbl or "washer" in lbl or "dryer" in lbl or "washerOperatingState" in main_comp or "dryerOperatingState" in main_comp:
                washer_data = self.parse_washer_data(status, dev)
            elif "lavastoviglie" in lbl or "dishwasher" in lbl or "dishwasherOperatingState" in main_comp or "samsungce.dishwasherCycle" in main_comp or "dishwasher" in dev_type:
                dishwasher_data = self.parse_dishwasher_data(status, dev)
            else:
                # Rilevamento presenza smartphone (S26 Ultra / S25 Ultra / Mobile)
                main_comp = status.get("components", {}).get("main", {})
                if "presenceSensor" in main_comp or dev.get("deviceTypeName") == "MOBILE" or "ultra" in lbl or "s26" in lbl or "s25" in lbl or "s24" in lbl:
                    p_parsed = self.parse_presence_data(status, dev)
                    priority = 40
                    if "s26" in lbl:
                        priority = 100
                    elif "s25" in lbl:
                        priority = 80
                    elif "s24" in lbl:
                        priority = 60
                    presence_candidates.append((priority, p_parsed))
                else:
                    other_devices.append({
                        "device_id": dev_id,
                        "name": dev.get("label") or dev.get("name"),
                        "type": dev.get("deviceTypeName") or dev.get("type")
                    })

        if presence_candidates:
            presence_candidates.sort(key=lambda x: x[0], reverse=True)
            presence_data = presence_candidates[0][1]


        # Calcolo Sinergia Solare Aton per Elettrodomestici
        p_solare = 0.0
        soc = 0.0
        p_batteria = 0.0
        if energy_latest:
            p_solare = float(energy_latest.get("p_solare") or 0.0)
            soc = float(energy_latest.get("soc") or 0.0)
            p_batteria = float(energy_latest.get("p_batteria") or 0.0)

        # Valutazione momento ottimale per avvio lavaggi
        # Elettrodomestici tipici assorbono ~1.5 - 2.2 kW durante il riscaldamento acqua
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
            dry_status = drying_index.get("status", "neutral")
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
            "laundry_drying_synergy": laundry_drying_synergy
        }

    async def execute_command(self, device_id: str, capability: str, command: str, args: Optional[List[Any]] = None) -> bool:
        """Invia un comando REST a un dispositivo SmartThings."""
        if not self.enabled:
            return False

        session = await self.get_session()
        payload = {
            "commands": [
                {
                    "component": "main",
                    "capability": capability,
                    "command": command,
                    "arguments": args or []
                }
            ]
        }

        try:
            url = f"{SMARTTHINGS_API_BASE}/devices/{device_id}/commands"
            async with session.post(url, json=payload) as resp:
                if resp.status in [200, 202]:
                    logger.info(f"Comando SmartThings {capability}.{command} inviato con successo a {device_id}")
                    await asyncio.sleep(1.0)
                    await self.fetch_device_status(device_id)
                    return True
                else:
                    err_txt = await resp.text()
                    logger.error(f"Errore invio comando a {device_id}: HTTP {resp.status} - {err_txt}")
                    return False
        except Exception as e:
            logger.error(f"Eccezione invio comando SmartThings a {device_id}: {e}")
            return False

    async def worker_loop(self):
        """Loop di polling in background per sincronizzare costantemente gli elettrodomestici."""
        if not self.enabled:
            logger.info("ℹ️ [SmartThings] Servizio non abilitato o PAT assente.")
            return

        logger.info(f"🚀 [SmartThings] Background worker avviato (Intervallo: {self.poll_interval}s)")
        while True:
            try:
                if self.enabled:
                    await self.sync_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Errore nel ciclo di polling SmartThings: {e}")
            
            # Se errore 401 (PAT non valido o scaduto), attendi 5 minuti prima del prossimo tentativo per non intasare i log
            sleep_time = 300 if (self.sync_error and "401" in self.sync_error) else self.poll_interval
            await asyncio.sleep(sleep_time)


# Istanza singleton globale
smartthings_service = SmartThingsService()
