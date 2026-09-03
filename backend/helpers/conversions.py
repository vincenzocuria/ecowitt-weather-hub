"""
Modulo centralizzato per conversioni di unità fisiche/meteorologiche e parsing numerico sicuro.
"""

from typing import Any, Optional


def safe_float(val: Any, default: Optional[float] = None) -> Optional[float]:
    """Converte un valore in float gestendo None, stringhe vuote ed eccezioni."""
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_int(val: Any, default: Optional[int] = None) -> Optional[int]:
    """Converte un valore in int gestendo None, stringhe vuote ed eccezioni."""
    if val is None or val == "":
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def f_to_c(f: Optional[float]) -> Optional[float]:
    """Fahrenheit -> Celsius."""
    if f is None:
        return None
    return round((f - 32.0) * (5.0 / 9.0), 1)


def c_to_f(c: Optional[float]) -> Optional[float]:
    """Celsius -> Fahrenheit."""
    if c is None:
        return None
    return round((c * 9.0 / 5.0) + 32.0, 1)


def inch_to_mm(inch: Optional[float]) -> Optional[float]:
    """Pollici -> Millimetri."""
    if inch is None:
        return None
    return round(inch * 25.4, 1)


def mm_to_inch(mm: Optional[float]) -> Optional[float]:
    """Millimetri -> Pollici."""
    if mm is None:
        return None
    return round(mm / 25.4, 3)


def mph_to_kmh(mph: Optional[float]) -> Optional[float]:
    """Miglia orarie -> Chilometri orari."""
    if mph is None:
        return None
    return round(mph * 1.60934, 1)


def kmh_to_mph(kmh: Optional[float]) -> Optional[float]:
    """Chilometri orari -> Miglia orarie."""
    if kmh is None:
        return None
    return round(kmh / 1.60934, 1)


def inhg_to_hpa(inhg: Optional[float]) -> Optional[float]:
    """Pollici di mercurio -> ettopascal (hPa)."""
    if inhg is None:
        return None
    return round(inhg * 33.86389, 1)


def hpa_to_inhg(hpa: Optional[float]) -> Optional[float]:
    """Ettopascal (hPa) -> pollici di mercurio."""
    if hpa is None:
        return None
    return round(hpa / 33.86389, 2)


def wm2_to_lux(wm2: Optional[float]) -> Optional[float]:
    """W/m² -> Lux solari stimati."""
    if wm2 is None:
        return None
    return round(wm2 * 126.7, 1)


def lux_to_wm2(lux: Optional[float]) -> Optional[float]:
    """Lux solari stimati -> W/m²."""
    if lux is None:
        return None
    return round(lux / 126.7, 1)


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
]
