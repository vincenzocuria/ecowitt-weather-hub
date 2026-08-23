"""
Modulo di integrazione per Tuya / Smart Life Cloud API (tramite TinyTuya).
Gestisce la sincronizzazione dello stato in tempo reale di prese smart (con monitoraggio consumi W/V/A),
termostati, elettrovalvole irrigazione, luci e tapparelle, integrandosi con le impostazioni di abilitazione
personalizzate dall'utente nel database SQLite.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import tinytuya

from backend.config import settings
from backend.database import get_tuya_device_configs, save_tuya_device_config

logger = logging.getLogger("TuyaService")

# Mappa icone e categorie per UI
CATEGORY_METADATA = {
    "cz": {"type": "plug", "icon": "🔌", "label": "Presa Smart con Misuratore"},
    "pc": {"type": "plug", "icon": "🔌", "label": "Presa / Ciabatta Smart"},
    "wk": {"type": "thermostat", "icon": "🌡️", "label": "Cronotermostato Smart"},
    "sfkzq": {"type": "irrigation", "icon": "💧", "label": "Elettrovalvola Irrigazione"},
    "cl": {"type": "curtain", "icon": "🪟", "label": "Interruttore Persiana/Tenda"},
    "clkg": {"type": "curtain", "icon": "🪟", "label": "Interruttore Persiana/Tapparella"},
    "bl": {"type": "curtain", "icon": "🪟", "label": "Persiana/Tapparella Motorizzata"},
    "cs": {"type": "curtain", "icon": "🪟", "label": "Comando Persiana/Tenda"},
    "jd": {"type": "switch", "icon": "🔘", "label": "Modulo Relè / Interruttore"},
    "kg": {"type": "switch", "icon": "🔘", "label": "Interruttore Smart"},
    "dj": {"type": "light", "icon": "💡", "label": "Lampadina Smart Wi-Fi"},
    "dd": {"type": "light", "icon": "💡", "label": "Luce / Striscia LED Smart"},
    "mc": {"type": "contact", "icon": "🚪", "label": "Sensore Porta / Finestra"},
    "tzc1": {"type": "scale", "icon": "⚖️", "label": "Bilancia Smart"},
}


import os
import json

class TuyaService:
    def __init__(self):
        self.client_id = settings.TUYA_CLIENT_ID
        self.secret = settings.TUYA_SECRET
        self.region = settings.TUYA_REGION
        self.enabled = settings.TUYA_ENABLED and bool(self.client_id) and bool(self.secret)
        self.poll_interval = settings.TUYA_POLL_INTERVAL_SEC

        self.cloud: Optional[tinytuya.Cloud] = None
        self.raw_devices: List[Dict[str, Any]] = []
        self.device_statuses: Dict[str, Dict[str, Any]] = {}
        self.last_sync_time: Optional[float] = None
        self.sync_error: Optional[str] = None
        self.is_connected = False
        self._lock = asyncio.Lock()
        self.cache_file = os.path.join(settings.DATA_DIR, "tuya_cache.json")
        self._load_cache()

        if self.enabled:
            self._init_cloud()

    def _load_cache(self):
        """Carica lo stato dei dispositivi Tuya persistito su disco per evitare che spariscano al riavvio."""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.raw_devices = data.get("raw_devices", [])
                    self.device_statuses = data.get("device_statuses", {})
                    self.last_sync_time = data.get("last_sync_time")
                    if self.device_statuses:
                        self.is_connected = True
                        logger.info("📂 [Tuya] Caricati %d dispositivi dalla cache locale persistente.", len(self.device_statuses))
        except Exception as e:
            logger.warning("⚠️ [Tuya] Impossibile caricare la cache da disco: %s", e)

    def _save_cache(self):
        """Salva lo stato dei dispositivi su file JSON in modo atomico."""
        try:
            os.makedirs(settings.DATA_DIR, exist_ok=True)
            tmp_path = f"{self.cache_file}.tmp"
            payload = {
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "raw_devices": self.raw_devices,
                "device_statuses": self.device_statuses,
                "last_sync_time": self.last_sync_time
            }
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.cache_file)
        except Exception as e:
            logger.warning("⚠️ [Tuya] Impossibile salvare la cache su disco: %s", e)

    def _init_cloud(self):
        try:
            self.cloud = tinytuya.Cloud(
                apiRegion=self.region,
                apiKey=self.client_id,
                apiSecret=self.secret
            )
            self.is_connected = True
            logger.info("Tuya Cloud client inizializzato per regione %s", self.region)
        except Exception as e:
            logger.error("Errore inizializzazione Tuya Cloud: %s", e)
            self.cloud = None
            self.is_connected = False

    def _format_device_status(self, dev_info: Dict[str, Any], raw_status_list: List[Dict[str, Any]], user_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Estrae e normalizza i campi di stato specifici per il tipo di dispositivo."""
        d_id = dev_info.get("id")
        category = dev_info.get("category", "")
        meta = CATEGORY_METADATA.get(category, {"type": "generic", "icon": "📱", "label": "Dispositivo Smart"})

        status_dict = {item.get("code"): item.get("value") for item in raw_status_list if "code" in item}

        # Parsing valori specifici per categoria
        is_on = None
        power_w = 0.0
        voltage_v = 0.0
        current_a = 0.0
        temp_current = None
        temp_set = None
        battery_pct = None
        work_state = None
        weather_delay = None
        curtain_state = None

        # Prese e interruttori
        if "switch_1" in status_dict:
            is_on = bool(status_dict["switch_1"])
        elif "switch" in status_dict:
            is_on = bool(status_dict["switch"])
        elif "switch_led" in status_dict:
            is_on = bool(status_dict["switch_led"])

        # Misuratore energia (prese 'cz')
        if "cur_power" in status_dict:
            # Tuya restituisce spesso potenza in dW (decimi di Watt)
            raw_p = status_dict["cur_power"]
            power_w = round(float(raw_p) / 10.0, 1) if raw_p is not None else 0.0
        if "cur_voltage" in status_dict:
            # Tensione in dV (es. 2287 = 228.7 V)
            raw_v = status_dict["cur_voltage"]
            voltage_v = round(float(raw_v) / 10.0, 1) if raw_v is not None else 0.0
        if "cur_current" in status_dict:
            # Corrente in mA (es. 1000 = 1.0 A)
            raw_i = status_dict["cur_current"]
            current_a = round(float(raw_i) / 1000.0, 2) if raw_i is not None else 0.0

        # Termostato ('wk')
        if category == "wk":
            if "upper_temp" in status_dict:
                # Spesso upper_temp o temp_current è la temperatura ambiente
                temp_current = float(status_dict["upper_temp"])
            if "temp_set" in status_dict:
                temp_set = float(status_dict["temp_set"])

        # Irrigazione ('sfkzq')
        if category == "sfkzq" or meta.get("type") == "irrigation":
            if "battery_percentage" in status_dict:
                battery_pct = int(status_dict["battery_percentage"])
            work_state = status_dict.get("work_state", "idle")
            weather_delay = status_dict.get("weather_delay", "cancel")
            if is_on is None:
                if "switch" in status_dict:
                    is_on = bool(status_dict["switch"])
                elif "switch_1" in status_dict:
                    is_on = bool(status_dict["switch_1"])
                elif "switch_spray" in status_dict:
                    is_on = bool(status_dict["switch_spray"])
                elif work_state and str(work_state).lower() in ("watering", "spray", "manual", "auto", "running", "working"):
                    is_on = True
                elif work_state and str(work_state).lower() in ("idle", "closed", "off", "standby"):
                    is_on = False

        # Persiana / Tenda / Tapparella
        cat_lower = category.lower()
        name_lower = (dev_info.get("name") or "").lower()
        if cat_lower in ("cl", "clkg", "bl", "cs") or any(kw in name_lower for kw in ("persian", "tapparel", "tenda", "curtain", "shutter", "blind", "avvolgibil")):
            meta = {"type": "curtain", "icon": "🪟", "label": "Persiana / Tenda Smart"}
            curtain_state = (
                status_dict.get("control")
                or status_dict.get("percent_control")
                or status_dict.get("mach_oper")
                or status_dict.get("percent_state")
                or ("Aperta" if is_on is True else ("Chiusa" if is_on is False else None))
            )

        # Nome visualizzato (alias utente se presente, altrimenti nome originale)
        custom_name = user_cfg.get("custom_name") if user_cfg else None
        name = custom_name if custom_name else dev_info.get("name", "Dispositivo Tuya")
        is_enabled = user_cfg.get("enabled", True) if user_cfg else True

        return {
            "id": d_id,
            "original_name": dev_info.get("name", ""),
            "name": name,
            "category": category,
            "type": meta["type"],
            "type_label": meta["label"],
            "icon": meta["icon"],
            "product_name": dev_info.get("product_name", ""),
            "model": dev_info.get("model", ""),
            "enabled": is_enabled,
            "is_on": is_on,
            "power_w": power_w,
            "voltage_v": voltage_v,
            "current_a": current_a,
            "temp_current": temp_current,
            "temp_set": temp_set,
            "battery_pct": battery_pct,
            "work_state": work_state,
            "weather_delay": weather_delay,
            "curtain_state": curtain_state,
            "raw_status": status_dict,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }

    async def fetch_devices_list(self) -> List[Dict[str, Any]]:
        """Recupera l'elenco di tutti i dispositivi associati all'account Tuya."""
        if not self.enabled or not self.cloud:
            return self.raw_devices
        
        loop = asyncio.get_running_loop()
        try:
            res = await loop.run_in_executor(None, self.cloud.getdevices)
            if isinstance(res, list):
                self.raw_devices = res
                self.is_connected = True
                self._save_cache()
                return res
            elif isinstance(res, dict) and "result" in res and isinstance(res["result"], list):
                self.raw_devices = res["result"]
                self.is_connected = True
                self._save_cache()
                return res["result"]
            else:
                logger.warning("Risposta imprevista getdevices da Tuya: %s", res)
                return self.raw_devices
        except Exception as e:
            logger.error("Errore chiamata getdevices Tuya: %s", e)
            self.sync_error = str(e)
            return self.raw_devices

    async def sync_all(self) -> Dict[str, Any]:
        """Sincronizza lo stato in tempo reale di tutti i dispositivi in parallelo."""
        if not self.enabled:
            return self.get_summary()

        async with self._lock:
            if not self.cloud:
                self._init_cloud()
                if not self.cloud:
                    return self.get_summary()

            loop = asyncio.get_running_loop()
            
            # Se la lista dispositivi è vuota, recuperala
            if not self.raw_devices:
                await self.fetch_devices_list()

            if not self.raw_devices:
                return self.get_summary()

            configs = get_tuya_device_configs()

            # Esecuzione parallela asincrona per tutte le chiamate di stato
            async def _fetch_status_for_dev(dev):
                d_id = dev.get("id")
                if not d_id:
                    return None, None
                user_cfg = configs.get(d_id)
                try:
                    status_res = await loop.run_in_executor(None, self.cloud.getstatus, d_id)
                    raw_list = status_res.get("result", []) if isinstance(status_res, dict) else []
                    parsed = self._format_device_status(dev, raw_list, user_cfg)
                    return d_id, parsed
                except Exception as e:
                    logger.warning("Impossibile leggere stato dispositivo Tuya %s (%s): %s", dev.get("name"), d_id, e)
                    if d_id in self.device_statuses:
                        return d_id, self.device_statuses[d_id]
                    return d_id, None

            tasks = [_fetch_status_for_dev(d) for d in self.raw_devices if d.get("id")]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for item in results:
                if isinstance(item, tuple) and item[0] and item[1]:
                    self.device_statuses[item[0]] = item[1]

            self.last_sync_time = time.time()
            self.sync_error = None
            self._save_cache()
            return self.get_summary()

    def get_summary(self) -> Dict[str, Any]:
        """Restituisce un riassunto strutturato di tutti i dispositivi Tuya attivi ed abilitati."""
        all_devs = list(self.device_statuses.values())
        enabled_devs = [d for d in all_devs if d.get("enabled", True)]
        
        # Calcolo potenza totale delle prese smart attive ed abilitate
        total_plug_power_w = sum(
            d.get("power_w", 0.0)
            for d in enabled_devs
            if d.get("category") == "cz" and d.get("is_on")
        )

        # Raggruppamento per tipologia per facilitare la UI
        plugs = [d for d in enabled_devs if d.get("category") in ("cz", "pc") or (d.get("type") == "plug" and d.get("category") not in ("dj", "dd"))]
        climates = [d for d in enabled_devs if d.get("category") == "wk" or d.get("type") == "thermostat"]
        irrigations = [d for d in enabled_devs if d.get("category") == "sfkzq" or d.get("type") == "irrigation"]
        lights = [d for d in enabled_devs if d.get("category") in ("dj", "dd") or d.get("type") == "light"]
        curtains = [
            d for d in enabled_devs 
            if d.get("category") in ("cl", "clkg", "bl", "cs") 
            or d.get("type") == "curtain"
            or any(kw in (d.get("name") or "").lower() for kw in ("persian", "tapparel", "tenda", "curtain", "shutter", "blind", "avvolgibil"))
        ]
        others = [d for d in enabled_devs if d not in plugs and d not in climates and d not in irrigations and d not in lights and d not in curtains]

        return {
            "enabled": self.enabled,
            "is_connected": self.is_connected,
            "last_sync_time": self.last_sync_time,
            "sync_error": self.sync_error,
            "total_plug_power_w": round(total_plug_power_w, 1),
            "total_devices_count": len(all_devs),
            "enabled_devices_count": len(enabled_devs),
            "devices": enabled_devs,
            "enabled_devices": enabled_devs,
            "all_devices": all_devs,
            "plugs": plugs,
            "climates": climates,
            "irrigations": irrigations,
            "lights": lights,
            "curtains": curtains,
            "others": others
        }

    async def send_command(self, device_id: str, commands: Any) -> Dict[str, Any]:
        """Invia un comando Tuya (es. switch, temperatura, persiana, ecc.)."""
        if not self.enabled or not self.cloud:
            return {"success": False, "error": "Servizio Tuya non configurato"}

        loop = asyncio.get_running_loop()
        try:
            if isinstance(commands, list):
                payload = {"commands": commands}
            elif isinstance(commands, dict) and "commands" in commands:
                payload = commands
            else:
                payload = {"commands": [commands]}

            res = await loop.run_in_executor(None, self.cloud.sendcommand, device_id, payload)
            logger.info("Comando Tuya inviato a %s: %s -> %s", device_id, payload, res)
            
            # Valida risposta effettiva di Tuya Cloud
            is_ok = False
            err_msg = None
            if isinstance(res, dict):
                if res.get("success") is True or res.get("result") is True:
                    is_ok = True
                elif "Error" in res:
                    err_msg = str(res.get("Error"))
                elif "msg" in res:
                    err_msg = str(res.get("msg"))
                elif res.get("code") and res.get("code") != 0:
                    err_msg = f"Tuya error {res.get('code')}: {res.get('msg', '')}"
            elif res is True:
                is_ok = True

            if is_ok:
                # Schedula un refresh immediato dello stato del dispositivo
                asyncio.create_task(self.sync_single_device(device_id))
                return {"success": True, "result": res}
            else:
                logger.warning("Tuya Cloud ha rifiutato il comando per %s: %s", device_id, res)
                return {"success": False, "error": err_msg or "Comando rifiutato dal dispositivo Tuya", "result": res}
        except Exception as e:
            logger.error("Errore invio comando Tuya a %s: %s", device_id, e)
            return {"success": False, "error": str(e)}

    async def control_curtain(self, device_id: str, action: str) -> Dict[str, Any]:
        """Invia il comando di apertura, stop o chiusura a una persiana/tenda."""
        action_norm = (action or "stop").lower().strip()
        cmd_value = action_norm
        if action_norm in ("open", "apri", "up", "su"):
            cmd_value = "open"
        elif action_norm in ("close", "chiudi", "down", "giu"):
            cmd_value = "close"
        elif action_norm in ("stop", "pause", "pausa", "ferma"):
            cmd_value = "stop"

        # 1. Prova con codice 'control' (standard Tuya Curtain Switch)
        commands = [{"code": "control", "value": cmd_value}]
        res = await self.send_command(device_id, commands)
        
        # 2. Fallback a 'mach_oper' (utilizzato da alcuni motori persiana)
        if not res.get("success") or (isinstance(res.get("result"), dict) and not res["result"].get("success")):
            alt_val = "FZ" if cmd_value == "open" else ("ZZ" if cmd_value == "close" else "STOP")
            res2 = await self.send_command(device_id, [{"code": "mach_oper", "value": alt_val}])
            if res2.get("success"):
                res = res2

        # 3. Fallback a 'percent_control' (0 per chiudi, 100 per apri)
        if not res.get("success") or (isinstance(res.get("result"), dict) and not res["result"].get("success")):
            if cmd_value in ("open", "close"):
                pct = 100 if cmd_value == "open" else 0
                res3 = await self.send_command(device_id, [{"code": "percent_control", "value": pct}])
                if res3.get("success"):
                    res = res3

        return res

    async def toggle_device(self, device_id: str, target_state: Optional[bool] = None) -> Dict[str, Any]:
        """Inverte o imposta lo stato ON/OFF del dispositivo con rilevamento dinamico del codice switch e fallback."""
        dev = self.device_statuses.get(device_id)
        if not dev:
            # Prova a sincronizzare prima
            await self.sync_all()
            dev = self.device_statuses.get(device_id)

        current_state = dev.get("is_on", False) if dev else False
        new_state = (not current_state) if target_state is None else target_state

        raw_status = dev.get("raw_status", {}) if dev else {}
        
        candidates: List[str] = []
        for candidate in ["switch_1", "switch", "switch_led", "switch_2", "switch_spray"]:
            if candidate in raw_status and candidate not in candidates:
                candidates.append(candidate)
        
        category = dev.get("category", "") if dev else ""
        if category == "cz" and "switch_1" not in candidates:
            candidates.insert(0, "switch_1")
        elif category in ("dj", "dd") and "switch_led" not in candidates:
            candidates.insert(0, "switch_led")
        elif category == "sfkzq" and "switch_spray" not in candidates:
            candidates.insert(0, "switch_spray")
            
        for fallback in ["switch_1", "switch", "switch_led", "switch_2", "switch_spray"]:
            if fallback not in candidates:
                candidates.append(fallback)

        last_res = {"success": False, "error": "Nessun codice switch accettato da Tuya"}
        for cmd_code in candidates:
            commands = [{"code": cmd_code, "value": new_state}]
            res = await self.send_command(device_id, commands)
            if res.get("success"):
                if dev:
                    dev["is_on"] = new_state
                    if "raw_status" not in dev:
                        dev["raw_status"] = {}
                    dev["raw_status"][cmd_code] = new_state
                    self._save_cache()
                return res
            last_res = res
            
        return last_res

    async def set_thermostat_temp(self, device_id: str, temp_c: float) -> Dict[str, Any]:
        """Imposta il target di temperatura per un termostato Tuya."""
        commands = [{"code": "temp_set", "value": int(temp_c)}]
        return await self.send_command(device_id, commands)

    async def open_irrigation(self, device_id: str, duration_minutes: int = 15) -> Dict[str, Any]:
        """Apre l'elettrovalvola per l'irrigazione inviando i comandi switch / countdown."""
        dev = self.device_statuses.get(device_id)
        raw_status = dev.get("raw_status", {}) if dev else {}

        # 1. Trova codice switch compatibile
        switch_code = "switch_1" if "switch_1" in raw_status else ("switch" if "switch" in raw_status else "switch_spray")
        commands = [{"code": switch_code, "value": True}]

        # 2. Se supportato countdown nativo Tuya (in secondi o minuti)
        if "countdown_1" in raw_status:
            commands.append({"code": "countdown_1", "value": int(duration_minutes * 60)})
        elif "countdown" in raw_status:
            commands.append({"code": "countdown", "value": int(duration_minutes * 60)})

        res = await self.send_command(device_id, commands)
        if not res.get("success"):
            # Fallback con solo switch
            res = await self.send_command(device_id, [{"code": "switch_1", "value": True}])
            if not res.get("success"):
                res = await self.send_command(device_id, [{"code": "switch", "value": True}])

        if dev and res.get("success"):
            dev["is_on"] = True
            dev["work_state"] = "watering"
            self._save_cache()

        return res

    async def close_irrigation(self, device_id: str) -> Dict[str, Any]:
        """Chiude immediatamente l'elettrovalvola per l'irrigazione."""
        dev = self.device_statuses.get(device_id)
        raw_status = dev.get("raw_status", {}) if dev else {}

        switch_code = "switch_1" if "switch_1" in raw_status else ("switch" if "switch" in raw_status else "switch_spray")
        commands = [{"code": switch_code, "value": False}]

        res = await self.send_command(device_id, commands)
        if not res.get("success"):
            res = await self.send_command(device_id, [{"code": "switch_1", "value": False}])
            if not res.get("success"):
                res = await self.send_command(device_id, [{"code": "switch", "value": False}])

        if dev and res.get("success"):
            dev["is_on"] = False
            dev["work_state"] = "idle"
            self._save_cache()

        return res

    async def set_irrigation_weather_delay(self, device_id: str, delay_str: str = "24h") -> Dict[str, Any]:
        """Imposta il ritardo meteo hardware (24h, 48h, 72h, cancel) per la valvola."""
        commands = [{"code": "weather_delay", "value": delay_str}]
        res = await self.send_command(device_id, commands)
        return res

    async def sync_single_device(self, device_id: str) -> None:
        """Aggiorna lo stato di un singolo dispositivo."""
        if not self.cloud:
            return
        loop = asyncio.get_running_loop()
        try:
            # Attendi 1s per permettere al cloud di applicare il comando
            await asyncio.sleep(1.0)
            status_res = await loop.run_in_executor(None, self.cloud.getstatus, device_id)
            raw_list = status_res.get("result", []) if isinstance(status_res, dict) else []
            
            dev_info = next((d for d in self.raw_devices if d.get("id") == device_id), None)
            if dev_info:
                configs = get_tuya_device_configs()
                user_cfg = configs.get(device_id)
                self.device_statuses[device_id] = self._format_device_status(dev_info, raw_list, user_cfg)
                self._save_cache()
        except Exception as e:
            logger.warning("Errore refresh singolo dispositivo Tuya %s: %s", device_id, e)

    async def set_device_enabled(self, device_id: str, enabled: bool, custom_name: Optional[str] = None) -> bool:
        """Salva nel database se il dispositivo deve essere mostrato/tracciato nella dashboard."""
        dev = self.device_statuses.get(device_id)
        category = dev.get("category") if dev else None
        icon = dev.get("icon") if dev else None
        save_tuya_device_config(device_id, enabled, custom_name, category, icon)
        
        # Aggiorna in memoria e cache
        if device_id in self.device_statuses:
            self.device_statuses[device_id]["enabled"] = enabled
            if custom_name is not None:
                self.device_statuses[device_id]["name"] = custom_name
            self._save_cache()
        return True

    async def worker_loop(self):
        """Loop di polling periodico asincrono in background."""
        if not self.enabled:
            logger.info("Tuya Service disattivato da configurazione.")
            return

        logger.info("Avvio worker loop Tuya / Smart Life (intervallo %ss)...", self.poll_interval)
        # Primo sync immediato
        try:
            await self.sync_all()
        except Exception as e:
            logger.error("Errore primo sync Tuya: %s", e)

        while True:
            try:
                await asyncio.sleep(self.poll_interval)
                await self.sync_all()
            except asyncio.CancelledError:
                logger.info("Worker loop Tuya arrestato.")
                break
            except Exception as e:
                logger.error("Errore non gestito nel loop Tuya: %s", e)
                await asyncio.sleep(10)


tuya_service = TuyaService()
