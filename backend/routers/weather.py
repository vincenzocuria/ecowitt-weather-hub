import io
import csv
import time
import logging
from typing import Optional, Dict, Any, List, Tuple
from fastapi import APIRouter, Request, BackgroundTasks, Query
from fastapi.responses import JSONResponse, Response

# Cache in memoria per statistiche climatologiche pesanti per /api/live (TTL 5 minuti)
_analytics_cache: Dict[str, Tuple[float, Any]] = {}

def _get_cached_analytics(key: str, ttl_sec: float = 300) -> Optional[Any]:
    now = time.time()
    if key in _analytics_cache:
        ts, val = _analytics_cache[key]
        if (now - ts) < ttl_sec:
            return val
    return None

def _set_cached_analytics(key: str, val: Any):
    _analytics_cache[key] = (time.time(), val)

from backend.config import settings
from backend.ecowitt_parser import parse_ecowitt_payload
from backend.alert_engine import engine
from backend.database import (
    save_reading, get_latest_reading, get_all_records, get_records_history,
    get_timeseries, search_history, get_history_kpis, get_alert_logs,
    get_station_status, get_pressure_trend,
    get_today_extremes, get_yesterday_same_time, get_recent_rain_totals, get_climate_comparisons,
    get_sensor_aliases, get_tropical_nights_stats, get_soil_moisture_summary,
    get_irrigation_automations_config, get_latest_energy,
    get_monthly_records, get_all_monthly_summaries, get_monthly_summary_by_key,
    calculate_monthly_summary, save_monthly_summary, rebuild_all_historical_monthly_summaries
)
from backend.analytics import (
    calc_zambretti_forecast, abs_to_rel_pressure, evaluate_window_ventilation, evaluate_laundry_index,
    calc_humidex, evaluate_outdoor_activity, calc_sun_ephemeris, calc_moon_phase,
    calc_beaufort_scale, evaluate_indoor_comfort, calc_current_weather_condition,
    calc_evapotranspiration, evaluate_smart_irrigation, generate_now_highlights,
    calc_dew_point, calc_apparent_temp, deg_to_compass
)
from backend.forecast_service import forecast_service
from backend.civil_protection_service import civil_protection_service
from backend.aton_service import aton_service
from backend.thinq_service import thinq_service
from backend.homeassistant_service import homeassistant_service

logger = logging.getLogger("weather_hub")

router = APIRouter(tags=["Weather & Analytics"])

def process_weather_data(raw_data: dict):
    try:
        parsed = parse_ecowitt_payload(raw_data)
        record_id = save_reading(parsed)
        logger.info(f"Salvata lettura ID {record_id} da {parsed.get('station_model')} ({parsed.get('timestamp')})")
        engine.evaluate(parsed)
    except Exception as e:
        logger.error(f"Errore durante l'elaborazione dei dati meteo: {e}", exc_info=True)

