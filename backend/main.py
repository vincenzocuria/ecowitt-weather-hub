from __future__ import annotations
import os
import sys
import io
import csv
import json
import asyncio
import logging

# Assicura che la root del progetto sia sempre nel PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Optional, Dict, Any, List, Union
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, BackgroundTasks, Query
from fastapi.responses import JSONResponse, HTMLResponse, Response, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import urlencode
import uvicorn

from backend.config import settings
from backend.ecowitt_parser import parse_ecowitt_payload
from backend.alert_engine import engine
from backend.notifier import notifier
from backend.database import (
    save_reading, get_latest_reading, get_all_records, get_records_history,
    get_timeseries, search_history, get_history_kpis, get_alert_logs, deg_to_compass, calc_dew_point,
    get_station_status, get_pressure_trend, calc_apparent_temp,
    get_today_extremes, get_yesterday_same_time, get_recent_rain_totals,
    save_push_subscription, delete_push_subscription, get_all_push_subscriptions,
    save_energy_reading, get_latest_energy, get_today_energy_summary, get_energy_timeseries,
    get_sensor_aliases, save_sensor_alias, get_database_stats, perform_database_maintenance,
    get_unread_alerts_count, mark_alert_as_read, mark_all_alerts_as_read,
    delete_alert_log, clear_all_alert_logs, get_alerts_stats,
    to_local_datetime_str, DB_PATH
)
from backend.analytics import (
    calc_zambretti_forecast, abs_to_rel_pressure, evaluate_window_ventilation, evaluate_laundry_index,
    calc_humidex, evaluate_outdoor_activity, calc_sun_ephemeris, calc_moon_phase,
    calc_beaufort_scale, evaluate_indoor_comfort, calc_current_weather_condition
)
from backend.forecast_service import forecast_service
from backend.aton_service import aton_service
from backend.thinq_service import thinq_service
from backend.smartthings_service import smartthings_service
from backend.tuya_service import tuya_service

# Setup Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("weather_hub")

# Background Watchdog, Daily Digest, Evening Energy Digest & Nightly DB Maintenance Loop
async def watchdog_worker():
    logger.info("[WATCHDOG] Station Offline Watchdog, Daily Digest, Energy Report & Smart Automations loop attivato")
    while True:
        try:
            engine.check_offline_watchdog()
            engine.check_rain_forecast()
            engine.check_daily_digest()
            engine.check_evening_energy_digest()
            engine.check_nightly_maintenance()

            # Automazioni intelligenti Presenza S26 Ultra, Elettrodomestici, Clima & Solare
            latest_w = get_latest_reading() or {}
            latest_e = aton_service.latest_data or get_latest_energy() or {}
            an_ctx = build_analytics_context(latest_w)
            st_sum = smartthings_service.get_summary(latest_e, an_ctx.get("drying_index") if an_ctx else None)
            engine.evaluate_smartthings_automations(st_sum, latest_w, latest_e)
        except Exception as e:
            logger.error(f"Errore nel watchdog worker: {e}")
        await asyncio.sleep(60)



@asynccontextmanager
async def lifespan(app: FastAPI):
    watchdog_task = asyncio.create_task(watchdog_worker())
    aton_task = asyncio.create_task(aton_service.worker_loop())
    thinq_task = asyncio.create_task(thinq_service.worker_loop())
    smartthings_task = asyncio.create_task(smartthings_service.worker_loop())
    tuya_task = asyncio.create_task(tuya_service.worker_loop())
    yield
    watchdog_task.cancel()
    aton_service.stop()
    aton_task.cancel()
    thinq_service.stop()
    thinq_task.cancel()
    smartthings_task.cancel()
    await smartthings_service.close()
    tuya_task.cancel()



# FastAPI App
app = FastAPI(title="Ecowitt & Sainlogic Weather Station Hub", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Se AUTH_TOKEN non è configurato nel .env, l'autenticazione è aperta
    if not settings.AUTH_TOKEN:
        return await call_next(request)

    path = request.url.path

    # Percorsi esenti dall'autenticazione (ingestione meteo, PWA, asset statici, login)
    if (
        path == "/api/ecowitt" or
        path.startswith("/api/ecowitt") or
        path.startswith("/static/") or
        path in ("/manifest.json", "/sw.js", "/favicon.ico", "/login", "/logout")
    ):
        return await call_next(request)

    # 1. Query parameter (?token=..., ?key=..., ?auth=...)
    token_param = (
        request.query_params.get("token") or
        request.query_params.get("key") or
        request.query_params.get("auth")
    )

    # 2. Cookie permanente su questo dispositivo
    cookie_token = request.cookies.get(settings.AUTH_COOKIE_NAME)

    # 3. Header API (X-Auth-Token o Authorization: Bearer ...)
    header_token = request.headers.get("X-Auth-Token")
    if not header_token and "authorization" in request.headers:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            header_token = auth_header[7:].strip()

    is_authenticated = False
    set_cookie_needed = False

    if token_param and token_param == settings.AUTH_TOKEN:
        is_authenticated = True
        set_cookie_needed = True
    elif cookie_token and cookie_token == settings.AUTH_TOKEN:
        is_authenticated = True
    elif header_token and header_token == settings.AUTH_TOKEN:
        is_authenticated = True

    if not is_authenticated:
        if path.startswith("/api/"):
            return JSONResponse(
                {"error": "Accesso non autorizzato. Token di sicurezza mancante o errato."},
                status_code=401
            )
        # Se è una pagina HTML, reindirizza alla schermata di sblocco
        next_url = path
        if request.url.query:
            next_url += f"?{request.url.query}"
        return RedirectResponse(url=f"/login?next={next_url}", status_code=303)

    # Se autenticato tramite parametro URL su una pagina web (non API),
    # impostiamo il cookie permanente a 10 anni e ripuliamo l'URL visibile nel browser
    if set_cookie_needed and not path.startswith("/api/"):
        clean_params = [
            (k, v) for k, v in request.query_params.multi_items()
            if k not in ("token", "key", "auth")
        ]
        clean_url = path
        if clean_params:
            clean_url += f"?{urlencode(clean_params)}"
        response = RedirectResponse(url=clean_url, status_code=303)
        response.set_cookie(
            key=settings.AUTH_COOKIE_NAME,
            value=settings.AUTH_TOKEN,
            max_age=315360000,  # 10 anni
            path="/",
            httponly=True,
            samesite="lax"
        )
        return response

    response = await call_next(request)

    if set_cookie_needed:
        response.set_cookie(
            key=settings.AUTH_COOKIE_NAME,
            value=settings.AUTH_TOKEN,
            max_age=315360000,
            path="/",
            httponly=True,
            samesite="lax"
        )

    return response

# Static & Templates setup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Filtri personalizzati Jinja2 per conversione automatica UTC -> Europe/Rome
templates.env.filters["local_dt"] = lambda s: to_local_datetime_str(s, "%d/%m/%Y %H:%M:%S")
templates.env.filters["local_dt_short"] = lambda s: to_local_datetime_str(s, "%d/%m/%Y %H:%M")
templates.env.filters["local_time"] = lambda s: to_local_datetime_str(s, "%H:%M")
templates.env.filters["local_date"] = lambda s: to_local_datetime_str(s, "%d/%m/%Y")

# ----------------- AUTHENTICATION ROUTES -----------------
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: Optional[str] = "/"):
    cookie_token = request.cookies.get(settings.AUTH_COOKIE_NAME)
    if not settings.AUTH_TOKEN or cookie_token == settings.AUTH_TOKEN:
        return RedirectResponse(url=next or "/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"next_url": next or "/", "error": None}
    )

