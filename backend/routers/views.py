import os
import asyncio
import hmac
import time
import json
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from backend.records_view import HISTORY_CATS, TITLES as REC_TITLES, build_monthly_view, build_records_view, format_day
from backend.alert_labels import ALERT_CATEGORIES, alert_icon, alert_label, build_alert_days
from backend.config import settings
from backend.forecast_service import forecast_service
from backend.civil_protection_service import civil_protection_service
from backend.aton_service import aton_service
from backend.thinq_service import thinq_service
from backend.homeassistant_service import homeassistant_service
from backend.weather_guide import build_weather_guide
from backend.alert_catalog import build_alert_catalog, quiet_hours_info
from backend.database import (
    get_latest_reading, get_station_status, get_pressure_trend, get_device_favorites,
    get_all_records, get_records_history, get_today_extremes,
    get_tropical_nights_stats, get_soil_moisture_summary,
    get_climate_comparisons, search_history, get_history_kpis,
    get_alert_logs, get_unread_alerts_count, get_alerts_stats,
    get_sensor_aliases, get_database_stats, get_today_energy_summary,
    get_latest_energy, get_climate_automations_config, get_irrigation_automations_config,
    get_tuya_local_devices, to_local_datetime_str,
    get_monthly_records, get_all_monthly_summaries,
    get_health_stats_summary, get_health_daily_history
)
from backend.analytics import (
    calc_apparent_temp, deg_to_compass, calc_current_weather_condition, calc_sun_ephemeris, wind_name
)
from backend.routers.weather import build_analytics_context
from backend.routers.devices import build_devices_catalog

logger = logging.getLogger("weather_hub")

router = APIRouter(tags=["UI Views"])

from backend.helpers import format_duration_italian, format_lightning_time_italian

# Inizializzazione Template Jinja2 e Filtri di Formattazione
templates_dir = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


def _js_literal(value) -> Markup:
    """Filtro Jinja `js`: serializza un valore come letterale JS sicuro dentro un attributo HTML (onclick=...)."""
    return escape(json.dumps(value, ensure_ascii=False))

templates.env.filters["js"] = _js_literal
templates.env.filters["alert_label"] = alert_label
templates.env.filters["day_it"] = format_day
templates.env.filters["alert_icon"] = alert_icon
templates.env.filters["localdt"] = lambda v, fmt="%d/%m/%Y %H:%M:%S": to_local_datetime_str(v, fmt) if v else ""

templates.env.filters["local_dt"] = lambda val: to_local_datetime_str(val, "%d/%m/%Y %H:%M:%S")
templates.env.filters["local_dt_short"] = lambda val: to_local_datetime_str(val, "%d/%m/%Y %H:%M")
templates.env.filters["local_date"] = lambda val: to_local_datetime_str(val, "%d/%m/%Y")
# Versione unica di CSS/JS per tutte le pagine (base, login, kiosk): cambiarla forza il ricaricamento
ASSET_VERSION = "7.4"
templates.env.globals["asset_version"] = ASSET_VERSION
templates.env.filters["local_time"] = lambda val: to_local_datetime_str(val, "%H:%M")
templates.env.filters["duration_it"] = lambda val: format_duration_italian(val) if val is not None else "--"
templates.env.filters["lightning_time_it"] = lambda val: format_lightning_time_italian(val)


# ----------------- AUTHENTICATION ROUTES -----------------

def _safe_next_url(next_url: Optional[str]) -> str:
    """Accetta solo percorsi relativi interni (es. /devices), mai URL esterni o //host."""
    if not next_url or not next_url.startswith("/") or next_url.startswith("//") or "\\" in next_url:
        return "/"
    return next_url

# Rate limit semplice per IP sui tentativi di login falliti
_LOGIN_FAILURES: Dict[str, List[float]] = {}
LOGIN_MAX_FAILURES = 10
LOGIN_WINDOW_SEC = 900

def _client_ip(request: Request) -> str:
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: Optional[str] = "/"):
    next_url = _safe_next_url(next)
    cookie_token = request.cookies.get(settings.AUTH_COOKIE_NAME) or ""
    if not settings.AUTH_TOKEN or hmac.compare_digest(cookie_token, settings.AUTH_TOKEN):
        return RedirectResponse(url=next_url, status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"next_url": next_url, "error": None}
    )