def build_analytics_context(latest: dict) -> dict:
    """Costruisce il set completo di analisi intelligenti per la dashboard e le API."""
    temp_c = latest.get("temp_c")
    hum = latest.get("humidity")
    wind_spd = latest.get("wind_speed_kmh")
    wind_gst = latest.get("wind_gust_kmh")
    wind_deg = latest.get("wind_dir_deg")
    press = latest.get("pressure_rel_hpa") or abs_to_rel_pressure(latest.get("pressure_abs_hpa"), settings.ELEVATION, temp_c)
    rain_rate = latest.get("rain_rate_mm_hr")
    solar = latest.get("solar_radiation")
    uv = latest.get("uv_index")
    dew_point = latest.get("dew_point_c") or calc_dew_point(temp_c, hum)
    
    temp_in = latest.get("temp_in_c")
    hum_in = latest.get("humidity_in")

    press_trend = latest.get("pressure_trend") or get_pressure_trend(press)
    zambretti = calc_zambretti_forecast(press, press_trend.get("diff"), wind_deg)
    
    # 1. Qualità dell'Aria & Pollini CAMS
    air_quality = forecast_service.fetch_air_quality()

    # 2. Finestre con incrocio termico e Qualità Aria
    window_advice = evaluate_window_ventilation(temp_c, hum, temp_in, hum_in, rain_rate, air_quality=air_quality)
    laundry_advice = evaluate_laundry_index(temp_c, hum, wind_spd, solar, rain_rate)
    humidex_info = calc_humidex(temp_c, dew_point)
    outdoor_advice = evaluate_outdoor_activity(
        temp_c=temp_c,
        wind_gust_kmh=wind_gst,
        rain_rate=rain_rate,
        uv_index=uv,
        humidex_val=humidex_info.get("value"),
        lightning_dist=latest.get("lightning_distance_km")
    )
    indoor_comfort = evaluate_indoor_comfort(temp_in, hum_in, temp_c)
    dew_point_in = calc_dew_point(temp_in, hum_in)

    today_ext = get_today_extremes()
    yesterday_cmp = get_yesterday_same_time(temp_c)
    rain_totals = get_recent_rain_totals()
    climate_comparisons = _get_cached_analytics("climate_comparisons", ttl_sec=300)
    if climate_comparisons is None:
        climate_comparisons = get_climate_comparisons()
        _set_cached_analytics("climate_comparisons", climate_comparisons)

    # 3. Evapotraspirazione & Irrigazione Intelligente WH51
    et_mm = calc_evapotranspiration(temp_c, hum, solar, wind_spd, today_ext.get("temp_min"), today_ext.get("temp_max"))
    soil_ch1 = (latest.get("soil_moisture") or {}).get("ch1") or latest.get("soil_moisture_ch1")
    irr_cfg = get_irrigation_automations_config()
    smart_irrigation = evaluate_smart_irrigation(
        soil_moisture_pct=soil_ch1,
        temp_c=temp_c,
        solar_rad=solar,
        rain_forecast_24h_mm=0.0,
        recent_rain_48h_mm=rain_totals.get("week_rain_mm", 0.0),
        et_mm=et_mm,
        dry_threshold=float(irr_cfg.get("soil_dry_threshold", 48.0)),
        target_threshold=float(irr_cfg.get("soil_target_threshold", 75.0)),
        crop_label=str(irr_cfg.get("crop_label", "Aiuola Orto: Pomodori & Zucchine 🍅🥒"))
    )

    # 4. Solar Forecast & Nowcasting
    aton_curr = aton_service.latest_data or get_latest_energy() or {}
    solar_forecast = forecast_service.fetch_solar_forecast(aton_data=aton_curr)
    rain_nowcast = forecast_service.build_rain_nowcasting_summary(latest)

    sun_info = calc_sun_ephemeris(settings.LATITUDE, settings.LONGITUDE)
    moon_info = calc_moon_phase()
    cross_check = forecast_service.build_cross_check_summary(latest)
    beaufort = calc_beaufort_scale(wind_spd)
    
    current_cond = calc_current_weather_condition(
        temp_c=temp_c,
        humidity=hum,
        dew_point_c=dew_point,
        rain_rate=rain_rate,
        solar_rad=solar,
        uv_index=uv,
        wind_spd=wind_spd,
        wind_gust=wind_gst,
        lightning_dist=latest.get("lightning_distance_km"),
        sun_ephemeris=sun_info,
        zambretti=zambretti
    )

    tropical_nights = _get_cached_analytics("tropical_nights", ttl_sec=300)
    if tropical_nights is None:
        tropical_nights = get_tropical_nights_stats()
        _set_cached_analytics("tropical_nights", tropical_nights)
    soil_summary = get_soil_moisture_summary()

    ctx = {
        "current_condition": current_cond,
        "zambretti": zambretti,
        "comfort": {
            "window": window_advice,
            "laundry": laundry_advice,
            "humidex": humidex_info,
            "outdoor": outdoor_advice,
            "indoor": indoor_comfort
        },
        "today_extremes": today_ext,
        "yesterday_comparison": yesterday_cmp,
        "rain_totals": rain_totals,
        "climate_comparisons": climate_comparisons,
        "tropical_nights": tropical_nights,
        "soil_summary": soil_summary,
        "evapotranspiration_mm": et_mm,
        "irrigation_advice": smart_irrigation,
        "air_quality": air_quality,
        "solar_forecast": solar_forecast,
        "rain_nowcast": rain_nowcast,
        "sun_ephemeris": sun_info,
        "moon_phase": moon_info,
        "dew_point_c": dew_point,
        "dew_point_in_c": dew_point_in,
        "cross_check": cross_check,
        "beaufort": beaufort
    }

    # 5. Generazione Pillole Dinamiche "Cosa devo sapere ora"
    ctx["now_highlights"] = generate_now_highlights(latest, ctx, air_quality, solar_forecast, rain_nowcast, aton_data=aton_curr)

    return ctx

