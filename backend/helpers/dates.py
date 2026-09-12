"""
Modulo centralizzato per la formattazione e la localizzazione di date e timestamp (fuso orario italiano).
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, Union, Any

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


def format_lightning_time_italian(val: Any, include_relative: bool = True) -> str:
    """
    Formatta la data/ora di una scarica di fulmine in modo chiaro, naturale e nel fuso orario italiano.
    Accetta stringhe ISO (anche UTC), float/int epoch o oggetti datetime.
    Esempi:
        - "Oggi alle 13:14 (2 min fa)"
        - "Oggi alle 08:30"
        - "Ieri alle 21:15"
        - "10 Ago alle 15:52"
        - "Nessuna recente" se nullo o vuoto
    """
    if val is None or val == "":
        return "Nessuna recente"

    tz = settings.get_tz()
    now_local = datetime.now(timezone.utc).astimezone(tz)

    dt_local = None
    if isinstance(val, (int, float)):
        try:
            if val <= 0:
                return "Nessuna recente"
            dt_local = datetime.fromtimestamp(val, tz=timezone.utc).astimezone(tz)
        except Exception:
            return "Nessuna recente"
    elif isinstance(val, datetime):
        if val.tzinfo is None:
            dt_local = val.replace(tzinfo=timezone.utc).astimezone(tz)
        else:
            dt_local = val.astimezone(tz)
    elif isinstance(val, str):
        v = val.strip()
        if not v or v.lower() in ("none", "null", "nessuna", "nessuna recente", "n/d", "--"):
            return "Nessuna recente"
        try:
            if v.isdigit():
                return format_lightning_time_italian(int(v), include_relative)
            parsed_dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            if parsed_dt.tzinfo is None:
                parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
            dt_local = parsed_dt.astimezone(tz)
        except Exception:
            if len(v) == 5 and ":" in v:
                return f"Oggi alle {v}"
            return v
    else:
        return "Nessuna recente"

    diff_sec = max(0, int((now_local - dt_local).total_seconds()))
    diff_min = diff_sec // 60

    time_str = dt_local.strftime("%H:%M")
    today_date = now_local.date()
    strike_date = dt_local.date()

    if strike_date == today_date:
        day_prefix = "Oggi alle"
        if include_relative:
            if diff_min < 1:
                rel_str = "meno di 1 min fa"
            elif diff_min == 1:
                rel_str = "1 min fa"
            elif diff_min < 60:
                rel_str = f"{diff_min} min fa"
            elif diff_min < 120:
                rel_str = "1 ora fa"
            elif diff_min < 1440:
                rel_str = f"{diff_min // 60} ore fa"
            else:
                rel_str = ""
            return f"{day_prefix} {time_str} ({rel_str})" if rel_str else f"{day_prefix} {time_str}"
        return f"{day_prefix} {time_str}"
    elif strike_date == (today_date - timedelta(days=1)):
        return f"Ieri alle {time_str}"
    else:
        month_abbr = ITALIAN_SHORT_MONTHS.get(f"{dt_local.month:02d}", dt_local.strftime("%b"))
        return f"{dt_local.day} {month_abbr} alle {time_str}"


__all__ = [
    "ITALIAN_MONTHS",
    "ITALIAN_SHORT_MONTHS",
    "ITALIAN_WEEKDAYS",
    "to_local_datetime_str",
    "get_month_name",
    "get_weekday_name",
    "format_duration_italian",
    "format_seconds_italian",
    "format_lightning_time_italian",
]

