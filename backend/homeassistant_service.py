"""
Modulo di integrazione per Home Assistant (Hub Domotico Locale).
Interroga l'API REST di Home Assistant (/api/states, /api/services) per sincronizzare
e controllare in tempo reale e in locale qualsiasi dispositivo di casa (Tuya, Shelly, Zigbee, Sonoff, ecc.).
"""

import asyncio
import logging
import time
from typing import Dict, Any, List, Optional
import aiohttp

from backend.config import settings

logger = logging.getLogger("weather_hub.homeassistant")

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

    def get_catalog_devices(self) -> List[Dict[str, Any]]:
        """Restituisce le entità rilevanti (switch, light, climate, cover) formattate per il catalogo unificato."""
        if not self.enabled or not self.entities:
            return []

        devices = []
        for entity_id, state_obj in self.entities.items():
            domain = entity_id.split(".")[0]
            if domain not in ("switch", "light", "climate", "cover", "fan"):
                continue

            attributes = state_obj.get("attributes", {})
            friendly_name = attributes.get("friendly_name") or entity_id
            state_str = (state_obj.get("state") or "").lower()
            is_on = state_str in ("on", "open", "cleaning", "cooling", "heating") if state_str not in ("unavailable", "unknown") else None
            is_online = state_str not in ("unavailable", "unknown")

            # Estrai potenza/consumo se presente negli attributi
            power_w = float(attributes.get("current_power_w") or attributes.get("power") or attributes.get("current_consumption") or 0.0)

            # Icona e categoria
            if domain in ("switch", "light"):
                cat = "plugs"
                icon = "💡" if domain == "light" else "🔌"
                cat_label = "Luce Smart" if domain == "light" else "Presa Smart"
            elif domain == "climate":
                cat = "climate"
                icon = "❄️"
                cat_label = "Climatizzatore"
            elif domain == "cover":
                cat = "shutters"
                icon = "🪟"
                cat_label = "Persiana / Tenda"
            else:
                cat = "generic"
                icon = "📱"
                cat_label = "Dispositivo Smart"

            devices.append({
                "id": f"hass_{entity_id}",
                "raw_id": entity_id,
                "ecosystem": "homeassistant",
                "name": friendly_name,
                "icon": icon,
                "category": cat,
                "category_label": f"{cat_label} • HA",
                "is_on": is_on,
                "can_toggle": domain in ("switch", "light", "fan", "cover"),
                "is_online": is_online,
                "status_text": f"Stato: {state_obj.get('state', 'N/D').upper()}",
                "power_w": power_w,
                "raw": state_obj
            })
        return devices

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
                    # Aggiorna subito lo stato locale
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
        domain = entity_id.split(".")[0]
        if domain in ("switch", "light", "fan"):
            service = "turn_on" if target_state else "turn_off"
            return await self.call_service(domain, service, entity_id)
        elif domain == "cover":
            service = "open_cover" if target_state else "close_cover"
            return await self.call_service(domain, service, entity_id)
        elif domain == "climate":
            service = "turn_on" if target_state else "turn_off"
            return await self.call_service(domain, service, entity_id)
        return {"success": False, "error": f"Dominio {domain} non supporta toggle diretto"}

homeassistant_service = HomeAssistantService()
