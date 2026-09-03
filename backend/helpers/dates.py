"""
Modulo centralizzato per la formattazione e la localizzazione di date e timestamp (fuso orario italiano).
"""

from datetime import datetime, timezone
from typing import Optional

from backend.config import settings

ITALIAN_MONTHS = {
    1: "Gennaio", 2: "Febbraio", 3: "Marzo", 4: "Aprile",
    5: "Maggio", 6: "Giugno", 7: "Luglio", 8: "Agosto",
    9: "Settembre", 10: "Ottobre", 11: "Novembre", 12: "Dicembre"
}

ITALIAN_SHORT_MONTHS = {
    "01": "Gen", "02": "Feb", "03": "Mar", "04": "Apr",
    "05": "Mag", "06": "Giu", "07": "Lug", "08": "Ago",
    "09": "Set", "10": "Ott", "11": "Nov", "12": "Dic"
}

ITALIAN_WEEKDAYS = {
    0: "Lunedì",
    1: "Martedì",
    2: "Mercoledì",
    3: "Giovedì",
    4: "Venerdì",
    5: "Sabato",
    6: "Domenica"
}


def to_local_datetime_str(iso_str: Optional[str], fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Converte una stringa timestamp ISO UTC nel fuso orario locale configurato (default Europe/Rome)."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local_dt = dt.astimezone(settings.get_tz())
        return local_dt.strftime(fmt)
    except Exception:
        return str(iso_str).replace("T", " ")[:19]


def get_month_name(month: int, default: str = "") -> str:
    """Ritorna il nome esteso in italiano del mese specificato (1-12)."""
    return ITALIAN_MONTHS.get(month, default or str(month))


def get_weekday_name(weekday: int, default: str = "") -> str:
    """Ritorna il giorno della settimana in italiano (0=Lunedì, 6=Domenica)."""
    return ITALIAN_WEEKDAYS.get(weekday, default or str(weekday))


__all__ = [
    "ITALIAN_MONTHS",
    "ITALIAN_SHORT_MONTHS",
    "ITALIAN_WEEKDAYS",
    "to_local_datetime_str",
    "get_month_name",
    "get_weekday_name",
]
