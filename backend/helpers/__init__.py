"""
Package helpers: funzioni e costanti di utilità centralizzate (conversioni, date, localizzazione).
"""

from .conversions import (
    safe_float,
    safe_int,
    f_to_c,
    c_to_f,
    inch_to_mm,
    mm_to_inch,
    mph_to_kmh,
    kmh_to_mph,
    inhg_to_hpa,
    hpa_to_inhg,
    wm2_to_lux,
    lux_to_wm2,
)
from .dates import (
    ITALIAN_MONTHS,
    ITALIAN_SHORT_MONTHS,
    ITALIAN_WEEKDAYS,
    to_local_datetime_str,
    get_month_name,
    get_weekday_name,
)

__all__ = [
    "safe_float",
    "safe_int",
    "f_to_c",
    "c_to_f",
    "inch_to_mm",
    "mm_to_inch",
    "mph_to_kmh",
    "kmh_to_mph",
    "inhg_to_hpa",
    "hpa_to_inhg",
    "wm2_to_lux",
    "lux_to_wm2",
    "ITALIAN_MONTHS",
    "ITALIAN_SHORT_MONTHS",
    "ITALIAN_WEEKDAYS",
    "to_local_datetime_str",
    "get_month_name",
    "get_weekday_name",
]