@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request):
    form = await request.form()
    token = str(form.get("token") or "").strip()
    next_url = _safe_next_url(str(form.get("next", "/") or "/"))

    ip = _client_ip(request)
    now = time.time()
    recent = [t for t in _LOGIN_FAILURES.get(ip, []) if now - t < LOGIN_WINDOW_SEC]
    if len(recent) >= LOGIN_MAX_FAILURES:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"next_url": next_url, "error": "Troppi tentativi falliti. Riprova tra qualche minuto."},
            status_code=429
        )

    if settings.AUTH_TOKEN and hmac.compare_digest(token, settings.AUTH_TOKEN):
        _LOGIN_FAILURES.pop(ip, None)
        response = RedirectResponse(url=next_url, status_code=303)
        response.set_cookie(
            key=settings.AUTH_COOKIE_NAME,
            value=settings.AUTH_TOKEN,
            max_age=315360000,  # 10 anni
            path="/",
            httponly=True,
            samesite="lax"
        )
        return response
    recent.append(now)
    _LOGIN_FAILURES[ip] = recent
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"next_url": next_url, "error": "Chiave di sicurezza non valida. Riprova."}
    )

@router.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key=settings.AUTH_COOKIE_NAME, path="/")
    return response

# ----------------- HTML PAGE ROUTES -----------------

def build_climate_comparison(analytics: dict, forecast_data: Optional[dict]) -> Optional[dict]:
    """Oggi, mese e anno rispetto alle medie 1991–2020 (None finché le medie non sono scaricate)."""
    from backend.climate_service import climate_service, station_month_days, station_data_since
    try:
        rain = (analytics or {}).get("rain_totals") or {}
        today_fc = ((forecast_data or {}).get("daily") or [None])[0]
        return climate_service.build_comparison(
            (analytics or {}).get("today_extremes") or {}, today_fc, station_month_days(),
            rain.get("month_rain_mm"), rain.get("year_rain_mm"), station_data_since())
    except Exception as e:
        logger.warning(f"Confronto con la media non disponibile: {e}")
        return None


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    latest = get_latest_reading() or {}
    raw = {}
    if latest.get("raw_data_json"):
        try:
            raw = json.loads(latest["raw_data_json"])
        except Exception:
            raw = {}
            
    station_model = raw.get("model", raw.get("stationtype", "Sainlogic / Ecowitt"))
    batt_wh65 = "🟢 Buona / OK" if raw.get("wh65batt") == "0" else ("🔴 Bassa" if raw.get("wh65batt") else "N/D")
    
    wind_deg = latest.get("wind_dir_deg") if latest.get("wind_dir_deg") is not None else raw.get("winddir")
    wind_dir_text = deg_to_compass(wind_deg)
    wind_info = wind_name(wind_deg, latest.get("wind_speed_kmh"))
    
    status_info = get_station_status()
    pressure_trend = latest.get("pressure_trend") or get_pressure_trend(latest.get("pressure_rel_hpa"))
    apparent_temp = latest.get("apparent_temp_c") or calc_apparent_temp(latest.get("temp_c"), latest.get("humidity"), latest.get("wind_speed_kmh"))
    
    all_records = get_all_records()
    top_records = [r for r in all_records if r["record_key"] in ("temp_max", "temp_min", "wind_gust_max", "rain_daily_max", "pressure_min")][:4]

    # Analisi avanzate & Nowcasting
    analytics = build_analytics_context(latest)
    forecast_data = await asyncio.to_thread(forecast_service.fetch_open_meteo)
    forecast_data = forecast_service.apply_station_observation(forecast_data, latest)
    from backend.marine_service import marine_service
    marine_data = await asyncio.to_thread(marine_service.fetch, False, latest)
    cross_check = forecast_service.build_cross_check_summary(latest)
    climate_cmp = await asyncio.to_thread(build_climate_comparison, analytics, forecast_data)

    # Dati Energetici Aton Storage
    energy_latest = aton_service.latest_data or get_latest_energy() or {}
    energy_summary = get_today_energy_summary()

    # Dati Smart Home & Elettrodomestici (Home Assistant Locale)
    if homeassistant_service.enabled and not homeassistant_service.entities:
        try:
            await homeassistant_service.fetch_states()
        except Exception:
            pass
    ha_summary = homeassistant_service.get_summary(energy_latest, analytics.get("drying_index") if analytics else None)
    health_data = ha_summary.get("health", {})
    health_stats = get_health_stats_summary()

    # Dati Climatizzazione (Fujitsu FGLair, LG ThinQ)
    climate_devs = []
    seen_climate_ids = set()
    if settings.HASS_ENABLED and homeassistant_service.enabled:
        for cd in homeassistant_service.parse_climate_data():
            if cd.get("device_type") == "DEVICE_AIR_CONDITIONER":
                climate_devs.append(cd)
                seen_climate_ids.add(cd.get("device_id"))
    if settings.LG_THINQ_ENABLED:
        for cd in thinq_service.get_cached_devices():
            if cd.get("device_id") not in seen_climate_ids and not any(k in (cd.get("alias") or "").lower() for k in ("camera", "cameretta") if any(k in s for s in seen_climate_ids)):
                climate_devs.append(cd)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "active_page": "dashboard",
            "title": "Domus",
            "latest": latest,
            "station_model": station_model,
            "batt_wh65": batt_wh65,
            "wind_dir_text": wind_dir_text,
            "wind_info": wind_info,
            "marine": marine_data,
            "wind_deg": wind_deg,
            "status_info": status_info,
            "pressure_trend": pressure_trend,
            "apparent_temp": apparent_temp,
            "soil_moisture": latest.get("soil_moisture", {}),
            "top_records": top_records,
            "analytics": analytics,
            "forecast": forecast_data,
            "cross_check": cross_check,
            "energy_latest": energy_latest,
            "energy_summary": energy_summary,
            "aton_enabled": settings.ATON_ENABLED,
            "aton_sn": settings.ATON_SN,
            "thinq_enabled": bool(settings.LG_THINQ_ENABLED or climate_devs),
            "thinq_connected": bool(homeassistant_service.is_connected or thinq_service.is_connected),
            "climate_devices": climate_devs,
            "smartthings": ha_summary,
            "smartthings_enabled": True,
            "tuya": ha_summary,
            "tuya_enabled": True,
            "health": health_data,
            "health_stats": health_stats,
            "health_enabled": bool(health_data.get("is_available")),
            "hass_enabled": settings.HASS_ENABLED,
            "sensor_aliases": get_sensor_aliases(),
            "db_stats": get_database_stats(),
            "civil_protection": (await asyncio.to_thread(civil_protection_service.fetch_alerts)) if settings.CIVIL_PROTECTION_ENABLED else None,
            "civil_protection_enabled": settings.CIVIL_PROTECTION_ENABLED,
            "ntfy_topic": settings.NTFY_TOPIC,
            "weather_guide": build_weather_guide(),
            "climate_cmp": climate_cmp,
        }
    )

