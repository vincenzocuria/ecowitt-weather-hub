"""
Modulo di integrazione unificato per Home Assistant (Hub Domotico Locale).
Fornisce una facciata coerente e modulare collegando:
- Client HTTP (client.py)
- Parser specializzati (parsers/)
- Costruttore catalogo dispositivi unificato (catalog.py)
- Controller comandi (controllers.py)
- Valutatore sinergie solari/meteo (synergies.py)
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional

from backend.config import settings
from .client import HomeAssistantClient
from .catalog import CatalogHelper
from .controllers import DeviceController
from .synergies import SynergiesHelper
from .parsers.appliances import parse_washer_data, parse_dishwasher_data, parse_fridge_data
from .parsers.presence import parse_presence_data
from .parsers.climate import parse_climate_data
from .parsers.irrigation import parse_irrigation_data
from .parsers.energy import parse_energy_data
from .parsers.health import parse_health_data

logger = logging.getLogger("weather_hub.homeassistant")


class HomeAssistantService:
    """Servizio integrato per Home Assistant."""

    def __init__(self):
        self.client = HomeAssistantClient()
        self.controller = DeviceController(self.client)
        self._catalog_helper = CatalogHelper
        self._synergies_helper = SynergiesHelper

    # Proprietà di stato delegate al client
    @property
    def entities(self) -> Dict[str, Dict[str, Any]]:
        return self.client.entities

    @entities.setter
    def entities(self, val: Dict[str, Dict[str, Any]]):
        self.client.entities = val

    @property
    def enabled(self) -> bool:
        return self.client.enabled

    @property
    def is_connected(self) -> bool:
        return self.client.is_connected

    @is_connected.setter
    def is_connected(self, val: bool):
        self.client.is_connected = val

    @property
    def last_sync_time(self) -> float:
        return self.client.last_sync_time

    @last_sync_time.setter
    def last_sync_time(self, val: float):
        self.client.last_sync_time = val

    @property
    def sync_error(self) -> Optional[str]:
        return self.client.sync_error

    @sync_error.setter
    def sync_error(self, val: Optional[str]):
        self.client.sync_error = val

    # Metodi di connessione
    async def check_connection(self) -> bool:
        return await self.client.check_connection()

    async def fetch_states(self) -> List[Dict[str, Any]]:
        return await self.client.fetch_states()

    # Metodi di parsing
    def parse_washer_data(self) -> Optional[Dict[str, Any]]:
        return parse_washer_data(self.client.entities)

    def parse_dishwasher_data(self) -> Optional[Dict[str, Any]]:
        return parse_dishwasher_data(self.client.entities)

    def parse_fridge_data(self) -> Optional[Dict[str, Any]]:
        return parse_fridge_data(self.client.entities)

    def parse_presence_data(self) -> Dict[str, Any]:
        return parse_presence_data(self.client.entities)

    def parse_climate_data(self) -> List[Dict[str, Any]]:
        return parse_climate_data(self.client.entities)

    def parse_irrigation_data(self) -> Dict[str, Any]:
        return parse_irrigation_data(self.client.entities)

    def parse_energy_data(self) -> Optional[Dict[str, Any]]:
        return parse_energy_data(self.client.entities)

    def parse_health_data(self) -> Dict[str, Any]:
        return parse_health_data(self.client.entities)

    # Riepilogo e Sinergie
    def get_summary(
        self,
        energy_latest: Optional[Dict[str, Any]] = None,
        drying_index: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        return self._synergies_helper.get_summary(
            entities=self.client.entities,
            enabled=self.enabled,
            is_connected=self.is_connected,
            last_sync_time=self.last_sync_time,
            sync_error=self.sync_error,
            energy_latest=energy_latest,
            drying_index=drying_index
        )

    # Catalogo dispositivi
    def get_catalog_devices(self) -> List[Dict[str, Any]]:
        return self._catalog_helper.get_catalog_devices(self.client.entities, self.enabled)

    # Controllo comandi
    async def call_service(self, domain: str, service: str, entity_id: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self.client.call_service(domain, service, entity_id, data)

    async def toggle_device(self, entity_id: str, target_state: bool) -> Dict[str, Any]:
        return await self.controller.toggle_device(entity_id, target_state)

    async def open_irrigation(self, entity_id: str = "valve.aiuola_valve", duration_minutes: int = 10) -> Dict[str, Any]:
        return await self.controller.open_irrigation(entity_id, duration_minutes)

    async def close_irrigation(self, entity_id: str = "valve.aiuola_valve") -> Dict[str, Any]:
        return await self.controller.close_irrigation(entity_id)

    async def control_cover(self, entity_id: str = "cover.persiana_tenda", action: str = "open") -> Dict[str, Any]:
        return await self.controller.control_cover(entity_id, action)

    async def set_climate_temp(self, entity_id: str = "climate.termostato", temp_c: float = 21.0) -> Dict[str, Any]:
        return await self.controller.set_climate_temp(entity_id, temp_c)

    async def set_climate_hvac_mode(self, entity_id: str, mode: str) -> Dict[str, Any]:
        return await self.controller.set_climate_hvac_mode(entity_id, mode)

    async def set_climate_fan_mode(self, entity_id: str, fan_mode: str) -> Dict[str, Any]:
        return await self.controller.set_climate_fan_mode(entity_id, fan_mode)

    async def set_climate_swing_mode(self, entity_id: str, swing_mode: str) -> Dict[str, Any]:
        return await self.controller.set_climate_swing_mode(entity_id, swing_mode)

    def find_entity_by_tuya_id(self, device_id: str) -> Optional[str]:
        return self.controller.find_entity_by_tuya_id(device_id)

    # Worker loop
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
        await self.client.close()


homeassistant_service = HomeAssistantService()

__all__ = [
    "HomeAssistantService",
    "homeassistant_service",
    "HomeAssistantClient",
    "CatalogHelper",
    "DeviceController",
    "SynergiesHelper",
    "parse_washer_data",
    "parse_dishwasher_data",
    "parse_fridge_data",
    "parse_presence_data",
    "parse_climate_data",
    "parse_irrigation_data",
    "parse_energy_data",
    "parse_health_data"
]

