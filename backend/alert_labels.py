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
