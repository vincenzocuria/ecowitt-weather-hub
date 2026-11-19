"""Nomi e icone leggibili per i tipi di notifica (in archivio restano i codici tecnici)."""

ALERT_LABELS = {
    "anomaly": ("Anomalia", "🔎"),
    "battery_full": ("Batteria carica", "🔋"),
    "battery_low": ("Batteria scarica", "🪫"),
    "civil_protection": ("Protezione Civile", "🛡️"),
    "climate_auto_off": ("Clima spento", "❄️"),
    "climate_away_reminder": ("Clima acceso fuori casa", "🏠"),
    "climate_battery_guard": ("Clima e batteria", "🔋"),
    "climate_comfort_auto_on": ("Clima acceso", "🌡️"),
    "climate_comfort_warning": ("Comfort in casa", "🌡️"),
    "climate_night_cooling": ("Fresco notturno", "🌙"),
    "climate_runtime_warning": ("Clima acceso a lungo", "⏱️"),
    "climate_solar_auto_on": ("Clima col sole", "☀️"),
    "climate_solar_opportunity": ("Clima col sole", "☀️"),
    "device_scheduled_action": ("Azione programmata", "⏰"),
    "device_scheduled_action_failed": ("Azione non riuscita", "⚠️"),
    "digest": ("Riepilogo del giorno", "☕"),
    "energy_digest": ("Riepilogo energia", "⚡"),
    "energy_high": ("Consumo elevato", "⚡"),
    "freeze": ("Gelo", "❄️"),
    "fridge_door_away": ("Frigo aperto", "🧊"),
    "fridge_door_open": ("Frigo aperto", "🧊"),
    "fridge_solar_opportunity": ("Frigo col sole", "☀️"),
    "grid_overload_critical": ("Sovraccarico rete", "🚨"),
    "grid_overload_warning": ("Carico rete alto", "⚠️"),
    "hail_warning": ("Grandine", "🧊"),
    "heatwave": ("Caldo intenso", "🔥"),
    "irrigation_advice": ("Consiglio irrigazione", "💧"),
    "irrigation_auto_start": ("Irrigazione avviata", "💧"),
    "irrigation_auto_stop": ("Irrigazione finita", "💧"),
    "irrigation_close_failed": ("Valvola non chiusa", "⚠️"),
    "irrigation_frost_guard": ("Irrigazione e gelo", "❄️"),
    "irrigation_learning_insight": ("Irrigazione", "💧"),
    "irrigation_manual_start": ("Irrigazione avviata", "💧"),
    "irrigation_manual_stop": ("Irrigazione finita", "💧"),
    "irrigation_rain_shutoff": ("Irrigazione fermata", "🌧️"),
    "irrigation_skip_rain": ("Irrigazione saltata", "🌧️"),
    "irrigation_skip_wind": ("Irrigazione saltata", "💨"),
    "irrigation_soil_saturated": ("Terreno saturo", "🌱"),
    "leak": ("Perdita di acqua", "🚰"),
    "lightning": ("Fulmini", "⚡"),
    "monthly_digest": ("Riepilogo del mese", "📊"),
    "offline": ("Stazione offline", "📡"),
    "online": ("Stazione online", "🟢"),
    "presence_away": ("Fuori casa", "🚶"),
    "presence_home": ("A casa", "🏠"),
    "rain": ("Pioggia", "🌧️"),
    "rain_forecast": ("Pioggia in arrivo", "☔"),
    "rain_start": ("Inizio pioggia", "🌧️"),
    "record": ("Record", "🏆"),
    "soil_dry": ("Terreno secco", "🌱"),
    "soil_recovered": ("Terreno a posto", "🌱"),
    "soil_wet": ("Terreno bagnato", "🌱"),
    "solar_synergy_appliances": ("Elettrodomestici col sole", "☀️"),
    "storm": ("Temporale", "⚠️"),
    "uv_extreme": ("UV estremo", "☀️"),
    "washer_finish": ("Lavatrice finita", "🧺"),
    "wind_spike": ("Raffica di vento", "💨"),
}