# ----------------- API ENDPOINTS -----------------

@router.post("/api/ecowitt")
@router.get("/api/ecowitt")
async def ingest_ecowitt(request: Request, bg: BackgroundTasks):
    try:
        form = await request.form()
        data = dict(form) or dict(request.query_params)
    except Exception:
        data = dict(request.query_params)
        
    # Validazione PASSKEY opzionale di sicurezza
    if settings.ECOWITT_STATION_PASSKEY:
        incoming_passkey = data.get("PASSKEY", "")
        if incoming_passkey != settings.ECOWITT_STATION_PASSKEY:
            logger.warning(f"Ricevuto payload con PASSKEY non autorizzata: {incoming_passkey}")
            return JSONResponse({"status": "error", "message": "Invalid PASSKEY"}, status_code=403)

    logger.info(f"Ricevuto payload da Stazione (PASSKEY: {data.get('PASSKEY', 'N/D')})")
    bg.add_task(process_weather_data, data)
    return {"status": "success"}

@router.get("/api/forecast")
async def api_forecast():
    latest = get_latest_reading() or {}
    forecast_data = forecast_service.fetch_open_meteo()
    cross_check = forecast_service.build_cross_check_summary(latest)
    return {
        "forecast": forecast_data,
        "cross_check": cross_check
    }

@router.get("/api/civil-protection")
@router.get("/api/civil_protection")
async def api_civil_protection(refresh: bool = False):
    """Restituisce lo stato delle allerte meteo ufficiali della Protezione Civile per oggi e domani."""
    return civil_protection_service.fetch_alerts(force_refresh=refresh)

@router.post("/api/civil-protection/refresh")
@router.post("/api/civil_protection/refresh")
async def api_civil_protection_refresh():
    """Forza il download e l'aggiornamento del bollettino della Protezione Civile."""
    return civil_protection_service.fetch_alerts(force_refresh=True)

@router.get("/api/air-quality")
async def api_air_quality():
    return forecast_service.fetch_air_quality()

@router.get("/api/solar-forecast")
async def api_solar_forecast():
    aton_curr = aton_service.latest_data or get_latest_energy() or {}
    return forecast_service.fetch_solar_forecast(aton_data=aton_curr)

@router.get("/api/climate-summary")
async def api_climate_summary():
    return get_climate_comparisons()

@router.get("/api/now-highlights")
async def api_now_highlights():
    latest = get_latest_reading() or {}
    analytics_ctx = build_analytics_context(latest)
    return {"highlights": analytics_ctx.get("now_highlights", [])}

@router.get("/api/status")
async def api_status():
    return get_station_status()

@router.get("/api/analytics")
async def api_analytics():
    latest = get_latest_reading() or {}
    return build_analytics_context(latest)

@router.get("/api/live")
async def api_live():
    latest = get_latest_reading()
    if not latest:
        return {"message": "In attesa dei primi dati dalla stazione meteo", "status_info": get_station_status()}
    
    # Sanitizzazione rigorosa: rimuove payload raw, MAC, PASSKEY, credenziali e token
    clean_latest = dict(latest)
    clean_latest.pop("raw_data_json", None)
    clean_latest.pop("raw_payload", None)
    clean_latest.pop("station_mac", None)
    clean_latest.pop("PASSKEY", None)
    clean_latest.pop("stationtype", None)

    status_info = get_station_status()
    clean_latest["status_info"] = status_info
    analytics_ctx = build_analytics_context(latest)
    clean_latest["analytics"] = analytics_ctx
    clean_latest["sensor_aliases"] = get_sensor_aliases()
    clean_latest["climate_devices"] = thinq_service.get_cached_devices()
    clean_latest["thinq_enabled"] = settings.LG_THINQ_ENABLED
    clean_latest["thinq_connected"] = thinq_service.is_connected
    ha_sum = homeassistant_service.get_summary(
        aton_service.latest_data or get_latest_energy() or {},
        analytics_ctx.get("drying_index") if analytics_ctx else None
    )
    clean_latest["smartthings"] = ha_sum
    clean_latest["smartthings_enabled"] = True
    clean_latest["tuya"] = ha_sum
    clean_latest["tuya_enabled"] = True
    clean_latest["health"] = ha_sum.get("health") or homeassistant_service.parse_health_data()
    clean_latest["health_enabled"] = bool(clean_latest["health"].get("is_available"))
    clean_latest["hass_enabled"] = settings.HASS_ENABLED
    if settings.CIVIL_PROTECTION_ENABLED:
        clean_latest["civil_protection"] = civil_protection_service.fetch_alerts()
    return clean_latest