@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request):
    form = await request.form()
    token = (form.get("token") or "").strip()
    next_url = form.get("next", "/") or "/"
    if token == settings.AUTH_TOKEN:
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
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"next_url": next_url, "error": "Chiave di sicurezza non valida. Riprova."}
    )

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key=settings.AUTH_COOKIE_NAME, path="/")
    return response

# ----------------- BACKGROUND WORKER -----------------
def process_weather_data(raw_data: dict):
    try:
        parsed = parse_ecowitt_payload(raw_data)
        record_id = save_reading(parsed)
        logger.info(f"Salvata lettura ID {record_id} da {parsed.get('station_model')} ({parsed.get('timestamp')})")
        engine.evaluate(parsed)
    except Exception as e:
        logger.error(f"Errore durante l'elaborazione dei dati meteo: {e}", exc_info=True)

# ----------------- API ENDPOINTS -----------------
@app.post("/api/ecowitt")
@app.get("/api/ecowitt")
async def ingest_ecowitt(request: Request, bg: BackgroundTasks):
    form = await request.form()
    data = dict(form) or dict(request.query_params)
    logger.info(f"Ricevuto payload da Stazione (PASSKEY: {data.get('PASSKEY', 'N/D')})")
    bg.add_task(process_weather_data, data)
    return {"status": "success"}

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
    
    window_advice = evaluate_window_ventilation(temp_c, hum, temp_in, hum_in, rain_rate)
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

    return {
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
        "sun_ephemeris": sun_info,
        "moon_phase": moon_info,
        "dew_point_c": dew_point,
        "dew_point_in_c": dew_point_in,
        "cross_check": cross_check,
        "beaufort": beaufort
    }

@app.get("/api/forecast")
async def api_forecast():
    latest = get_latest_reading() or {}
    forecast_data = forecast_service.fetch_open_meteo()
    cross_check = forecast_service.build_cross_check_summary(latest)
    return {
        "forecast": forecast_data,
        "cross_check": cross_check
    }

@app.get("/api/status")
async def api_status():
    return get_station_status()

@app.get("/api/analytics")
async def api_analytics():
    latest = get_latest_reading() or {}
    return build_analytics_context(latest)

@app.get("/api/live")
async def api_live():
    latest = get_latest_reading()
    if not latest:
        return {"message": "In attesa dei primi dati dalla stazione meteo", "status_info": get_station_status()}
    
    # Sanitizzazione: rimuove payload raw e chiavi riservate
    clean_latest = dict(latest)
    clean_latest.pop("raw_data_json", None)
    clean_latest.pop("raw_payload", None)
    clean_latest.pop("station_mac", None)
    clean_latest.pop("PASSKEY", None)

    status_info = get_station_status()
    clean_latest["status_info"] = status_info
    analytics_ctx = build_analytics_context(latest)
    clean_latest["analytics"] = analytics_ctx
    clean_latest["sensor_aliases"] = get_sensor_aliases()
    clean_latest["climate_devices"] = thinq_service.get_cached_devices()
    clean_latest["thinq_enabled"] = settings.LG_THINQ_ENABLED
    clean_latest["thinq_connected"] = thinq_service.is_connected
    clean_latest["smartthings"] = smartthings_service.get_summary(
        aton_service.latest_data or get_latest_energy() or {},
        analytics_ctx.get("drying_index") if analytics_ctx else None
    )
    clean_latest["smartthings_enabled"] = settings.SMARTTHINGS_ENABLED
    clean_latest["tuya"] = tuya_service.get_summary()
    clean_latest["tuya_enabled"] = settings.TUYA_ENABLED
    return clean_latest



@app.post("/api/daily-digest/send")
@app.get("/api/daily-digest/send")
async def api_send_daily_digest():
    """Invia manualmente o via test la notifica 'Buongiorno Meteo' del mattino."""
    res = engine.send_daily_digest()
    return res

@app.get("/api/records")
async def api_records():
    return {"records": get_all_records()}

@app.get("/api/records/history")
async def api_records_history(record_key: Optional[str] = None, limit: int = 50):
    return {"history": get_records_history(record_key=record_key, limit=limit)}

@app.get("/api/history")
async def api_history(period: str = "24h"):
    return get_timeseries(period=period)

@app.get("/api/search")
async def api_search(start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100, page: int = 1):
    offset = (page - 1) * limit
    records, total = search_history(start_date=start_date, end_date=end_date, limit=limit, offset=offset)
    return {"records": records, "total": total, "page": page, "limit": limit}

@app.get("/api/search/kpis")
async def api_search_kpis(start_date: Optional[str] = None, end_date: Optional[str] = None):
    return get_history_kpis(start_date=start_date, end_date=end_date)

@app.get("/api/export/csv")
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

