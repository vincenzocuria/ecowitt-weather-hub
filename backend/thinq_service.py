import asyncio
import logging
import os
import json
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List
import aiohttp

from backend.config import settings

logger = logging.getLogger("weather_hub.thinq")

class LGThinQService:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.api = None
        self.client_id = str(uuid.uuid4())
        self.is_connected: bool = False
        self.last_fetch_time: Optional[datetime] = None
        self.devices_cache: Dict[str, Dict[str, Any]] = {}
        self.device_profiles: Dict[str, Dict[str, Any]] = {}
        self.device_instances: Dict[str, Any] = {}
        self._running: bool = False
        self.sync_error: Optional[str] = None
        self.rate_limited: bool = False
        self.cache_file = os.path.join(settings.DATA_DIR, "thinq_cache.json")
        self._load_cache()

    def _load_cache(self):
        """Carica lo stato dei dispositivi persistito su disco per sopravvivere ai riavvii o ai limiti API."""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.devices_cache = data.get("devices_cache", {})
                    self.device_profiles = data.get("device_profiles", {})
                    if self.devices_cache:
                        logger.info(f"📂 [LG ThinQ] Caricati {len(self.devices_cache)} dispositivi dalla cache locale persistente.")
        except Exception as e:
            logger.warning(f"⚠️ [LG ThinQ] Impossibile caricare la cache da disco: {e}")

    def _save_cache(self):
        """Salva lo stato dei dispositivi su file JSON in modo atomico."""
        try:
            os.makedirs(settings.DATA_DIR, exist_ok=True)
            tmp_path = f"{self.cache_file}.tmp"
            payload = {
                "saved_at": settings.now_local().strftime("%Y-%m-%d %H:%M:%S"),
                "devices_cache": self.devices_cache,
                "device_profiles": self.device_profiles
            }
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.cache_file)
        except Exception as e:
            logger.warning(f"⚠️ [LG ThinQ] Impossibile salvare la cache su disco: {e}")

    async def _ensure_session(self) -> bool:
        """Crea o rinnova la sessione aiohttp e l'istanza ThinQApi."""
        if not settings.LG_THINQ_ENABLED or not settings.LG_THINQ_PAT:
            return False

        try:
            if self.session is None or self.session.closed:
                # Usa ThreadedResolver per compatibilità multipiattaforma e Windows DNS
                connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver(), ssl=True)
                self.session = aiohttp.ClientSession(connector=connector)

            if self.api is None:
                from thinqconnect.thinq_api import ThinQApi
                self.api = ThinQApi(
                    session=self.session,
                    access_token=settings.LG_THINQ_PAT,
                    country_code=settings.LG_THINQ_COUNTRY,
                    client_id=self.client_id
                )
                await self.api.async_init()
                logger.info(f"✅ [LG ThinQ] Inizializzata connessione API (Country: {settings.LG_THINQ_COUNTRY})")
            
            return True
        except Exception as e:
            err_str = str(e)
            logger.error(f"❌ [LG ThinQ] Errore inizializzazione API: {err_str}")
            self.is_connected = False
            self.sync_error = err_str
            if "1314" in err_str or "Exceeded User API calls" in err_str:
                self.rate_limited = True
            return False

    async def fetch_all_devices(self) -> List[Dict[str, Any]]:
        """Recupera la lista dei dispositivi e aggiorna lo stato in cache."""
        if not settings.LG_THINQ_ENABLED or not settings.LG_THINQ_PAT:
            return list(self.devices_cache.values())

        if not await self._ensure_session():
            return list(self.devices_cache.values())

        try:
            raw_devices = await self.api.async_get_device_list()
            devices_list = []
            if isinstance(raw_devices, dict):
                devices_list = raw_devices.get("item", [])
            elif isinstance(raw_devices, list):
                devices_list = raw_devices

            now_str = settings.now_local().strftime("%Y-%m-%d %H:%M:%S")

            for dev in devices_list:
                device_id = dev.get("deviceId")
                info = dev.get("deviceInfo", {})
                device_type = info.get("deviceType", "UNKNOWN")
                alias = info.get("alias", "LG Device")
                model_name = info.get("modelName", "")

                # Se non abbiamo ancora il profilo, scaricalo
                if device_id not in self.device_profiles:
                    try:
                        profile = await self.api.async_get_device_profile(device_id)
                        self.device_profiles[device_id] = profile
                    except Exception as e_prof:
                        logger.warning(f"⚠️ [LG ThinQ] Impossibile recuperare profilo per {alias}: {e_prof}")

                # Recupera lo stato attuale
                status_raw = {}
                try:
                    status_raw = await self.api.async_get_device_status(device_id)
                except Exception as e_stat:
                    logger.debug(f"⚠️ [LG ThinQ] Errore lettura stato per {alias}: {e_stat}")

                # Se è un condizionatore, normalizza la scheda tecnica
                if device_type == "DEVICE_AIR_CONDITIONER":
                    op_mode = status_raw.get("operation", {}).get("airConOperationMode", "POWER_OFF")
                    is_on = (op_mode == "POWER_ON")
                    job_mode = status_raw.get("airConJobMode", {}).get("currentJobMode", "COOL")
                    
                    temp_info = status_raw.get("temperature", {})
                    current_temp = temp_info.get("currentTemperature")
                    target_temp = temp_info.get("targetTemperature")
                    unit = temp_info.get("unit", "C")
                    
                    airflow = status_raw.get("airFlow", {})
                    wind_strength = airflow.get("windStrengthDetail") or airflow.get("windStrength", "LOW")
                    
                    wind_dir = status_raw.get("windDirection", {})
                    rotate_up_down = wind_dir.get("rotateUpDown", False)
                    rotate_left_right = wind_dir.get("rotateLeftRight", False)
                    
                    power_save = status_raw.get("powerSave", {}).get("powerSaveEnabled", False)

                    self.devices_cache[device_id] = {
                        "device_id": device_id,
                        "deviceId": device_id,
                        "alias": alias,
                        "model_name": model_name,
                        "device_type": device_type,
                        "is_online": True if status_raw else False,
                        "power": op_mode,
                        "is_on": is_on,
                        "current_temp": current_temp,
                        "target_temp": target_temp,
                        "unit": unit,
                        "mode": job_mode,
                        "fan_speed": wind_strength,
                        "rotate_up_down": rotate_up_down,
                        "rotate_left_right": rotate_left_right,
                        "power_save": power_save,
                        "min_temp": 18.0,
                        "max_temp": 30.0,
                        "step_temp": 0.5,
                        "available_modes": ["COOL", "HEAT", "DRY", "FAN", "AUTO"],
                        "available_fan_speeds": ["LOW", "MID", "HIGH", "AUTO"],
                        "last_updated": now_str,
                        "raw_status": status_raw
                    }
                else:
                    # Altri dispositivi (es. lavatrice, frigo)
                    self.devices_cache[device_id] = {
                        "device_id": device_id,
                        "deviceId": device_id,
                        "alias": alias,
                        "model_name": model_name,
                        "device_type": device_type,
                        "is_online": True if status_raw else False,
                        "last_updated": now_str,
                        "raw_status": status_raw
                    }

            self.is_connected = True
            self.sync_error = None
            self.rate_limited = False
            self.last_fetch_time = settings.now_local()
            self._save_cache()
            return list(self.devices_cache.values())

        except Exception as e:
            err_str = str(e)
            logger.error(f"❌ [LG ThinQ] Errore durante fetch_all_devices: {err_str}")
            self.is_connected = False
            self.sync_error = err_str
            if "1314" in err_str or "Exceeded User API calls" in err_str:
                self.rate_limited = True
                logger.warning("⚠️ [LG ThinQ] Quota chiamate API giornaliere superata (1314). Uso cache persistente.")
            return list(self.devices_cache.values())

    async def control_device(self, device_id: str, command: Dict[str, Any]) -> Dict[str, Any]:
        """Invia uno o più comandi al climatizzatore."""
        if not await self._ensure_session():
            return {"status": "error", "message": "ThinQ non configurato o non connesso"}

        cached_dev = self.devices_cache.get(device_id)
        if not cached_dev:
            await self.fetch_all_devices()
            cached_dev = self.devices_cache.get(device_id)

        if not cached_dev:
            return {"status": "error", "message": f"Dispositivo {device_id} non trovato"}

        results = []
        try:
            # 1. Accensione / Spegnimento (Power)
            if "power" in command:
                p_val = "POWER_ON" if command["power"] in (True, "POWER_ON", "on", "1") else "POWER_OFF"
                payload = {"operation": {"airConOperationMode": p_val}}
                res = await self.api.async_post_device_control(device_id=device_id, payload=payload)
                results.append({"power": p_val, "result": res})
                if cached_dev:
                    cached_dev["power"] = p_val
                    cached_dev["is_on"] = (p_val == "POWER_ON")

            # 2. Modalità (Job Mode: COOL, HEAT, DRY, FAN, AUTO)
            if "mode" in command:
                m_val = str(command["mode"]).upper()
                payload = {"airConJobMode": {"currentJobMode": m_val}}
                res = await self.api.async_post_device_control(device_id=device_id, payload=payload)
                results.append({"mode": m_val, "result": res})
                if cached_dev:
                    cached_dev["mode"] = m_val

            # 3. Temperatura target
            if "target_temp" in command or "temperature" in command:
                t_val = float(command.get("target_temp", command.get("temperature")))
                # In base alla modalità
                mode = cached_dev.get("mode", "COOL") if cached_dev else "COOL"
                field_name = "coolTargetTemperature"
                if mode == "HEAT":
                    field_name = "heatTargetTemperature"
                elif mode == "AUTO":
                    field_name = "autoTargetTemperature"
                
                payload = {"temperatureInUnits": {field_name: t_val}}
                res = await self.api.async_post_device_control(device_id=device_id, payload=payload)
                results.append({"target_temp": t_val, "result": res})
                if cached_dev:
                    cached_dev["target_temp"] = t_val

            # 4. Velocità Ventilazione (windStrength)
            if "fan_speed" in command or "wind_strength" in command:
                speed = str(command.get("fan_speed", command.get("wind_strength"))).upper()
                payload = {"airFlow": {"windStrengthDetail": speed}}
                res = await self.api.async_post_device_control(device_id=device_id, payload=payload)
                results.append({"fan_speed": speed, "result": res})
                if cached_dev:
                    cached_dev["fan_speed"] = speed

            # 5. Swing / Oscillazione verticale (rotateUpDown)
            if "rotate_up_down" in command:
                swing = bool(command["rotate_up_down"])
                payload = {"windDirection": {"rotateUpDown": swing}}
                res = await self.api.async_post_device_control(device_id=device_id, payload=payload)
                results.append({"rotate_up_down": swing, "result": res})
                if cached_dev:
                    cached_dev["rotate_up_down"] = swing

            # 6. Eco / Power Save
            if "power_save" in command:
                ps = bool(command["power_save"])
                payload = {"powerSave": {"powerSaveEnabled": ps}}
                res = await self.api.async_post_device_control(device_id=device_id, payload=payload)
                results.append({"power_save": ps, "result": res})
                if cached_dev:
                    cached_dev["power_save"] = ps

            # Aggiorna timestamp
            if cached_dev:
                cached_dev["last_updated"] = settings.now_local().strftime("%Y-%m-%d %H:%M:%S")

            return {"status": "success", "device_id": device_id, "actions": results}

        except Exception as e:
            logger.error(f"❌ [LG ThinQ] Errore controllo dispositivo {device_id}: {e}")
            return {"status": "error", "message": str(e)}

    def get_cached_devices(self) -> List[Dict[str, Any]]:
        """Restituisce lo stato cached di tutti i dispositivi."""
        return list(self.devices_cache.values())

    def get_cached_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Restituisce lo stato cached di un singolo dispositivo."""
        return self.devices_cache.get(device_id)

    async def worker_loop(self):
        """Loop di polling periodico per sincronizzare lo stato dei climatizzatori."""
        if not settings.LG_THINQ_ENABLED or not settings.LG_THINQ_PAT:
            logger.info("ℹ️ [LG ThinQ] Servizio non abilitato o PAT assente in configurazione.")
            return

        self._running = True
        logger.info(f"🚀 [LG ThinQ] Background worker avviato (Intervallo: {settings.LG_THINQ_POLL_INTERVAL_SEC}s)")

        # Primo fetch immediato
        await self.fetch_all_devices()

        while self._running:
            try:
                # Se siamo in rate limit (1314), attendi 10 minuti prima di riprovare
                sleep_sec = 600 if self.rate_limited else settings.LG_THINQ_POLL_INTERVAL_SEC
                await asyncio.sleep(sleep_sec)
                await self.fetch_all_devices()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"⚠️ [LG ThinQ] Errore nel worker loop: {e}")
                await asyncio.sleep(30)

    def stop(self):
        self._running = False
        if self.session and not self.session.closed:
            asyncio.create_task(self.session.close())

thinq_service = LGThinQService()