@router.get("/api/records")
async def api_records():
    return {"records": get_all_records()}

@router.get("/api/records/history")
async def api_records_history(record_key: Optional[str] = None, limit: int = 50):
    return {"history": get_records_history(record_key=record_key, limit=limit)}

@router.get("/api/history")
async def api_history(period: str = "24h"):
    return get_timeseries(period=period)

@router.get("/api/search")
async def api_search(start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100, page: int = 1):
    offset = (page - 1) * limit
    records, total = search_history(start_date=start_date, end_date=end_date, limit=limit, offset=offset)
    return {"records": records, "total": total, "page": page, "limit": limit}

@router.get("/api/search/kpis")
async def api_search_kpis(start_date: Optional[str] = None, end_date: Optional[str] = None):
    return get_history_kpis(start_date=start_date, end_date=end_date)

@router.get("/api/climate/tropical-nights")
async def api_climate_tropical_nights(year: Optional[int] = None):
    """Restituisce le statistiche climatologiche delle notti tropicali e roventi."""
    return get_tropical_nights_stats(year=year)

@router.get("/api/soil/summary")
async def api_soil_summary():
    """Restituisce lo stato, trend e salute dei sensori di umidità del suolo WH51."""
    return get_soil_moisture_summary()

@router.get("/api/export/csv")
async def api_export_csv(start_date: Optional[str] = None, end_date: Optional[str] = None):
    """Esporta le letture storiche meteo in CSV (apribile direttamente in Excel)."""
    records, _ = search_history(start_date=start_date, end_date=end_date, limit=50000, offset=0)
    output = io.StringIO()
    # Usa delimitatore punto e virgola e BOM UTF-8 per compatibilità nativa perfetta con Excel in italiano
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        "ID", "Data e Ora (UTC)", "Temperatura Esterna (°C)", "Umidità Esterna (%)", "Punto di Rugiada (°C)",
        "Temp Percepita (°C)", "Temperatura Interna (°C)", "Umidità Interna (%)", "Pressione Relativa (hPa)", "Pressione Assoluta (hPa)",
        "Vento Medio (km/h)", "Raffica (km/h)", "Direzione Vento (°)", "Pioggia Oraria (mm/h)",
        "Pioggia Giorno (mm)", "Pioggia Totale Anno (mm)", "Radiazione Solare (W/m²)", "Indice UV"
    ])
    for r in records:
        writer.writerow([
            r.get("id"), r.get("timestamp"), r.get("temp_c"), r.get("humidity"),
            r.get("dew_point_c"), calc_apparent_temp(r.get("temp_c"), r.get("humidity"), r.get("wind_speed_kmh")),
            r.get("temp_in_c"), r.get("humidity_in"),
            r.get("pressure_rel_hpa"), r.get("pressure_abs_hpa"), r.get("wind_speed_kmh"),
            r.get("wind_gust_kmh"), r.get("wind_dir_deg"), r.get("rain_rate_mm_hr"),
            r.get("daily_rain_mm"), r.get("yearly_rain_mm"), r.get("solar_radiation"),
            r.get("uv_index")
        ])
    output.seek(0)
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=storico_meteo.csv"}
    )

@router.get("/api/export/alerts-csv")
async def api_export_alerts_csv():
    """Esporta il registro eventi e notifiche in CSV per Excel."""
    alerts = get_alert_logs(limit=1000)
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';')
    writer.writerow(["ID", "Data e Ora", "Tipo Allarme", "Titolo Evento", "Messaggio Dettagliato"])
    for a in alerts:
        writer.writerow([a.get("id"), a.get("timestamp"), a.get("alert_type"), a.get("title"), a.get("message")])
    output.seek(0)
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=registro_eventi_allerte.csv"}
    )

