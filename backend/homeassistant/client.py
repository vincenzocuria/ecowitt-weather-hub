"""
Client HTTP asincrono dedicato alla comunicazione con l'API REST di Home Assistant.
Gestisce autenticazione, session pooling aiohttp, lock e chiamate di servizio generiche.
"""

import asyncio
import logging
import time
from typing import Dict, Any, List, Optional
import aiohttp

from backend.config import settings

logger = logging.getLogger("weather_hub.homeassistant.client")


class HomeAssistantClient:
    """Client REST asincrono per Home Assistant."""

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.entities: Dict[str, Dict[str, Any]] = {}
        self.is_connected: bool = False
        self.last_sync_time: float = 0.0
        self.sync_error: Optional[str] = None
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        """Indica se l'integrazione con Home Assistant è abilitata e configurata."""
        return settings.HASS_ENABLED and bool(settings.HASS_TOKEN)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.HASS_TOKEN}",
            "Content-Type": "application/json"
        }

    async def get_session(self) -> aiohttp.ClientSession:
        """Restituisce o inizializza la sessione client aiohttp."""
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

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Chiama un servizio su Home Assistant (es. switch/turn_on, climate/set_temperature, notify/mobile_app_xxx)."""
        if not self.enabled:
            return {"success": False, "error": "Home Assistant non configurato o disabilitato"}

        payload = {}
        if entity_id:
            payload["entity_id"] = entity_id
        if data:
            payload.update(data)

        try:
            session = await self.get_session()
            url = f"{settings.HASS_URL}/api/services/{domain}/{service}"
            async with session.post(url, headers=self._headers(), json=payload) as resp:
                if resp.status in (200, 201):
                    res_json = await resp.json()
                    target_desc = f" su {entity_id}" if entity_id else ""
                    logger.info("✅ [HASS] Servizio %s.%s eseguito%s", domain, service, target_desc)
                    await self.fetch_states()
                    return {"success": True, "result": res_json}
                else:
                    err_txt = await resp.text()
                    logger.error("❌ [HASS] Errore chiamata servizio %s.%s (HTTP %s): %s", domain, service, resp.status, err_txt)
                    return {"success": False, "error": f"HTTP {resp.status}: {err_txt}"}
        except Exception as e:
            logger.error("❌ [HASS] Errore connessione servizio %s: %s", entity_id, e)
            return {"success": False, "error": str(e)}

    async def close(self):
        """Chiude la sessione HTTP."""
        if self.session and not self.session.closed:
            await self.session.close()
