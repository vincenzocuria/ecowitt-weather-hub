"""
Catalogo degli allarmi per la pagina Impostazioni.

Le soglie arrivano dalla configurazione e la regola notturna da notifier.wakes_at_night,
così la tabella resta allineata a quello che il sistema fa davvero.
"""
from typing import Any, Dict, List

from backend.config import settings
from backend.notifier import wakes_at_night

PRIORITY_LABELS = {"urgent": "Urgente", "high": "Alta", "normal": "Normale", "low": "Informativa"}


def _fmt(v: float) -> str:
    return f"{v:g}".replace(".", ",")


def build_alert_catalog() -> List[Dict[str, Any]]:
    s = settings
    cp_level = (s.CIVIL_PROTECTION_MIN_ALERT_LEVEL or "GIALLA").capitalize()
    groups = [
        ("Meteo", [
            ("civil_protection", "🛡️", "Allerta Protezione Civile", f"Bollettino DPC/ARPACAL per la zona, livello {cp_level} o superiore", "urgent"),
            ("lightning", "⚡", "Fulmini vicini", f"Fulmine rilevato entro {_fmt(s.LIGHTNING_MAX_DISTANCE_KM)} km dalla stazione", "high"),
            ("storm", "🌀", "Burrasca / crollo pressione", f"Pressione in calo di almeno {_fmt(s.PRESSURE_DROP_3H_THRESHOLD)} hPa in 3 ore", "urgent"),
            ("hail_warning", "🧊", "Rischio grandine", "Pioggia ≥ 40 mm/h, oppure ≥ 25 mm/h con fulmini entro 6 km e raffiche ≥ 35 km/h", "urgent"),
            ("rain", "🌊", "Nubifragio in corso", f"Intensità di pioggia ≥ {_fmt(s.RAIN_BURST_THRESHOLD_MM_HR)} mm/h", "urgent"),
            ("rain_heavy", "🌧️", "Pioggia intensa", f"Intensità di pioggia ≥ {_fmt(s.RAIN_RATE_ALERT_MM_HR)} mm/h", "normal"),
            ("rain_start", "🌦️", "Ha iniziato a piovere", "La stazione misura le prime gocce", "high"),
            ("rain_forecast", "☔", "Pioggia in arrivo", f"Nelle prossime 2 ore: probabilità ≥ {s.RAIN_FORECAST_PROB_THRESHOLD}% (almeno 0,2 mm) oppure ≥ 0,5 mm con probabilità ≥ 40%", "normal"),
            ("wind_spike", "💨", "Raffica anomala", f"Raffica ≥ {_fmt(s.GUST_SPIKE_THRESHOLD_KMH)} km/h", "high"),
            ("freeze", "❄️", "Gelo", f"Temperatura ≤ {_fmt(s.TEMP_FREEZE_THRESHOLD_C)} °C", "high"),
            ("heatwave", "🔥", "Caldo estremo", f"Temperatura ≥ {_fmt(s.TEMP_HEAT_THRESHOLD_C)} °C", "normal"),
            ("anomaly", "🌡️", "Sbalzo termico", f"Variazione di almeno {_fmt(s.TEMP_DROP_1H_THRESHOLD)} °C in un'ora (escluse alba e tramonto, salvo ≥ {_fmt(s.TEMP_EXTREME_CHANGE_THRESHOLD)} °C)", "normal"),
            ("uv_extreme", "☀️", "UV pericoloso", f"Indice UV ≥ {s.UV_EXTREME_THRESHOLD}", "normal"),
            ("record", "🏆", "Record battuto", "Nuovo record storico della stazione", "high"),
            ("digest", "☕", "Buongiorno meteo", "Ogni mattina alle 8: previsione del giorno e riepilogo della notte", "normal"),
        ]),
        ("Casa ed energia", [
            ("leak", "💦", "Perdita d'acqua", "Un sensore di allagamento rileva acqua", "urgent"),
            ("grid_overload_critical", "⚡", "Contatore sta per staccare", "Prelievo dalla rete ≥ 4,9 kW: spegne i climatizzatori accesi", "urgent"),
            ("grid_overload_warning", "🔌", "Prelievo alto dalla rete", "Prelievo dalla rete tra 4,5 e 4,9 kW", "high"),
            ("energy_high", "📈", "Consumo elevato", f"Consumi della casa ≥ {_fmt(s.ENERGY_HIGH_CONSUMPTION_W)} W", "normal"),
            ("battery_low", "🪫", "Batteria di casa scarica", f"Batteria Aton ≤ {_fmt(s.ENERGY_BATTERY_LOW_PCT)}%", "normal"),
            ("battery_full", "🔋", "Batteria di casa carica", f"Batteria Aton ≥ {_fmt(s.ENERGY_BATTERY_FULL_PCT)}%", "normal"),
            ("fridge_door_open", "🚪", "Porta del frigo aperta", "Porta aperta da più di 2 minuti (dato dal cloud LG)", "high"),
            ("fridge_door_away", "🚨", "Frigo aperto e sei uscito", "Il telefono risulta fuori casa con la porta del frigo aperta", "urgent"),
            ("washer_finish", "🧺", "Lavatrice finita", "Fine del programma, con consiglio per stendere", "normal"),
            ("climate_runtime_warning", "❄️", "Climatizzatore acceso da tanto", "Supera le ore impostate nella scheda Clima Smart", "normal"),
            ("climate_away_reminder", "🏃", "Clima acceso e sei uscito", "Climatizzatore acceso mentre sei fuori casa (azione scelta nella scheda Clima Smart)", "normal"),
        ]),
        ("Giardino e irrigazione", [
            ("soil_dry", "🌱", "Terreno secco", f"Umidità del suolo ≤ {_fmt(s.SOIL_MOISTURE_LOW_THRESHOLD)}%", "normal"),
            ("soil_wet", "💧", "Terreno saturo", f"Umidità del suolo ≥ {_fmt(s.SOIL_MOISTURE_HIGH_THRESHOLD)}%", "normal"),
            ("irrigation_auto_start", "🚿", "Irrigazione automatica", "Avvio e stop dell'irrigazione automatica, salti per pioggia o vento", "normal"),
            ("irrigation_frost_guard", "🧊", "Irrigazione bloccata per gelo", "Temperatura troppo bassa per irrigare", "high"),
            ("irrigation_close_failed", "🚰", "Valvola non si chiude", "La valvola dell'irrigazione non risponde al comando di chiusura", "urgent"),
        ]),
        ("Stazione", [
            ("offline", "📡", "Stazione offline", f"Nessun dato dalla stazione per più di {s.STATION_OFFLINE_TIMEOUT_MIN} minuti", "urgent"),
            ("battery_low_sensor", "🔋", "Pile dei sensori scariche", "Pile in esaurimento in uno dei sensori (WH65, WH57, WH51, WH31…)", "normal"),
        ]),
    ]
    # Alcuni allarmi condividono il tipo con altri: per la regola notturna conta il tipo reale
    real_type = {"rain_heavy": "rain", "battery_low_sensor": "battery_low"}
    out = []
    for name, rows in groups:
        items = []
        for key, icon, title, condition, prio in rows:
            items.append({
                "key": key, "icon": icon, "title": title, "condition": condition,
                "priority": prio, "priority_label": PRIORITY_LABELS[prio],
                "wakes_at_night": wakes_at_night(real_type.get(key, key), prio),
            })
        out.append({"name": name, "items": items})
    return out


def quiet_hours_info() -> Dict[str, Any]:
    return {
        "enabled": settings.QUIET_HOURS_ENABLED,
        "start": f"{settings.QUIET_HOURS_START:02d}:00",
        "end": f"{settings.QUIET_HOURS_END:02d}:00",
    }