@router.get("/api/export/records-csv")
async def api_export_records_csv():
    """Esporta l'Albo dei Record, i Record Mensili e la cronologia in CSV per Excel."""
    records = get_all_records()
    monthly_recs = get_monthly_records()
    monthly_sums = get_all_monthly_summaries(limit=100)
    history = get_records_history(limit=500)
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';')
    
    writer.writerow(["--- ALBO DEI RECORD ASSOLUTI ATTUALI (ALL-TIME) ---"])
    writer.writerow(["Chiave Record", "Categoria", "Titolo", "Valore Record", "Unità", "Data e Ora Registrazione"])
    for r in records:
        writer.writerow([r.get("record_key"), r.get("category"), r.get("title"), r.get("value"), r.get("unit"), r.get("timestamp")])
    
    writer.writerow([])
    writer.writerow(["--- ALBO DEI RECORD MENSILI STORICI ---"])
    writer.writerow(["Chiave", "Categoria", "Titolo Primato", "Valore Record", "Unità", "Mese / Anno Record", "Data Registrazione"])
    for mr in monthly_recs:
        writer.writerow([mr.get("record_key"), mr.get("category"), mr.get("title"), mr.get("value"), mr.get("unit"), mr.get("month_name"), mr.get("timestamp")])

    writer.writerow([])
    writer.writerow(["--- CRONOLOGIA DEI RECORD INFRANTI NEL TEMPO ---"])
    writer.writerow(["ID", "Data e Ora", "Titolo Record", "Vecchio Valore", "Nuovo Record Battuto", "Unità"])
    for h in history:
        writer.writerow([h.get("id"), h.get("timestamp"), h.get("title"), h.get("old_value"), h.get("new_value"), h.get("unit")])

    writer.writerow([])
    writer.writerow(["--- ARCHIVIO DEI RIEPILOGHI MENSILI CONSOLIDATI ---"])
    writer.writerow(["Mese/Anno", "T Media (°C)", "T Min (°C)", "T Max (°C)", "Pioggia Totale (mm)", "GG Pioggia", "Notti Tropicali", "Solare Aton (kWh)", "Autarchia (%)", "Raffica Max (km/h)"])
    for ms in monthly_sums:
        writer.writerow([
            ms.get("month_name"), ms.get("avg_temp"), ms.get("min_temp"), ms.get("max_temp"),
            ms.get("total_rain_mm"), ms.get("rainy_days_count"), ms.get("tropical_nights_count"),
            ms.get("solar_total_kwh"), ms.get("autarky_pct"), ms.get("max_wind_gust_kmh")
        ])
        
    output.seek(0)
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=albo_record_meteo_e_mensili.csv"}
    )

# ----------------- RECORD & RESOCONTI MENSILI -----------------

@router.get("/api/records/monthly")
async def api_get_monthly_records():
    """Restituisce l'Albo dei Record Mensili Storici e l'elenco dei riepiloghi mensili."""
    return {
        "monthly_records": get_monthly_records(),
        "monthly_summaries": get_all_monthly_summaries(limit=36)
    }

@router.get("/api/reports/monthly/{year}/{month}")
async def api_get_monthly_report(year: int, month: int):
    """Calcola o restituisce il riepilogo mensile per un determinato anno e mese."""
    ym = f"{year:04d}-{month:02d}"
    stored = get_monthly_summary_by_key(ym)
    if stored:
        return stored
    summary = calculate_monthly_summary(year, month)
    if summary.get("total_records", 0) > 0:
        save_monthly_summary(summary)
    return summary

@router.post("/api/reports/monthly/rebuild")
async def api_rebuild_monthly_reports():
    """Ricalcola tutti i riepiloghi mensili storici e aggiorna i record mensili assoluti."""
    return rebuild_all_historical_monthly_summaries()

@router.post("/api/reports/monthly/send-digest")
async def api_send_monthly_digest(year: Optional[int] = Query(None), month: Optional[int] = Query(None)):
    """Invia manualmente o su richiesta il Resoconto Mensile per il mese specificato (o per il mese precedente)."""
    return engine.send_monthly_digest(year=year, month=month)