@router.get("/devices", response_class=HTMLResponse)
def devices_page(request: Request):
    catalog = build_devices_catalog()
    return templates.TemplateResponse(
        request=request,
        name="devices.html",
        context={
            "active_page": "devices",
            "title": "Dispositivi & Smart Home • Domus",
            "devices": catalog.get("devices", []),
            "stats": catalog.get("stats", {}),
            "active_schedules": catalog.get("active_schedules", []),
            "favorites": get_device_favorites(),
            "tuya_enabled": settings.TUYA_ENABLED,
            "thinq_enabled": settings.LG_THINQ_ENABLED,
            "smartthings_enabled": settings.SMARTTHINGS_ENABLED,
            "aton_enabled": settings.ATON_ENABLED
        }
    )

@router.get("/telecomando", response_class=HTMLResponse)
def remote_page(request: Request):
    """Telecomando della TV a schermo intero (scorciatoia dall'icona dell'app)."""
    return templates.TemplateResponse(
        request=request,
        name="telecomando.html",
        context={"active_page": "telecomando", "title": "Telecomando • Domus"},
    )

@router.get("/records", response_class=HTMLResponse)
def records_page(request: Request):
    records = get_all_records()
    history = get_records_history(limit=100)
    tropical_stats = get_tropical_nights_stats()
    soil_summary = get_soil_moisture_summary()
    climate_stats = get_climate_comparisons()
    today_extremes = get_today_extremes()
    monthly_records = get_monthly_records()
    monthly_summaries = get_all_monthly_summaries(limit=36)
    available_years = sorted(list({ms["year"] for ms in monthly_summaries if ms.get("year")}), reverse=True)
    return templates.TemplateResponse(
        request=request,
        name="records.html",
        context={
            "active_page": "records",
            "title": "Record • Domus",
            "records": records,
            "rv": build_records_view(records, history, settings.get_tz()),
            "mv": build_monthly_view(monthly_records),
            "rec_titles": REC_TITLES, "hist_cats": HISTORY_CATS,
            "history": history,
            "tropical_stats": tropical_stats,
            "soil_summary": soil_summary,
            "climate_stats": climate_stats,
            "today_extremes": today_extremes,
            "monthly_records": monthly_records,
            "monthly_summaries": monthly_summaries,
            "available_years": available_years
        }
    )

