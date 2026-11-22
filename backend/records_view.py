"""Prepara i record di sempre per la pagina Record: riepilogo, filtri e schede leggibili."""
from collections import Counter
from datetime import datetime, timezone

CATEGORIES = [
    ("temperature", "Temperatura", "🌡️"),
    ("wind", "Vento", "💨"),
    ("rain", "Pioggia", "🌧️"),
    ("pressure", "Pressione", "⏲️"),
    ("solar", "Sole", "☀️"),
    ("lightning", "Fulmini", "⚡"),
]
_CAT = {k: (name, icon) for k, name, icon in CATEGORIES}

TITLES = {
    "temp_max": "Temperatura più alta",
    "temp_min": "Temperatura più bassa",
    "temp_min_highest": "Notte più calda",
    "dew_point_max": "Rugiada più alta",
    "wind_gust_max": "Raffica più forte",
    "wind_speed_max": "Vento medio più forte",
    "rain_rate_max": "Pioggia più intensa",
    "rain_daily_max": "Più pioggia in un giorno",
    "pressure_max": "Pressione più alta",
    "pressure_min": "Pressione più bassa",
    "uv_max": "UV più alto",
    "solar_max": "Sole più forte",
    "lightning_closest": "Fulmine più vicino",
}
NOTES = {
    "temp_min_highest": "la minima più alta di una notte",
    "rain_rate_max": "intensità massima",
    "solar_max": "radiazione solare",
}
# I quattro record in evidenza in cima alla pagina
HIGHLIGHTS = [
    ("temp_max", "Più caldo"),
    ("temp_min", "Più freddo"),
    ("wind_gust_max", "Raffica"),
    ("rain_daily_max", "Pioggia in un giorno"),
]

_MONTHS = ("gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic")
_COMPASS = {
    "N": "Nord", "NNE": "Nord-Nord-Est", "NE": "Nord-Est", "ENE": "Est-Nord-Est",
    "E": "Est", "ESE": "Est-Sud-Est", "SE": "Sud-Est", "SSE": "Sud-Sud-Est",
    "S": "Sud", "SSW": "Sud-Sud-Ovest", "SW": "Sud-Ovest", "WSW": "Ovest-Sud-Ovest",
    "W": "Ovest", "WNW": "Ovest-Nord-Ovest", "NW": "Nord-Ovest", "NNW": "Nord-Nord-Ovest",
}
NEW_DAYS = 30


def _parse(ts, tz):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def format_value(value, unit):
    if value is None:
        return "--"
    v = float(value)
    if unit == "W/m²" or (unit == "UV" and v.is_integer()):
        return f"{v:.0f}"
    return f"{v:.1f}"


def format_direction(raw):
    """'280° (W)' -> 'da Ovest · 280°'."""
    if not raw:
        return ""
    text = str(raw)
    deg = text.split("°")[0].strip()
    code = text[text.find("(") + 1:text.find(")")] if "(" in text else ""
    name = _COMPASS.get(code.strip().upper(), code)
    if name and deg:
        return f"da {name} · {deg}°"
    return text


def relative_age(dt, now):
    days = (now.date() - dt.date()).days
    if days <= 0:
        return "oggi"
    if days == 1:
        return "ieri"
    if days < 30:
        return f"{days} giorni fa"
    months = days // 30
    if months < 12:
        return "1 mese fa" if months == 1 else f"{months} mesi fa"
    years = days // 365
    return "1 anno fa" if years == 1 else f"{years} anni fa"


def build_records_view(records, history, tz, now=None):
    now = (now or datetime.now(tz)).astimezone(tz)
    beaten = Counter(h.get("record_key") for h in (history or []))
    cards = []
    for r in records or []:
        key = r.get("record_key") or r.get("key") or ""
        cat = r.get("category") or "temperature"
        cat_name, cat_icon = _CAT.get(cat, (cat.capitalize(), "📈"))
        details = r.get("details") or {}
        dt = _parse(r.get("timestamp"), tz)
        has_value = r.get("value") is not None and dt is not None
        when = ""
        if has_value:
            day = details.get("date")
            if day:
                try:
                    d = datetime.strptime(day, "%Y-%m-%d")
                    when = f"{d.day} {_MONTHS[d.month - 1]} {d.year}"
                except ValueError:
                    when = f"{dt.day} {_MONTHS[dt.month - 1]} {dt.year}"
            else:
                when = f"{dt.day} {_MONTHS[dt.month - 1]} {dt.year} · {dt:%H:%M}"
        cards.append({
            "key": key,
            "category": cat,
            "cat_name": cat_name,
            "icon": cat_icon,
            "title": TITLES.get(key, r.get("title") or key),
            "note": NOTES.get(key, ""),
            "value": format_value(r.get("value"), r.get("unit")),
            "unit": r.get("unit") or "",
            "has_value": has_value,
            "when": when,
            "age": relative_age(dt, now) if has_value else "",
            "is_new": has_value and (now - dt).days < NEW_DAYS,
            "direction": format_direction(details.get("dir")),
            "beaten": beaten.get(key, 0),
            "search": f"{TITLES.get(key, '')} {r.get('title', '')} {cat_name} {r.get('unit', '')}".lower(),
        })
    order = {k: i for i, (k, _, _) in enumerate(CATEGORIES)}
    cards.sort(key=lambda c: order.get(c["category"], 99))

    by_key = {c["key"]: c for c in cards}
    highlights = []
    for key, label in HIGHLIGHTS:
        c = by_key.get(key)
        if c and c["has_value"]:
            highlights.append({"label": label, "icon": c["icon"], "value": c["value"], "unit": c["unit"],
                               "when": c["when"].split(" · ")[0], "category": c["category"], "key": key})

    counts = Counter(c["category"] for c in cards)
    filters = [{"key": k, "name": n, "icon": i, "count": counts[k]} for k, n, i in CATEGORIES if counts[k]]

    latest = None
    if history:
        h = history[0]
        hdt = _parse(h.get("timestamp"), tz)
        if hdt is not None:
            latest = {
                "title": TITLES.get(h.get("record_key"), h.get("title") or ""),
                "value": format_value(h.get("new_value"), h.get("unit")),
                "unit": h.get("unit") or "",
                "age": relative_age(hdt, now),
            }
    return {
        "cards": cards,
        "highlights": highlights,
        "filters": filters,
        "total": len(cards),
        "new_count": sum(1 for c in cards if c["is_new"]),
        "latest": latest,
    }
