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
from backend.database import (
    get_tuya_device_configs, save_tuya_device_config,
    get_tuya_local_devices, get_tuya_local_device, save_tuya_local_device,
    update_tuya_local_status, update_tuya_local_device_ip, delete_tuya_local_device
)

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
                else:
                    payload_txt = str(res.get("Payload") or "")
                    msg_txt = str(res.get("msg") or "")
                    err_txt = str(res.get("Error") or "")
                    
                    full_err = f"{payload_txt} {msg_txt} {err_txt}".lower()
                    if "trial quota is exhausted" in full_err or "quota is exhausted" in full_err or "28841105" in full_err or "28841002" in full_err:
                        err_msg = "Quota API Tuya IoT Core scaduta su iot.tuya.com: estendi gratuitamente il periodo di prova da Cloud -> API Services -> IoT Core -> Extend Trial Period."
                    elif "permission deny" in full_err or "1106" in full_err:
                        err_msg = "Permesso negato da Tuya Cloud: verifica che il progetto su iot.tuya.com abbia abilitato il servizio IoT Core per questo dispositivo."
                    elif "device is offline" in full_err or "2008" in full_err:
                        err_msg = "Il dispositivo Tuya risulta spento o non connesso al Wi-Fi / Cloud."
                    elif payload_txt:
                        err_msg = str(res.get("Payload"))
                    elif msg_txt:
                        err_msg = msg_txt
                    elif err_txt:
                        err_msg = err_txt
                    elif res.get("code") and res.get("code") != 0:
                        err_msg = f"Errore Tuya {res.get('code')}: {res.get('msg', '')}"
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

    # =========================================================================
    # CONTROLLO LOCALE LAN (ZERO CLOUD - SENZA API TRIAL)
    # =========================================================================

    async def scan_lan_devices(self, subnet_prefix: str = "192.168.1", port: int = 6668, timeout_sec: float = 0.6) -> List[Dict[str, Any]]:
        """Esegue una scansione asincrona TCP veloce della rete locale per trovare tutti i dispositivi Tuya (porta 6668)."""
        async def _check(ip: str):
            try:
                conn = asyncio.open_connection(ip, port)
                reader, writer = await asyncio.wait_for(conn, timeout=timeout_sec)
                writer.close()
                await writer.wait_closed()
                return {"ip": ip, "port": port, "open": True}
            except Exception:
                return None

        tasks = [_check(f"{subnet_prefix}.{i}") for i in range(1, 255)]
        results = await asyncio.gather(*tasks)
        found = [r for r in results if r]
        logger.info("📡 [Tuya LAN Scan] Trovati %d IP con porta Tuya aperta: %s", len(found), [f['ip'] for f in found])
        return found

    async def discover_device_ip(self, device_id: str) -> Optional[str]:
        """Cerca l'IP locale associato a uno specifico device_id interrogando i dispositivi Tuya trovati su LAN."""
        local_cfg = get_tuya_local_device(device_id)
        key = local_cfg.get("local_key") if local_cfg else None
        
        lan_hosts = await self.scan_lan_devices()
        loop = asyncio.get_running_loop()
        
        for host in lan_hosts:
            ip = host["ip"]
            if key:
                def _test(ip_addr, l_key):
                    try:
                        d = tinytuya.OutletDevice(device_id, ip_addr, l_key, version=3.3, connection_timeout=1.0)
                        d.set_socketPersistent(False)
                        st = d.status()
                        if st and (st.get("dps") or st.get("devId") == device_id):
                            return True
                    except Exception:
                        pass
                    return False

                matched = await loop.run_in_executor(None, _test, ip, key)
                if matched:
                    logger.info("🎯 [Tuya Local] Rilevato IP %s per device_id %s", ip, device_id)
                    update_tuya_local_device_ip(device_id, ip)
                    return ip

        # Se c'è un solo dispositivo Tuya sulla rete ed è l'unico configurato, associa quell'IP
        if len(lan_hosts) == 1:
            lone_ip = lan_hosts[0]["ip"]
            logger.info("🎯 [Tuya Local] Associato unico IP Tuya trovato %s a %s", lone_ip, device_id)
            update_tuya_local_device_ip(device_id, lone_ip)
            return lone_ip

        return None

    async def control_device_local(self, device_id: str, new_state: bool, switch_num: int = 1) -> Dict[str, Any]:
        """Comanda direttamente il dispositivo Tuya via socket locale TCP (porta 6668, zero cloud)."""
        local_dev = get_tuya_local_device(device_id)
        if not local_dev or not local_dev.get("local_key"):
            return {"success": False, "error": "Chiave locale (local_key) non presente"}

        ip = local_dev.get("ip_address")
        key = local_dev.get("local_key")
        version_str = str(local_dev.get("version") or "3.3")

        # Se non c'è un IP, tenta discovery
        if not ip:
            ip = await self.discover_device_ip(device_id)
            if not ip:
                return {"success": False, "error": "Indirizzo IP locale non trovato sulla rete"}

        loop = asyncio.get_running_loop()

        def _sync_local_toggle():
            try:
                ver_val = float(version_str)
            except Exception:
                ver_val = 3.3

            d = tinytuya.OutletDevice(
                dev_id=device_id,
                address=ip,
                local_key=key,
                version=ver_val,
                connection_timeout=2.5
            )
            d.set_socketPersistent(False)

            res = d.set_status(new_state, switch=switch_num)
            if isinstance(res, dict) and ("Error" in res or res.get("success") is False):
                res = d.set_value(switch_num, new_state)

            stat = None
            try:
                stat = d.status()
            except Exception:
                pass
            return res, stat

        try:
            res, stat = await loop.run_in_executor(None, _sync_local_toggle)
            is_ok = False
            if isinstance(res, dict):
                if res.get("Error") is None and res.get("success") is not False:
                    is_ok = True
                elif res.get("dps"):
                    is_ok = True
            elif res is True:
                is_ok = True

            if is_ok:
                logger.info("⚡ [Tuya Local LAN] Dispositivo %s impostato a %s via LAN (%s)", device_id, new_state, ip)
                p_w = 0.0
                v_v = 0.0
                c_a = 0.0
                if isinstance(stat, dict) and "dps" in stat:
                    dps = stat["dps"]
                    if "19" in dps:
                        p_w = round(float(dps["19"]) / 10.0, 1)
                    if "20" in dps:
                        v_v = round(float(dps["20"]) / 10.0, 1)
                    if "18" in dps:
                        c_a = round(float(dps["18"]) / 1000.0, 2)
                
                update_tuya_local_status(device_id, is_on=new_state, power_w=p_w, voltage_v=v_v, current_a=c_a)
                
                if device_id in self.device_statuses:
                    self.device_statuses[device_id]["is_on"] = new_state
                    if p_w > 0:
                        self.device_statuses[device_id]["power_w"] = p_w
                    if v_v > 0:
                        self.device_statuses[device_id]["voltage_v"] = v_v
                    if c_a > 0:
                        self.device_statuses[device_id]["current_a"] = c_a
                else:
                    self.device_statuses[device_id] = {
                        "id": device_id,
                        "name": local_dev.get("name", "Presa Smart"),
                        "category": local_dev.get("category", "cz"),
                        "type": "plug",
                        "is_on": new_state,
                        "power_w": p_w,
                        "voltage_v": v_v,
                        "current_a": c_a,
                        "online": True
                    }
                self._save_cache()
                return {"success": True, "local": True, "mode": "LAN", "ip": ip, "result": res}
            else:
                err = res.get("Error") if isinstance(res, dict) else "Errore risposta socket locale"
                return {"success": False, "local": True, "error": str(err)}
        except Exception as e:
            logger.warning("⚠️ [Tuya Local] Errore LAN su %s (%s): %s", device_id, ip, e)
            return {"success": False, "local": True, "error": str(e)}

    async def import_keys_from_cloud(self) -> Dict[str, Any]:
        """Tenta di scaricare tutte le local_key da Tuya Cloud per salvarle permanentemente in locale."""
        if not self.cloud:
            return {"success": False, "error": "Tuya Cloud client non inizializzato"}
            
        loop = asyncio.get_running_loop()
        try:
            devs_resp = await loop.run_in_executor(None, self.cloud._get_all_devices)
            items = []
            if isinstance(devs_resp, dict) and "result" in devs_resp:
                items = devs_resp["result"]
            elif isinstance(devs_resp, list):
                items = devs_resp
                
            imported = 0
            for item in items:
                d_id = item.get("id")
                d_name = item.get("name") or "Dispositivo Tuya"
                d_key = item.get("local_key") or item.get("key")
                d_ip = item.get("ip") or item.get("last_ip")
                d_cat = item.get("category", "cz")
                
                if d_id and d_key:
                    save_tuya_local_device(
                        device_id=d_id,
                        name=d_name,
                        local_key=d_key,
                        ip_address=d_ip,
                        version="3.3",
                        category=d_cat
                    )
                    imported += 1
                    logger.info("🔑 [Tuya Local] Importata chiave permanente per '%s' (ID: %s)", d_name, d_id)
            
            return {"success": True, "imported_count": imported, "total_found": len(items)}
        except Exception as e:
            logger.error("Errore importazione chiavi Tuya: %s", e)
            return {"success": False, "error": str(e)}

    async def toggle_device(self, device_id: str, target_state: Optional[bool] = None) -> Dict[str, Any]:
        """Inverte o imposta lo stato ON/OFF del dispositivo, privilegiando il controllo 100% LOCALE LAN."""
        dev = self.device_statuses.get(device_id)
        if not dev:
            # Prova a sincronizzare o leggere configurazione locale
            local_info = get_tuya_local_device(device_id)
            if local_info:
                dev = {
                    "id": device_id,
                    "name": local_info["name"],
                    "category": local_info["category"],
                    "is_on": local_info["is_on"] or False,
                    "online": True
                }
                self.device_statuses[device_id] = dev

        current_state = dev.get("is_on", False) if dev else False
        new_state = (not current_state) if target_state is None else target_state

        # --- 1. TENTATIVO CONTROLLO 100% LOCALE LAN (Zero Cloud) ---
        local_cfg = get_tuya_local_device(device_id)
        if local_cfg and local_cfg.get("local_key"):
            local_res = await self.control_device_local(device_id, new_state)
            if local_res.get("success"):
                logger.info("✅ [Tuya Toggle] Eseguito con successo via LAN LOCALE su %s", device_id)
                return local_res
            else:
                logger.warning("⚠️ [Tuya Toggle] Controllo locale fallito (%s), fallback a Cloud...", local_res.get("error"))

        # --- 2. FALLBACK A TUYA CLOUD ---
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