@router.get("/radar", response_class=HTMLResponse)
def radar_page(request: Request):
    latest = get_latest_reading() or {}
    temp_c = latest.get("temp_c")
    rain_rate = latest.get("rain_rate_mm_hr", 0.0) or 0.0
    analytics = build_analytics_context(latest)
    current_cond = analytics.get("current_condition") or calc_current_weather_condition(
        temp_c=temp_c,
        humidity=latest.get("humidity"),
        dew_point_c=latest.get("dew_point_c"),
        rain_rate=rain_rate,
        solar_rad=latest.get("solar_radiation"),
        uv_index=latest.get("uv_index"),
        wind_spd=latest.get("wind_speed_kmh"),
        wind_gust=latest.get("wind_gust_kmh"),
        lightning_dist=latest.get("lightning_distance_km"),
        sun_ephemeris=calc_sun_ephemeris(settings.LATITUDE, settings.LONGITUDE)
    )
    return templates.TemplateResponse(
        request=request,
        name="radar.html",
        context={
            "active_page": "radar",
            "title": "Radar Pioggia Live • Domus",
            "lat": settings.LATITUDE,
            "lon": settings.LONGITUDE,
            "station_name": settings.STATION_NAME,
            "location_name": settings.LOCATION_NAME,
            "temp_c": temp_c,
            "rain_rate": rain_rate,
            "current_cond": current_cond,
            "analytics": analytics,
            "lightning": analytics.get("lightning")
        }
    )


@router.get("/kiosk", response_class=HTMLResponse)
def kiosk_page(request: Request):
    latest = get_latest_reading() or {}
    analytics = build_analytics_context(latest)
    forecast_data = forecast_service.apply_station_observation(forecast_service.fetch_open_meteo(), latest)
    pressure_trend = latest.get("pressure_trend") or get_pressure_trend(latest.get("pressure_rel_hpa"))
    apparent_temp = latest.get("apparent_temp_c") or calc_apparent_temp(latest.get("temp_c"), latest.get("humidity"), latest.get("wind_speed_kmh"))
    today_ext = analytics.get("today_extremes") or get_today_extremes()
    kiosk_wind = wind_name(latest.get("wind_dir_deg"), latest.get("wind_speed_kmh")) if latest else None

    return templates.TemplateResponse(
        request=request,
        name="kiosk.html",
        context={
            "active_page": "kiosk",
            "title": "Kiosk meteo • Domus",
            "latest": latest,
            "station_name": settings.STATION_NAME,
            "location_name": settings.LOCATION_NAME,
            "apparent_temp": apparent_temp,
            "pressure_trend": pressure_trend,
            "analytics": analytics,
            "today_extremes": today_ext,
            "forecast": forecast_data,
            "wind_name": (kiosk_wind or {}).get("name") if isinstance(kiosk_wind, dict) else kiosk_wind,
            "lat": settings.LATITUDE,
            "lon": settings.LONGITUDE
        }
    )

@router.get("/charts", response_class=HTMLResponse)
def charts_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="charts.html",
        context={
            "active_page": "charts",
            "title": "Grafici & Trend • Domus"
        }
    )

@router.get("/history", response_class=HTMLResponse)
def history_page(request: Request, start_date: Optional[str] = None, end_date: Optional[str] = None, page: int = 1):
    limit = 25
    offset = (page - 1) * limit
    records, total_count = search_history(start_date=start_date, end_date=end_date, limit=limit, offset=offset)
    kpis = get_history_kpis(start_date=start_date, end_date=end_date)
    max_pages = max(1, (total_count + limit - 1) // limit)
    
    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            "active_page": "history",
            "title": "Archivio & Ricerche • Domus",
            "records": records,
            "total_count": total_count,
            "page": page,
            "max_pages": max_pages,
            "start_date": start_date,
            "end_date": end_date,
            "kpis": kpis
        }
    )

