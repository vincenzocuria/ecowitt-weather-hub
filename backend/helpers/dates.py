"""
Modulo centralizzato per la formattazione e la localizzazione di date e timestamp (fuso orario italiano).
"""

from datetime import datetime, timezone
from typing import Optional, Union

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


def format_duration_italian(minutes: Optional[Union[int, float]], show_seconds: bool = False) -> str:
    """
    Formatta una durata in minuti in una stringa leggibile in italiano con ore e minuti.
    Esempi:
        0 o < 1 -> "meno di un minuto"
        1 -> "1 minuto"
        13 -> "13 minuti"
        60 -> "1 ora"
        61 -> "1 ora e 1 minuto"
        120 -> "2 ore"
        193 -> "3 ore e 13 minuti"
        999 -> "16 ore e 39 minuti"
    """
    if minutes is None:
        return "—"
    try:
        val = float(minutes)
        if val < 0:
            return "—"
        total_m = int(round(val))
    except (ValueError, TypeError):
        return str(minutes)

    if total_m < 1:
        return "meno di un minuto"
    if total_m < 60:
        return f"{total_m} {'minuto' if total_m == 1 else 'minuti'}"

    ore = total_m // 60
    rem_m = total_m % 60
    h_str = "1 ora" if ore == 1 else f"{ore} ore"
    if rem_m == 0:
        return h_str
    m_str = "1 minuto" if rem_m == 1 else f"{rem_m} minuti"
    return f"{h_str} e {m_str}"


def format_seconds_italian(seconds: Optional[Union[int, float]]) -> str:
    """
    Formatta una durata in secondi in formato leggibile italiano con ore, minuti o secondi.
    """
    if seconds is None:
        return "—"
    try:
        sec = max(0, int(round(float(seconds))))
    except (ValueError, TypeError):
        return str(seconds)

    if sec < 60:
        return f"{sec} {'secondo' if sec == 1 else 'secondi'}"
    return format_duration_italian(sec / 60.0)


__all__ = [
    "ITALIAN_MONTHS",
    "ITALIAN_SHORT_MONTHS",
    "ITALIAN_WEEKDAYS",
    "to_local_datetime_str",
    "get_month_name",
    "get_weekday_name",
    "format_duration_italian",
    "format_seconds_italian",
]