def alert_label(alert_type) -> str:
    key = str(alert_type or "").strip()
    if not key:
        return "Notifica"
    if key in ALERT_LABELS:
        return ALERT_LABELS[key][0]
    return key.replace("_", " ").capitalize()


def alert_icon(alert_type) -> str:
    item = ALERT_LABELS.get(str(alert_type or "").strip())
    return item[1] if item else "🔔"


ALERT_CATEGORIES = [
    ("meteo", "Meteo", "🌦️"),
    ("casa", "Casa", "🏠"),
    ("giardino", "Giardino", "🌱"),
    ("energia", "Energia", "⚡"),
    ("sistema", "Sistema", "⚙️"),
]

_CATEGORY_PREFIXES = (
    ("irrigation_", "giardino"), ("soil_", "giardino"),
    ("energy_", "energia"), ("grid_", "energia"), ("battery_", "energia"), ("solar_", "energia"),
    ("climate_", "casa"), ("fridge_", "casa"), ("washer_", "casa"), ("presence_", "casa"),
    ("device_", "casa"), ("leak", "casa"),
    ("offline", "sistema"), ("online", "sistema"),
)

_WEEKDAYS = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")
_MONTHS = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
           "agosto", "settembre", "ottobre", "novembre", "dicembre")


def alert_category(alert_type) -> str:
    key = str(alert_type or "")
    for prefix, category in _CATEGORY_PREFIXES:
        if key.startswith(prefix):
            return category
    return "meteo"


def clean_alert_title(title) -> str:
    """Toglie emoji e simboli iniziali: l'icona è già mostrata accanto."""
    text = str(title or "").strip()
    i = 0
    while i < len(text) and not text[i].isalnum():
        i += 1
    return text[i:].strip() or text


def _local_dt(iso_str, tz):
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def build_alert_days(alerts, tz, now=None):
    """Raggruppa le notifiche per giorno locale; nello stesso giorno unisce quelle dello stesso tipo.

    Ritorna una lista di giorni (dal più recente), ognuno con le sue voci; ogni voce ha
    l'ultima notifica del tipo e l'elenco completo delle occorrenze di quel giorno.
    """
    from datetime import datetime, timedelta
    now = (now or datetime.now(tz)).astimezone(tz)
    today = now.date()
    days = {}
    for a in alerts:
        dt = _local_dt(a.get("timestamp"), tz)
        if dt is None:
            continue
        day = days.setdefault(dt.date(), {})
        kind = str(a.get("alert_type") or "")
        item = {
            "id": a.get("id"),
            "time": dt.strftime("%H:%M"),
            "title": clean_alert_title(a.get("title")),
            "message": str(a.get("message") or "").strip(),
            "unread": not a.get("is_read"),
            "_dt": dt,
        }
        day.setdefault(kind, []).append(item)
    out = []
    for date in sorted(days, reverse=True):
        entries = []
        for kind, items in days[date].items():
            items.sort(key=lambda x: x["_dt"], reverse=True)
            entries.append({
                "type": kind,
                "label": alert_label(kind),
                "icon": alert_icon(kind),
                "category": alert_category(kind),
                "count": len(items),
                "unread": sum(1 for x in items if x["unread"]),
                "latest": items[0],
                "occurrences": items,
                "ids": [x["id"] for x in items],
            })
        entries.sort(key=lambda e: e["latest"]["_dt"], reverse=True)
        if date == today:
            name = "Oggi"
        elif date == today - timedelta(days=1):
            name = "Ieri"
        else:
            name = _WEEKDAYS[date.weekday()].capitalize()
        out.append({
            "key": date.isoformat(),
            "name": name,
            "date_label": f"{date.day} {_MONTHS[date.month - 1]}",
            "count": sum(e["count"] for e in entries),
            "unread": sum(e["unread"] for e in entries),
            "entries": entries,
        })
    if not out or out[0]["key"] != today.isoformat():
        out.insert(0, {"key": today.isoformat(), "name": "Oggi",
                       "date_label": f"{today.day} {_MONTHS[today.month - 1]}",
                       "count": 0, "unread": 0, "entries": []})
    return out