@router.get("/alerts-page", response_class=HTMLResponse)
def alerts_page(request: Request):
    alerts = get_alert_logs(limit=400)
    unread_count = get_unread_alerts_count()
    days = build_alert_days(alerts, settings.get_tz())
    used = {e["category"] for d in days for e in d["entries"]}
    return templates.TemplateResponse(
        request=request,
        name="alerts.html",
        context={
            "active_page": "alerts",
            "title": "Notifiche • Domus",
            "days": days,
            "has_alerts": bool(alerts),
            "categories": [c for c in ALERT_CATEGORIES if c[0] in used],
            "unread_count": unread_count,
            "civil_protection": civil_protection_service.fetch_alerts() if settings.CIVIL_PROTECTION_ENABLED else None,
            "civil_protection_enabled": settings.CIVIL_PROTECTION_ENABLED,
        }
    )

def get_detected_sensors(raw: Dict[str, Any], soil_moisture: Dict[str, Any], saved_aliases: Dict[str, str]) -> List[Dict[str, Any]]:
    """Restituisce solo i sensori opzionali/aggiuntivi effettivamente rilevati o con alias salvato."""
    sensors = []

    # 1. Sensore Interno Gateway / Console (tempin)
    if ("tempinf" in raw and raw.get("tempinf") != "") or "temp_in" in saved_aliases:
        t_in = raw.get("tempinf")
        sensors.append({
            "key": "temp_in",
            "icon": "🏠",
            "type_label": "Sensore Interno Gateway",
            "channel_label": "Interno",
            "current_val": f"{t_in}°F" if t_in is not None else None,
            "alias": saved_aliases.get("temp_in", "")
        })

    # 2. Sensori Umidità Suolo (WH51, ch1..ch8)
    for i in range(1, 9):
        ch_key = f"ch{i}"
        raw_key = f"soilmoisture{i}"
        key = f"soil_ch{i}"
        val = soil_moisture.get(ch_key)
        if val is not None or (raw_key in raw and raw.get(raw_key) != "") or key in saved_aliases:
            curr = f"{val}%" if val is not None else (f"{raw.get(raw_key)}%" if raw.get(raw_key) is not None else None)
            sensors.append({
                "key": key,
                "icon": "🌱",
                "type_label": "Sensore Umidità Suolo",
                "channel_label": f"Canale {i}",
                "current_val": curr,
                "alias": saved_aliases.get(key, "")
            })

    # 3. Termometri / Igrometri Multi-Canale (WH31, ch1..ch8)
    for i in range(1, 9):
        raw_t = f"temp{i}f"
        key = f"temp_ch{i}"
        if (raw_t in raw and raw.get(raw_t) != "") or key in saved_aliases:
            t_val = raw.get(raw_t)
            sensors.append({
                "key": key,
                "icon": "🌡️",
                "type_label": "Termo-Igrometro Extra",
                "channel_label": f"Canale {i}",
                "current_val": f"{t_val}°F" if t_val is not None else None,
                "alias": saved_aliases.get(key, "")
            })

    # 4. Sonde di Temperatura ad Immersione (WN34, tf_ch1..tf_ch8)
    for i in range(1, 9):
        raw_tf = f"tf_ch{i}"
        key = f"tf_ch{i}"
        if (raw_tf in raw and raw.get(raw_tf) != "") or key in saved_aliases:
            tf_val = raw.get(raw_tf)
            sensors.append({
                "key": key,
                "icon": "🧪",
                "type_label": "Sonda Temperatura",
                "channel_label": f"Canale {i}",
                "current_val": f"{tf_val}°F" if tf_val is not None else None,
                "alias": saved_aliases.get(key, "")
            })

    # 5. Rilevatori Perdite d'Acqua / Allagamento (WH55, leak_ch1..leak_ch4)
    for i in range(1, 5):
        raw_leak = f"leak_ch{i}"
        key = f"leak_ch{i}"
        if (raw_leak in raw and raw.get(raw_leak) != "") or key in saved_aliases:
            leak_val = raw.get(raw_leak)
            status_text = "Allarme Perdita! 🚨" if str(leak_val) == "1" else "Normale / Asciutto 🟢"
            sensors.append({
                "key": key,
                "icon": "💧",
                "type_label": "Rilevatore Allagamento",
                "channel_label": f"Canale {i}",
                "current_val": status_text if leak_val is not None else None,
                "alias": saved_aliases.get(key, "")
            })

    # 6. Qualità dell'Aria (PM2.5 / PM10 / CO2)
    for i in range(1, 5):
        raw_pm = f"pm25_ch{i}"
        key = f"pm25_ch{i}"
        if (raw_pm in raw and raw.get(raw_pm) != "") or key in saved_aliases:
            pm_val = raw.get(raw_pm)
            sensors.append({
                "key": key,
                "icon": "🌫️",
                "type_label": "Sensore PM2.5",
                "channel_label": f"Canale {i}",
                "current_val": f"{pm_val} µg/m³" if pm_val is not None else None,
                "alias": saved_aliases.get(key, "")
            })

    if ("co2" in raw and raw.get("co2") != "") or "co2" in saved_aliases:
        co2_val = raw.get("co2")
        sensors.append({
            "key": "co2",
            "icon": "🫧",
            "type_label": "Sensore CO2",
            "channel_label": "Ambiente",
            "current_val": f"{co2_val} ppm" if co2_val is not None else None,
            "alias": saved_aliases.get("co2", "")
        })

    return sensors