@app.get("/api/export/alerts-csv")
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

@app.get("/api/export/records-csv")
async def api_export_records_csv():
    """Esporta l'Albo dei Record e la cronologia dei record infranti in CSV per Excel."""
    records = get_all_records()
    history = get_records_history(limit=500)
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';')
    
    writer.writerow(["--- ALBO DEI RECORD ASSOLUTI ATTUALI ---"])
    writer.writerow(["Chiave Record", "Categoria", "Titolo", "Valore Record", "Unità", "Data e Ora Registrazione"])
    for r in records:
        writer.writerow([r.get("record_key"), r.get("category"), r.get("title"), r.get("value"), r.get("unit"), r.get("timestamp")])
    
    writer.writerow([])
    writer.writerow(["--- CRONOLOGIA DEI RECORD INFRANTI NEL TEMPO ---"])
    writer.writerow(["ID", "Data e Ora", "Titolo Record", "Vecchio Valore", "Nuovo Record Battuto", "Unità"])
    for h in history:
        writer.writerow([h.get("id"), h.get("timestamp"), h.get("title"), h.get("old_value"), h.get("new_value"), h.get("unit")])
        
    output.seek(0)
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=albo_record_meteo.csv"}
    )

@app.get("/api/alerts")
async def api_alerts(limit: int = 50, unread_only: bool = False):
    alerts = get_alert_logs(limit=limit, unread_only=unread_only)
    unread_count = get_unread_alerts_count()
    return {
        "alerts": alerts,
        "unread_count": unread_count,
        "total_count": len(alerts)
    }

@app.get("/api/alerts/unread-count")
async def api_alerts_unread_count():
    return {"unread_count": get_unread_alerts_count()}

@app.post("/api/alerts/{alert_id}/read")
async def api_mark_alert_read(alert_id: int):
    success = mark_alert_as_read(alert_id)
    return {"status": "ok" if success else "not_found", "unread_count": get_unread_alerts_count()}

@app.post("/api/alerts/mark-all-read")
async def api_mark_all_alerts_read():
    marked = mark_all_alerts_as_read()
    return {"status": "ok", "marked": marked, "unread_count": 0}

@app.delete("/api/alerts/{alert_id}")
async def api_delete_alert(alert_id: int):
    success = delete_alert_log(alert_id)
    return {"status": "ok" if success else "not_found", "unread_count": get_unread_alerts_count()}

@app.post("/api/alerts/clear-all")
async def api_clear_all_alerts():
    cleared = clear_all_alert_logs()
    return {"status": "ok", "cleared": cleared, "unread_count": 0}

# --- Web Push (PWA iOS / Android / Desktop) Endpoints ---
@app.get("/api/push/vapid-public-key")
async def api_push_vapid_key():
    key = notifier.get_vapid_public_key()
    if not key:
        return JSONResponse({"error": "VAPID non pronto"}, status_code=503)
    return {"public_key": key}

@app.post("/api/push/subscribe")
async def api_push_subscribe(request: Request):
    try:
        data = await request.json()
        endpoint = data.get("endpoint")
        keys = data.get("keys", {})
        p256dh = keys.get("p256dh")
        auth = keys.get("auth")
        user_agent = request.headers.get("user-agent", "")
        
        if not endpoint or not p256dh or not auth:
            return JSONResponse({"error": "Dati di sottoscrizione incompleti"}, status_code=400)
            
        save_push_subscription(endpoint, p256dh, auth, user_agent)
        count = len(get_all_push_subscriptions())
        logger.info(f"[PUSH] Nuovo dispositivo PWA iscritto. Totale attivi: {count}")
        return {"status": "subscribed", "devices_count": count}
    except Exception as e:
        logger.error(f"[PUSH] Errore sottoscrizione: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/push/unsubscribe")
