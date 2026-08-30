"""
Helper per l'invio di comandi e controllo di entità su Home Assistant.
Supporta switch, luci, valvole, climatizzatori, frigorifero, persiane e risoluzione di ID legacy Tuya/SmartThings.
"""

import logging
from typing import Dict, Any, Optional

from .client import HomeAssistantClient

logger = logging.getLogger("weather_hub.homeassistant.controllers")

TUYA_ID_MAP = {
    "04564850cc50e3d1ca35": "switch.cisterna_presa",
    "bfe099fb503c352edeq28i": "switch.lavasciuga_socket_1",
    "bfb7123e755a2ce701p0xd": "switch.lavastoviglie_socket_1",
    "bf0d071d55d193bc3fxwmp": "switch.climatizzatore_socket_1",
    "bf4a39d41904562ce8gssc": "valve.aiuola_valve",
    "30148414807d3a287c81": "cover.persiana_tenda",
    "5402285098f4abbc53a3": "climate.termostato"
}


class DeviceController:
    """Controller per l'esecuzione di comandi su entità Home Assistant."""

    def __init__(self, client: HomeAssistantClient):
        self.client = client

    def find_entity_by_tuya_id(self, device_id: str) -> Optional[str]:
        """Mappa un vecchio ID Tuya o nome dispositivo alla corrispondente entità Home Assistant."""
        if device_id in TUYA_ID_MAP:
            return TUYA_ID_MAP[device_id]

        for ent_id in self.client.entities:
            if device_id in ent_id:
                return ent_id
        return None

    def resolve_entity_id(self, entity_id: str) -> str:
        """Risolve un entity_id assicurando il prefisso corretto."""
        if entity_id.startswith("hass_"):
            entity_id = entity_id[5:]

        if "." not in entity_id:
            resolved = self.find_entity_by_tuya_id(entity_id)
            if resolved:
                return resolved
            if entity_id == "frigorifero":
                return "switch.frigorifero_express_mode"
            return f"switch.{entity_id}"
        return entity_id

    async def toggle_device(self, entity_id: str, target_state: bool) -> Dict[str, Any]:
        """Accende o spegne un'entità su Home Assistant in base al suo dominio."""
        clean_id = self.resolve_entity_id(entity_id)
        domain = clean_id.split(".")[0]

        if domain in ("switch", "light", "fan"):
            service = "turn_on" if target_state else "turn_off"
            return await self.client.call_service(domain, service, clean_id)
        elif domain == "valve":
            service = "open_valve" if target_state else "close_valve"
            return await self.client.call_service(domain, service, clean_id)
        elif domain == "cover":
            service = "open_cover" if target_state else "close_cover"
            return await self.client.call_service(domain, service, clean_id)
        elif domain == "climate":
            if not target_state:
                return await self.client.call_service("climate", "set_hvac_mode", clean_id, {"hvac_mode": "off"})
            else:
                return await self.client.call_service("climate", "set_hvac_mode", clean_id, {"hvac_mode": "cool"})
        elif domain == "media_player":
            service = "turn_on" if target_state else "turn_off"
            return await self.client.call_service(domain, service, clean_id)

        return {"success": False, "error": f"Dominio {domain} non supporta toggle diretto"}

    async def set_climate_temp(self, entity_id: str = "climate.termostato", temp_c: float = 21.0) -> Dict[str, Any]:
        """Imposta la temperatura del termostato/climatizzatore su Home Assistant."""
        clean_id = self.resolve_entity_id(entity_id)
        if clean_id == "frigorifero" or "frigorifero" in clean_id:
            # Frigorifero target temp
            return await self.client.call_service("number", "set_value", "number.frigorifero_temperatura_fridge", {"value": float(temp_c)})
        return await self.client.call_service("climate", "set_temperature", clean_id, {"temperature": float(temp_c)})

    async def set_climate_hvac_mode(self, entity_id: str, mode: str) -> Dict[str, Any]:
        """Imposta la modalità HVAC (cool, heat, dry, fan_only, auto, off)."""
        clean_id = self.resolve_entity_id(entity_id)
        clean_mode = str(mode).lower()
        return await self.client.call_service("climate", "set_hvac_mode", clean_id, {"hvac_mode": clean_mode})

    async def set_climate_fan_mode(self, entity_id: str, fan_mode: str) -> Dict[str, Any]:
        """Imposta la velocità della ventola per il climatizzatore."""
        clean_id = self.resolve_entity_id(entity_id)
        return await self.client.call_service("climate", "set_fan_mode", clean_id, {"fan_mode": str(fan_mode).lower()})

    async def open_irrigation(self, entity_id: str = "valve.aiuola_valve", duration_minutes: int = 10) -> Dict[str, Any]:
        """Apre l'elettrovalvola o switch di irrigazione specificato su Home Assistant."""
        clean_id = self.resolve_entity_id(entity_id)
        domain = clean_id.split(".")[0]
        if "aiuola" in clean_id and "number.aiuola_irrigation_duration" in self.client.entities:
            try:
                await self.client.call_service(
                    "number",
                    "set_value",
                    "number.aiuola_irrigation_duration",
                    {"value": float(duration_minutes * 60)}
                )
            except Exception:
                pass
        if domain == "switch":
            return await self.client.call_service("switch", "turn_on", clean_id)
        return await self.client.call_service("valve", "open_valve", clean_id)

    async def close_irrigation(self, entity_id: str = "valve.aiuola_valve") -> Dict[str, Any]:
        """Chiude l'elettrovalvola o switch di irrigazione su Home Assistant."""
        clean_id = self.resolve_entity_id(entity_id)
        domain = clean_id.split(".")[0]
        if domain == "switch":
            return await self.client.call_service("switch", "turn_off", clean_id)
        return await self.client.call_service("valve", "close_valve", clean_id)

    async def control_cover(self, entity_id: str = "cover.persiana_tenda", action: str = "open") -> Dict[str, Any]:
        """Controlla persiane/tende su Home Assistant (open, close, stop, set_position)."""
        clean_id = self.resolve_entity_id(entity_id)
        if action == "open":
            return await self.client.call_service("cover", "open_cover", clean_id)
        elif action == "close":
            return await self.client.call_service("cover", "close_cover", clean_id)
        elif action == "stop":
            return await self.client.call_service("cover", "stop_cover", clean_id)
        return {"success": False, "error": f"Azione {action} non riconosciuta per cover"}