@router.get("/more", response_class=HTMLResponse)
def more_page(request: Request):
    """Menu "Altro": raccoglie le sezioni secondarie per mantenere semplice la navigazione principale."""
    return templates.TemplateResponse(
        request=request,
        name="more.html",
        context={
            "active_page": "more",
            "title": "Altro • Domus",
            "station_name": settings.STATION_NAME,
        }
    )

def forecast_models_label() -> str:
    """Nomi leggibili dei modelli di previsione configurati (es. "DWD ICON + ECMWF IFS 0,25°")."""
    from backend.forecast_service import MODEL_LABELS
    models = [m.strip() for m in str(getattr(settings, "FORECAST_MODELS", "") or "").split(",") if m.strip()]
    return " + ".join(MODEL_LABELS.get(m, m) for m in models) or "Open-Meteo"


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    latest = get_latest_reading() or {}
    raw = {}
    if latest.get("raw_data_json"):
        try:
            raw = json.loads(latest["raw_data_json"])
        except Exception:
            raw = {}
    station_model = raw.get("model", raw.get("stationtype", "Sainlogic / Ecowitt"))
    batt_wh65 = "🟢 Buona / OK" if raw.get("wh65batt") == "0" else ("🔴 Bassa" if raw.get("wh65batt") else "N/D")
    aliases = get_sensor_aliases()
    soil_moist = latest.get("soil_moisture") or {}
    detected_sensors = get_detected_sensors(raw, soil_moist, aliases)
    ha_sum = homeassistant_service.get_summary()
    climate_cfg = get_climate_automations_config()
    climate_devs = thinq_service.get_cached_devices() if settings.LG_THINQ_ENABLED else []
    tuya_local_devs = get_tuya_local_devices()
    alert_catalog = build_alert_catalog()
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "active_page": "settings",
            "title": "Impostazioni & Sistema • Domus",
            "station_model": station_model,
            "batt_wh65": batt_wh65,
            "aton_sn": settings.ATON_SN,
            "aton_enabled": settings.ATON_ENABLED,
            "thinq_enabled": settings.LG_THINQ_ENABLED,
            "climate_config": climate_cfg,
            "climate_devices": climate_devs,
            "irrigation_config": get_irrigation_automations_config(),
            "smartthings_enabled": True,
            "tuya_enabled": True,
            "tuya_summary": ha_sum,
            "tuya_devices": homeassistant_service.get_catalog_devices(),
            "tuya_local_devices": tuya_local_devs,
            "hass_enabled": settings.HASS_ENABLED,
            "hass_url": settings.HASS_URL,
            "hass_has_token": bool(settings.HASS_TOKEN),
            "sensor_aliases": aliases,
            "detected_sensors": detected_sensors,
            "db_stats": get_database_stats(),
            "ntfy_topic": settings.NTFY_TOPIC,
            "alert_catalog": alert_catalog,
            "alert_catalog_count": sum(len(g["items"]) for g in alert_catalog),
            "quiet_hours": quiet_hours_info(),
            "forecast_models_label": forecast_models_label(),
        }
    )