async def api_push_unsubscribe(request: Request):
    try:
        data = await request.json()
        endpoint = data.get("endpoint")
        if endpoint:
            delete_push_subscription(endpoint)
            logger.info(f"[PUSH] Dispositivo rimosso con successo.")
        return {"status": "unsubscribed"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/push/status")
async def api_push_status():
    subs = get_all_push_subscriptions()
    return {
        "enabled": bool(notifier.get_vapid_public_key()),
        "devices_count": len(subs),
        "vapid_public_key": notifier.get_vapid_public_key()
    }

@app.post("/api/test-alert")
@app.get("/api/test-alert")
async def api_test_alert(alert_type: str = "record"):
    notifier.send_alert(
        alert_type=alert_type,
        title="🔔 Test Notifiche Weather Hub",
        message="Se leggi questo messaggio, le Notifiche Push PWA (iOS/Android/PC) e ntfy funzionano alla perfezione!",
        priority="high"
    )
    return {
        "status": "sent",
        "devices_notified": len(get_all_push_subscriptions()),
        "ntfy_topic": settings.NTFY_TOPIC
    }

# --- STATISTICHE, BACKUP & MANUTENZIONE DATABASE ---
@app.get("/api/system/db-stats")
async def api_system_db_stats():
    """Restituisce le statistiche su dimensioni del database, totale campioni e stato WAL."""
    return get_database_stats()

@app.get("/api/system/backup")
async def api_system_backup():
    """Scarica il file completo del database SQLite come backup sicuro."""
    if not os.path.exists(DB_PATH):
        return JSONResponse({"error": "Database non trovato"}, status_code=404)
    # Esegue un checkpoint prima del download per sincronizzare il file WAL nel DB principale
    try:
        from backend.database import get_connection
        c = get_connection()
        c.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        c.close()
    except Exception:
        pass
    return FileResponse(
        path=DB_PATH,
        filename="weather_history_backup.db",
        media_type="application/octet-stream"
    )

@app.post("/api/system/maintenance")
async def api_system_maintenance(retention_days: int = Query(60, ge=7, le=365)):
    """Esegue manualmente la compattazione e il downsampling dello storico > retention_days."""
    res = perform_database_maintenance(retention_days=retention_days)
    return res

# --- GESTIONE ALIAS SENSORI PERSONALIZZATI ---
@app.get("/api/sensors/aliases")
async def api_get_sensor_aliases():
    """Restituisce i nomi personalizzati assegnati ai canali dei sensori."""
    return {"aliases": get_sensor_aliases()}

@app.post("/api/sensors/aliases")
async def api_save_sensor_alias(request: Request):
    """Salva o aggiorna il nome di un canale sensore (es: soil_ch1 -> 'Giardino')."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    sensor_id = data.get("sensor_id")
    alias = data.get("alias", "")
    if not sensor_id:
        return JSONResponse({"error": "ID sensore mancante"}, status_code=400)
    save_sensor_alias(sensor_id, alias)
    return {"status": "saved", "sensor_id": sensor_id, "alias": alias, "aliases": get_sensor_aliases()}

@app.get("/api/energy/latest")
async def api_energy_latest():
    """Restituisce l'ultima lettura energetica live da Aton Storage."""
    data = aton_service.latest_data or get_latest_energy()
    return {
        "enabled": settings.ATON_ENABLED,
        "connected": aton_service.is_connected,
        "serial_number": settings.ATON_SN,
        "data": data
    }

@app.get("/api/energy/summary")
async def api_energy_summary():
    """Restituisce il riassunto energetico odierno (produzione, autoconsumo, autosufficienza)."""
    return get_today_energy_summary()

@app.get("/api/energy/history")
async def api_energy_history(hours: int = 24):
    """Restituisce la serie storica energetica per i grafici."""
    return {"history": get_energy_timeseries(hours=hours)}

@app.get("/api/energy/house-breakdown")
async def api_energy_house_breakdown():
    """
    Restituisce la ripartizione dettagliata in tempo reale dei consumi domestici:
    potenza totale della casa, dispositivi/prese smart attive con relativo assorbimento (W, V, A),
    elettrodomestici in esecuzione, climatizzatori accesi e stima del carico di fondo/non monitorato.
    """
    energy_data = aton_service.latest_data or get_latest_energy() or {}
    summary = get_today_energy_summary() or {}

    total_house_w = float(energy_data.get("p_utenze") if energy_data.get("p_utenze") is not None else (energy_data.get("house_load_w") or 0.0))
    total_house_kwh = summary.get("total_house_kwh", "0.0")
    p_solar_w = float(energy_data.get("p_solare") or energy_data.get("solar_power_w") or 0.0)
    p_batt_w = float(energy_data.get("p_batteria") or energy_data.get("battery_power_w") or 0.0)
    p_grid_w = float(energy_data.get("p_rete") or energy_data.get("grid_power_w") or 0.0)

    active_consumers = []
    standby_devices = []

    # 1. Prese Smart ed Interruttori Tuya / Smart Life
    if settings.TUYA_ENABLED:
        tuya_sum = tuya_service.get_summary()
        all_tuya = tuya_sum.get("enabled_devices") or tuya_sum.get("devices") or []
        for dev in all_tuya:
            p_w = float(dev.get("power_w") or 0.0)
            is_on = dev.get("is_on")
            c_type = dev.get("type") or "generic"
            icon = dev.get("icon") or "🔌"
            name = dev.get("name", "Presa Smart")
            cat_label = dev.get("type_label") or "Presa Smart Life"

            status_txt = "Spento" if is_on is False else "Acceso"
            if is_on and p_w > 0:
                status_txt = f"Assorbimento: {p_w:.1f} W"
            elif is_on and dev.get("temp_current") is not None:
                status_txt = f"Temp: {dev.get('temp_current')}°C"

            entry = {
                "id": f"tuya_{dev.get('id')}",
                "raw_id": dev.get("id"),
                "ecosystem": "tuya",
                "name": name,
                "icon": icon,
                "category_label": cat_label,
                "type": c_type,
                "is_on": is_on,
                "can_toggle": (c_type != "curtain") and (is_on is not None or c_type in ("plug", "light", "irrigation")),
                "power_w": p_w,
                "voltage_v": dev.get("voltage_v"),
                "current_a": dev.get("current_a"),
                "status_text": status_txt
            }

            if is_on is True and (p_w > 0 or c_type in ("plug", "light", "switch", "thermostat")):
                active_consumers.append(entry)
            else:
                standby_devices.append(entry)

    # 2. Climatizzatori LG ThinQ
    if settings.LG_THINQ_ENABLED:
        thinq_devs = thinq_service.get_cached_devices()
        for d in thinq_devs:
            is_on = d.get("is_on", False)
            mode = d.get("mode") or d.get("job_mode", "COOL")
            mode_lbl = "Raffrescamento" if mode == "COOL" else ("Riscaldamento" if mode == "HEAT" else "Deumidificatore / Ventilazione")
            t_curr = d.get("current_temp")
            t_target = d.get("target_temp")

            stat_parts = []
            if is_on:
                stat_parts.append(f"In funzione ({mode_lbl})")
                if t_target is not None:
                    stat_parts.append(f"Impostato: {t_target}°C")
                if t_curr is not None:
                    stat_parts.append(f"Stanza: {t_curr}°C")
            else:
                stat_parts.append("Spento")
                if t_curr is not None:
                    stat_parts.append(f"Temp: {t_curr}°C")

            entry = {
                "id": f"thinq_{d.get('device_id') or d.get('deviceId')}",
                "raw_id": d.get("device_id") or d.get("deviceId"),
                "ecosystem": "thinq",
                "name": d.get("alias") or d.get("name", "Climatizzatore LG"),
                "icon": "❄️" if mode == "COOL" else ("🔥" if mode == "HEAT" else "🌬️"),
                "category_label": "Climatizzatore LG ThinQ",
                "type": "climate",
                "is_on": is_on,
                "can_toggle": True,
                "power_w": 0.0,
                "status_text": " • ".join(stat_parts)
            }
            if is_on:
                active_consumers.append(entry)
            else:
                standby_devices.append(entry)

    # 3. Samsung SmartThings (Lavatrice / Lavastoviglie)
    if settings.SMARTTHINGS_ENABLED:
        st_summary = smartthings_service.get_summary(energy_data)
        washer = st_summary.get("washer") or {}
        if washer and washer.get("device_id"):
            is_run = washer.get("is_running", False)
            is_on = washer.get("is_on", False)
            p_w = float(washer.get("power_w") or 0.0)

            st_text = washer.get("job_state_label") or ("In Lavaggio" if is_run else "In Standby")
            if washer.get("remaining_min") and washer.get("remaining_min") > 0:
                st_text += f" • {washer.get('remaining_min')} min rimasti (fine ~{washer.get('finish_estimate')})"
            if washer.get("cycle_name"):
                st_text += f" • {washer.get('cycle_name')}"

            entry = {
                "id": f"st_{washer.get('device_id')}",
                "raw_id": washer.get("device_id"),
                "ecosystem": "smartthings",
                "name": washer.get("name", "Lavatrice Samsung"),
                "icon": "🫧",
                "category_label": "Lavatrice Samsung Smart",
                "type": "appliance",
                "is_on": is_on,
                "is_running": is_run,
                "can_toggle": False,
                "power_w": p_w,
                "status_text": st_text
            }
            if is_run or is_on or p_w > 0:
                active_consumers.append(entry)
            else:
                standby_devices.append(entry)

        dish = st_summary.get("dishwasher") or {}
        if dish and dish.get("device_id"):
            is_run = dish.get("is_running", False)
            is_on = dish.get("is_on", False)
            p_w = float(dish.get("power_w") or 0.0)

            st_text = dish.get("job_state_label") or ("In Lavaggio" if is_run else "In Standby")
            if dish.get("remaining_min") and dish.get("remaining_min") > 0:
                st_text += f" • {dish.get('remaining_min')} min rimasti (fine ~{dish.get('finish_estimate')})"
            if dish.get("cycle_name"):
                st_text += f" • {dish.get('cycle_name')}"

            entry = {
                "id": f"st_{dish.get('device_id')}",
                "raw_id": dish.get("device_id"),
                "ecosystem": "smartthings",
                "name": dish.get("name", "Lavastoviglie Samsung"),
                "icon": "🍽️",
                "category_label": "Lavastoviglie Samsung Smart",
                "type": "appliance",
                "is_on": is_on,
                "is_running": is_run,
                "can_toggle": False,
                "power_w": p_w,
                "status_text": st_text
            }
            if is_run or is_on or p_w > 0:
                active_consumers.append(entry)
            else:
                standby_devices.append(entry)

    # Calcolo totali e quote
    monitored_power_w = sum(d.get("power_w", 0.0) for d in active_consumers)
    monitored_power_w = round(monitored_power_w, 1)

    unmonitored_power_w = max(0.0, total_house_w - monitored_power_w)
    unmonitored_power_w = round(unmonitored_power_w, 1)

    for d in active_consumers:
        p = d.get("power_w", 0.0)
        d["percent_of_total"] = round((p / total_house_w * 100), 1) if total_house_w > 0 else 0.0

    active_consumers.sort(key=lambda x: (x.get("power_w", 0.0), 1 if x.get("is_running") or x.get("is_on") else 0), reverse=True)

    monitored_pct = round((monitored_power_w / total_house_w * 100), 1) if total_house_w > 0 else 0.0
    unmonitored_pct = round((unmonitored_power_w / total_house_w * 100), 1) if total_house_w > 0 else 0.0

    return {
        "total_house_w": round(total_house_w, 1),
        "total_house_kwh": total_house_kwh,
        "solar_power_w": round(p_solar_w, 1),
        "battery_power_w": round(p_batt_w, 1),
        "grid_power_w": round(p_grid_w, 1),
        "monitored_power_w": monitored_power_w,
        "unmonitored_power_w": unmonitored_power_w,
        "monitored_pct": monitored_pct,
        "unmonitored_pct": unmonitored_pct,
        "active_consumers": active_consumers,
        "standby_devices": standby_devices,
        "active_count": len(active_consumers),
        "standby_count": len(standby_devices)
    }

# --- LG ThinQ Climatizzazione Endpoints ---
@app.get("/api/thinq/devices")
async def api_thinq_devices():
    """Restituisce la lista e lo stato in tempo reale dei dispositivi LG ThinQ."""
    devices = thinq_service.get_cached_devices()
    if not devices and settings.LG_THINQ_ENABLED and settings.LG_THINQ_PAT:
        devices = await thinq_service.fetch_all_devices()
    return {
        "enabled": settings.LG_THINQ_ENABLED,
        "connected": thinq_service.is_connected,
        "devices": devices
    }

@app.post("/api/thinq/device/{device_id}/control")
async def api_thinq_control(device_id: str, request: Request):
    """Invia comandi (Power, Temp, Mode, Fan Speed, Swing) a un condizionatore LG."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    return await thinq_service.control_device(device_id, payload)

@app.post("/api/thinq/sync")
@app.get("/api/thinq/sync")
async def api_thinq_sync():
    """Forza la risincronizzazione con il cloud LG ThinQ."""
    devices = await thinq_service.fetch_all_devices()
    return {"status": "synced", "connected": thinq_service.is_connected, "devices": devices}

# --- Samsung SmartThings Endpoints ---
@app.get("/api/smartthings/summary")
async def api_smartthings_summary():
    """Restituisce il riepilogo in tempo reale di lavatrice, lavastoviglie, presenza e sinergia solare."""
    latest = get_latest_reading() or {}
    analytics = build_analytics_context(latest)
    energy_latest = aton_service.latest_data or get_latest_energy() or {}
    return smartthings_service.get_summary(energy_latest, analytics.get("drying_index") if analytics else None)

@app.post("/api/smartthings/sync")
@app.get("/api/smartthings/sync")
async def api_smartthings_sync():
    """Forza la risincronizzazione con il cloud Samsung SmartThings."""
    await smartthings_service.sync_all()
    latest = get_latest_reading() or {}
    analytics = build_analytics_context(latest)
    energy_latest = aton_service.latest_data or get_latest_energy() or {}
    return smartthings_service.get_summary(energy_latest, analytics.get("drying_index") if analytics else None)

@app.post("/api/smartthings/device/{device_id}/command")
async def api_smartthings_command(device_id: str, request: Request):
    """Invia un comando REST (accensione, spegnimento, switch) a un dispositivo SmartThings."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    cap = payload.get("capability", "switch")
    cmd = payload.get("command", "off")
    args = payload.get("arguments", [])
    res = await smartthings_service.execute_command(device_id, cap, cmd, args)
    return {"success": res}

# --- Tuya / Smart Life Endpoints ---
@app.get("/api/tuya/summary")
async def api_tuya_summary():
    """Restituisce il riepilogo in tempo reale di tutti i dispositivi Smart Life (Tuya) abilitati."""
    return tuya_service.get_summary()

@app.post("/api/tuya/sync")
@app.get("/api/tuya/sync")
async def api_tuya_sync():
    """Forza la risincronizzazione con il cloud Tuya."""
    await tuya_service.sync_all()
    return tuya_service.get_summary()

@app.get("/api/tuya/devices")
async def api_tuya_devices():
    """Restituisce tutti i dispositivi rilevati su Tuya con relativo stato di abilitazione."""
    summary = tuya_service.get_summary()
    return {"devices": summary.get("all_devices", []), "enabled_count": summary.get("enabled_devices_count", 0)}

@app.post("/api/tuya/device/{device_id}/toggle")
async def api_tuya_toggle(device_id: str, request: Request):
    """Inverte o imposta lo stato ON/OFF del dispositivo Tuya."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    target_state = payload.get("state")
    res = await tuya_service.toggle_device(device_id, target_state)
    return res

@app.post("/api/tuya/device/{device_id}/command")
async def api_tuya_command(device_id: str, request: Request):
    """Invia un comando avanzato (es: setpoint temperatura, comandi raw) a un dispositivo Tuya."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    commands = payload.get("commands", [])
    if not commands and "temp_c" in payload:
        return await tuya_service.set_thermostat_temp(device_id, float(payload["temp_c"]))
    if not commands and ("action" in payload or "control" in payload):
        return await tuya_service.control_curtain(device_id, payload.get("action") or payload.get("control"))
    return await tuya_service.send_command(device_id, commands)

@app.post("/api/tuya/device/{device_id}/curtain")
async def api_tuya_curtain(device_id: str, request: Request):
    """Invia comandi di apertura/stop/chiusura alla persiana/tenda Tuya."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    action = payload.get("action") or payload.get("control") or "stop"
    return await tuya_service.control_curtain(device_id, action)

@app.post("/api/tuya/device/{device_id}/config")
async def api_tuya_config(device_id: str, request: Request):
    """Salva le impostazioni di abilitazione (ON/OFF visibilità) e nome personalizzato per il dispositivo Tuya."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    enabled = payload.get("enabled", True)
    custom_name = payload.get("custom_name")
    await tuya_service.set_device_enabled(device_id, enabled, custom_name)
    return {"status": "ok", "device_id": device_id, "enabled": enabled, "custom_name": custom_name}

# --- Unified Devices Hub Endpoints ---
def build_devices_catalog() -> Dict[str, Any]:
    """Genera l'elenco normalizzato e aggregato di tutti i dispositivi smart (Tuya, LG ThinQ, SmartThings, Aton Solar)."""
    devices = []
    
    # 1. Tuya / Smart Life
    tuya_summary = tuya_service.get_summary() if settings.TUYA_ENABLED else {}
    tuya_dev_list = tuya_summary.get("enabled_devices") or tuya_summary.get("devices") or []
    for dev in tuya_dev_list:
        c_type = dev.get("type") or dev.get("category_meta", {}).get("type", "generic")
        
        ui_category = "plugs"
        if c_type in ("thermostat",):
            ui_category = "climate"
        elif c_type in ("irrigation",):
            ui_category = "irrigation"
        elif c_type in ("curtain",):
            ui_category = "curtains"
        elif c_type in ("plug", "light"):
            ui_category = "plugs"
        else:
            ui_category = "other"
            
        status_parts = []
        if c_type == "curtain":
            c_state = dev.get("curtain_state")
            if c_state:
                status_parts.append(str(c_state).capitalize())
            else:
                status_parts.append("Pronta")
        elif dev.get("is_on") is True:
            p_w = dev.get("power_w", 0.0) or 0.0
            if p_w > 0:
                status_parts.append(f"Acceso ({p_w:.1f} W)")
            else:
                status_parts.append("Acceso")
        elif dev.get("is_on") is False:
            status_parts.append("Spento")
        else:
            status_parts.append("Online" if dev.get("online") else "Offline")

        if dev.get("temp_current") is not None:
            status_parts.append(f"{dev.get('temp_current')}°C")

        devices.append({
            "id": f"tuya_{dev.get('id')}",
            "raw_id": dev.get("id"),
            "ecosystem": "tuya",
            "name": dev.get("name", "Dispositivo Tuya"),
            "icon": dev.get("icon") or dev.get("category_meta", {}).get("icon", "🔌"),
            "category": ui_category,
            "category_label": dev.get("type_label") or dev.get("category_meta", {}).get("label", "Smart Life"),
            "is_on": dev.get("is_on"),
            "can_toggle": (c_type != "curtain") and (dev.get("is_on") is not None or c_type in ("plug", "light", "irrigation")),
            "is_online": dev.get("online", True),
            "status_text": " • ".join(status_parts) if status_parts else "Stato Sconosciuto",
            "power_w": dev.get("power_w", 0.0) or 0.0,
            "voltage_v": dev.get("voltage_v"),
            "current_a": dev.get("current_a"),
            "temp_current": dev.get("temp_current"),
            "temp_set": dev.get("temp_set"),
            "battery_pct": dev.get("battery_pct"),
            "work_state": dev.get("work_state"),
            "curtain_state": dev.get("curtain_state"),
            "raw": dev
        })

    # 2. LG ThinQ Climatizzatori
    thinq_devices = thinq_service.get_cached_devices() if settings.LG_THINQ_ENABLED else []
    for d in thinq_devices:
        dev_id = d.get("device_id") or d.get("deviceId") or "unknown"
        is_on = d.get("is_on", False)
        t_curr = d.get("current_temp")
        t_target = d.get("target_temp")
        mode = d.get("mode") or d.get("job_mode", "COOL")
        
        status_txt = "Acceso" if is_on else "Spento"
        if is_on and t_curr is not None:
            status_txt += f" • {t_curr}°C (Set: {t_target}°C)"
        elif t_curr is not None:
            status_txt += f" • {t_curr}°C"

        devices.append({
            "id": f"thinq_{dev_id}",
            "raw_id": dev_id,
            "ecosystem": "thinq",
            "name": d.get("alias") or d.get("name", "Climatizzatore LG"),
            "icon": "❄️" if mode == "COOL" else ("🔥" if mode == "HEAT" else "🌬️"),
            "category": "climate",
            "category_label": "Climatizzatore LG ThinQ",
            "is_on": is_on,
            "can_toggle": True,
            "is_online": d.get("is_online", True),
            "status_text": status_txt,
            "power_w": 0.0,
            "temp_current": t_curr,
            "temp_set": t_target,
            "job_mode": mode,
            "fan_speed": d.get("fan_speed", "LOW"),
            "swing_vertical": d.get("rotate_up_down", False),
            "swing_horizontal": d.get("rotate_left_right", False),
            "raw": d
        })

    # 3. Samsung SmartThings
    if settings.SMARTTHINGS_ENABLED:
        energy_latest = aton_service.latest_data or get_latest_energy() or {}
        st_summary = smartthings_service.get_summary(energy_latest)
        
        # Lavatrice
        washer = st_summary.get("washer", {})
        if washer and washer.get("is_connected") is not False and washer.get("device_id"):
            is_running = washer.get("is_running", False)
            p_w = washer.get("power_w", 0.0) or 0.0
            devices.append({
                "id": f"st_{washer.get('device_id')}",
                "raw_id": washer.get("device_id"),
                "ecosystem": "smartthings",
                "name": washer.get("name", "Lavatrice Smart"),
                "icon": "🫧",
                "category": "appliances",
                "category_label": "Lavatrice Samsung",
                "is_on": is_running or (washer.get("switch_state") == "on"),
                "can_toggle": bool(washer.get("switch_state")),
                "is_online": True,
                "status_text": washer.get("state_text", "In Standby"),
                "power_w": p_w,
                "completion_time": washer.get("completion_time"),
                "cycle_name": washer.get("cycle_name"),
                "raw": washer
            })
            
        # Lavastoviglie
        dish = st_summary.get("dishwasher", {})
        if dish and dish.get("is_connected") is not False and dish.get("device_id"):
            is_running = dish.get("is_running", False)
            p_w = dish.get("power_w", 0.0) or 0.0
            devices.append({
                "id": f"st_{dish.get('device_id')}",
                "raw_id": dish.get("device_id"),
                "ecosystem": "smartthings",
                "name": dish.get("name", "Lavastoviglie Smart"),
                "icon": "🍽️",
                "category": "appliances",
                "category_label": "Lavastoviglie Samsung",
                "is_on": is_running or (dish.get("switch_state") == "on"),
                "can_toggle": bool(dish.get("switch_state")),
                "is_online": True,
                "status_text": dish.get("state_text", "In Standby"),
                "power_w": p_w,
                "completion_time": dish.get("completion_time"),
                "cycle_name": dish.get("cycle_name"),
                "raw": dish
            })

        # Presenza / Smartphone
        presence = st_summary.get("presence", {})
        if presence and presence.get("device_id"):
            is_present = presence.get("is_present", True)
            batt = presence.get("battery_percent")
            stat = "A Casa 🟢" if is_present else "Fuori Casa 📍"
            if batt is not None:
                stat += f" • {batt}%"
            devices.append({
                "id": f"st_{presence.get('device_id')}",
                "raw_id": presence.get("device_id"),
                "ecosystem": "smartthings",
                "name": presence.get("name", "Smartphone Galaxy"),
                "icon": "📱",
                "category": "presence",
                "category_label": "Sensore Presenza & Posizione",
                "is_on": is_present,
                "can_toggle": False,
                "is_online": True,
                "status_text": stat,
                "power_w": 0.0,
                "battery_pct": batt,
                "is_present": is_present,
                "raw": presence
            })

    # 4. Aton Storage Fotovoltaico & Batteria
    if settings.ATON_ENABLED:
        e_latest = aton_service.latest_data or get_latest_energy() or {}
        p_solar = float(e_latest.get("solar_power_w", 0) or 0)
        p_batt = float(e_latest.get("battery_power_w", 0) or 0)
        soc = float(e_latest.get("battery_soc_pct", 0) or 0)
        load = float(e_latest.get("house_load_w", 0) or 0)
        grid = float(e_latest.get("grid_power_w", 0) or 0)
        
        stat = f"Solare: {int(p_solar)} W • Batteria: {int(soc)}%"
        devices.append({
            "id": "aton_storage_hub",
            "raw_id": "aton_storage_hub",
            "ecosystem": "aton",
            "name": "Impianto Solare & Accumulo Aton",
            "icon": "☀️",
            "category": "energy",
            "category_label": "Fotovoltaico & Batteria",
            "is_on": p_solar > 20 or soc > 10,
            "can_toggle": False,
            "is_online": True,
            "status_text": stat,
            "power_w": load,
            "solar_power_w": p_solar,
            "battery_soc_pct": soc,
            "battery_power_w": p_batt,
            "house_load_w": load,
            "grid_power_w": grid,
            "raw": e_latest
        })

    # Statistiche di sintesi
    total_count = len(devices)
    active_count = sum(1 for d in devices if d.get("is_on") is True)
    total_power = sum(d.get("power_w", 0.0) for d in devices if d.get("is_on") is True)
    online_count = sum(1 for d in devices if d.get("is_online", True))

    return {
        "devices": devices,
        "stats": {
            "total": total_count,
            "active": active_count,
            "total_power_w": round(total_power, 1),
            "online": online_count
        }
    }

@app.get("/api/devices/all")
async def api_devices_all():
    """Restituisce la lista aggregata e normalizzata di tutti i dispositivi smart."""
    return build_devices_catalog()

@app.post("/api/devices/turn-all")
async def api_devices_turn_all(request: Request):
    """Accende o spegne in blocco tutti i dispositivi commutabili (Prese, Luci, Clima)."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    
    target_state = payload.get("state", False)
    category = payload.get("category", "all")
    results = []

    # 1. Tuya
    if settings.TUYA_ENABLED:
        tuya_summary = tuya_service.get_summary()
        tuya_devs = tuya_summary.get("enabled_devices") or tuya_summary.get("devices") or []
        for dev in tuya_devs:
            c_type = dev.get("type") or dev.get("category_meta", {}).get("type", "generic")
            if c_type in ("plug", "light", "irrigation") and (category in ("all", "plugs")):
                if dev.get("is_on") != target_state:
                    res = await tuya_service.toggle_device(dev.get("id"), target_state)
                    results.append({"name": dev.get("name"), "res": res})

    # 2. LG ThinQ
    if settings.LG_THINQ_ENABLED and (category in ("all", "climate")):
        for d in thinq_service.get_cached_devices():
            if d.get("is_on") != target_state:
                dev_id = d.get("device_id") or d.get("deviceId")
                res = await thinq_service.control_device(dev_id, {"power": target_state})
                results.append({"name": d.get("alias"), "res": res})

    return {"status": "ok", "target_state": target_state, "updated_count": len(results), "details": results}

# ----------------- UI HTML ROUTES -----------------
@app.get("/", response_class=HTMLResponse)
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
    
    status_info = get_station_status()
    pressure_trend = latest.get("pressure_trend") or get_pressure_trend(latest.get("pressure_rel_hpa"))
    apparent_temp = latest.get("apparent_temp_c") or calc_apparent_temp(latest.get("temp_c"), latest.get("humidity"), latest.get("wind_speed_kmh"))
    
    all_records = get_all_records()
    top_records = [r for r in all_records if r["record_key"] in ("temp_max", "temp_min", "wind_gust_max", "rain_daily_max", "pressure_min")][:4]

    # Analisi avanzate & Nowcasting
    analytics = build_analytics_context(latest)
    forecast_data = forecast_service.fetch_open_meteo()
    cross_check = forecast_service.build_cross_check_summary(latest)

    # Dati Energetici Aton Storage
    energy_latest = aton_service.latest_data or get_latest_energy() or {}
    energy_summary = get_today_energy_summary()

    # Dati SmartThings & Tuya Smart Life
    smartthings_summary = smartthings_service.get_summary(energy_latest, analytics.get("drying_index") if analytics else None)
    tuya_summary = tuya_service.get_summary()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "active_page": "dashboard",
            "title": "Ecowitt & Sainlogic Weather Hub",
            "latest": latest,
            "station_model": station_model,
            "batt_wh65": batt_wh65,
            "wind_dir_text": wind_dir_text,
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
            "thinq_enabled": settings.LG_THINQ_ENABLED,
            "thinq_connected": thinq_service.is_connected,
            "climate_devices": thinq_service.get_cached_devices(),
            "smartthings": smartthings_summary,
            "smartthings_enabled": settings.SMARTTHINGS_ENABLED,
            "tuya": tuya_summary,
            "tuya_enabled": settings.TUYA_ENABLED,
            "sensor_aliases": get_sensor_aliases(),
            "db_stats": get_database_stats(),
            "ntfy_topic": settings.NTFY_TOPIC
        }
    )

@app.get("/devices", response_class=HTMLResponse)
async def devices_page(request: Request):
    catalog = build_devices_catalog()
    return templates.TemplateResponse(
        request=request,
        name="devices.html",
        context={
            "active_page": "devices",
            "title": "Dispositivi & Smart Home • Weather Hub",
            "devices": catalog.get("devices", []),
            "stats": catalog.get("stats", {}),
            "tuya_enabled": settings.TUYA_ENABLED,
            "thinq_enabled": settings.LG_THINQ_ENABLED,
            "smartthings_enabled": settings.SMARTTHINGS_ENABLED,
            "aton_enabled": settings.ATON_ENABLED
        }
    )

@app.get("/records", response_class=HTMLResponse)
async def records_page(request: Request):
    records = get_all_records()
    history = get_records_history(limit=30)
    return templates.TemplateResponse(
        request=request,
        name="records.html",
        context={
            "active_page": "records",
            "title": "Albo dei Record • Weather Hub",
            "records": records,
            "history": history
        }
    )

@app.get("/charts", response_class=HTMLResponse)
async def charts_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="charts.html",
        context={
            "active_page": "charts",
            "title": "Grafici & Trend • Weather Hub"
        }
    )

@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request, start_date: Optional[str] = None, end_date: Optional[str] = None, page: int = 1):
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
            "title": "Archivio & Ricerche • Weather Hub",
            "records": records,
            "total_count": total_count,
            "page": page,
            "max_pages": max_pages,
            "start_date": start_date,
            "end_date": end_date,
            "kpis": kpis
        }
    )

@app.get("/alerts-page", response_class=HTMLResponse)
async def alerts_page(request: Request):
    alerts = get_alert_logs(limit=250)
    unread_count = get_unread_alerts_count()
    stats = get_alerts_stats()
    recent_limit = 5
    recent_alerts = alerts[:recent_limit]
    archive_alerts = alerts[recent_limit:]
    return templates.TemplateResponse(
        request=request,
        name="alerts.html",
        context={
            "active_page": "alerts",
            "title": "Centro Notifiche • Weather Hub",
            "alerts": alerts,
            "recent_alerts": recent_alerts,
            "archive_alerts": archive_alerts,
            "recent_limit": recent_limit,
            "unread_count": unread_count,
            "total_count": stats.get("total_count", len(alerts)),
            "stats": stats,
            "ntfy_topic": settings.NTFY_TOPIC
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

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
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
    tuya_sum = tuya_service.get_summary()
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "active_page": "settings",
            "title": "Impostazioni & Sistema • Weather Hub",
            "station_model": station_model,
            "batt_wh65": batt_wh65,
            "aton_sn": settings.ATON_SN,
            "aton_enabled": settings.ATON_ENABLED,
            "thinq_enabled": settings.LG_THINQ_ENABLED,
            "smartthings_enabled": settings.SMARTTHINGS_ENABLED,
            "tuya_enabled": settings.TUYA_ENABLED,
            "tuya_summary": tuya_sum,
            "tuya_devices": tuya_sum.get("all_devices", []),
            "sensor_aliases": aliases,
            "detected_sensors": detected_sensors,
            "db_stats": get_database_stats(),
            "ntfy_topic": settings.NTFY_TOPIC
        }
    )

if __name__ == "__main__":
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
