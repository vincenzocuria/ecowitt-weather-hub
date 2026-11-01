"""
Package di parser specializzati per entità Home Assistant.
"""

from .appliances import parse_washer_data, parse_dishwasher_data, parse_fridge_data
from .presence import parse_presence_data
from .climate import parse_climate_data
from .irrigation import parse_irrigation_data
from .energy import parse_energy_data
from .health import parse_health_data

__all__ = [
    "parse_washer_data",
    "parse_dishwasher_data",
    "parse_fridge_data",
    "parse_presence_data",
    "parse_climate_data",
    "parse_irrigation_data",
    "parse_energy_data",
    "parse_health_data"
]

