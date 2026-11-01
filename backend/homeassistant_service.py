"""
Modulo di compatibilità retroattiva per Home Assistant Service.
Reindirizza le importazioni al nuovo package modulare 'backend.homeassistant'.
"""

from backend.homeassistant import (
    HomeAssistantService,
    homeassistant_service,
    HomeAssistantClient,
    CatalogHelper,
    DeviceController,
    SynergiesHelper,
    parse_washer_data,
    parse_dishwasher_data,
    parse_presence_data,
    parse_climate_data,
    parse_irrigation_data,
    parse_energy_data,
    parse_health_data
)
from backend.homeassistant.parsers.appliances import WASHER_STATE_MAP, DISHWASHER_STATE_MAP

__all__ = [
    "HomeAssistantService",
    "homeassistant_service",
    "HomeAssistantClient",
    "CatalogHelper",
    "DeviceController",
    "SynergiesHelper",
    "WASHER_STATE_MAP",
    "DISHWASHER_STATE_MAP",
    "parse_washer_data",
    "parse_dishwasher_data",
    "parse_presence_data",
    "parse_climate_data",
    "parse_irrigation_data",
    "parse_energy_data",
    "parse_health_data"
]
