from __future__ import annotations
import os
import sys
import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
import uvicorn

# Assicura che la root del progetto sia sempre nel PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import settings
from backend.alert_engine import engine
from backend.database import (
    get_latest_reading, get_latest_energy, get_recent_rain_totals
)
from backend.forecast_service import forecast_service
from backend.aton_service import aton_service
from backend.thinq_service import thinq_service
from backend.smartthings_service import smartthings_service
from backend.tuya_service import tuya_service
from backend.device_scheduler import device_scheduler

# Routers modulari
from backend.routers.weather import router as weather_router, build_analytics_context, process_weather_data
from backend.routers.alerts import router as alerts_router
from backend.routers.energy import router as energy_router
from backend.routers.devices import router as devices_router, build_devices_catalog
from backend.routers.system import router as system_router
from backend.routers.views import router as views_router, templates

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
            engine.check_civil_protection_alerts()
            engine.check_daily_digest()
            engine.check_evening_energy_digest()
            engine.check_nightly_maintenance()

            # Automazioni intelligenti Presenza S26 Ultra, Elettrodomestici, Clima & Solare
            latest_w = get_latest_reading() or {}
            latest_e = aton_service.latest_data or get_latest_energy() or {}
            an_ctx = build_analytics_context(latest_w)
            st_sum = smartthings_service.get_summary(latest_e, an_ctx.get("drying_index") if an_ctx else None)
            engine.evaluate_smartthings_automations(st_sum, latest_w, latest_e)

            # Automazioni Climatizzatori LG ThinQ (Spegnimento/Accensione Autonoma & Notifiche)
            if settings.LG_THINQ_ENABLED:
                thinq_devs = thinq_service.get_cached_devices()
                if thinq_devs:
                    await engine.evaluate_climate_automations(
                        thinq_devs,
                        latest_w,
                        latest_e,
                        st_sum.get("presence") if st_sum else None
                    )

            # Automazioni Irrigazione Intelligente (WH51 + Tuya SOP10 + Meteo Predittivo)
            if settings.TUYA_ENABLED:
                fc_rain = 0.0
                try:
                    fc_data = forecast_service.fetch_open_meteo() or {}
                    fc_rain = float(fc_data.get("rain_24h_sum", 0.0) or 0.0)
                except Exception:
                    pass
                recent_rain_mm = 0.0
                try:
                    recent_r = get_recent_rain_totals() or {}
                    recent_rain_mm = float(recent_r.get("rain_48h", 0.0) or 0.0)
                except Exception:
                    pass
                await engine.evaluate_smart_irrigation_automations(
                    weather_data=latest_w,
                    forecast_rain_24h_mm=fc_rain,
                    recent_rain_48h_mm=recent_rain_mm
                )
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
    scheduler_task = asyncio.create_task(device_scheduler.worker_loop())
    yield
    watchdog_task.cancel()
    aton_service.stop()
    aton_task.cancel()
    thinq_service.stop()
    thinq_task.cancel()
    smartthings_task.cancel()
    await smartthings_service.close()
    tuya_task.cancel()
    device_scheduler.stop()
    scheduler_task.cancel()

# Inizializzazione FastAPI
app = FastAPI(title="Ecowitt & Sainlogic Weather Station Hub", lifespan=lifespan)

# CORS Middleware (sicuro e compatibile)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://.*$",
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
                {"error": "Accesso non autorizzato. Fornisci un token valido via X-Auth-Token o cookie."},
                status_code=401
            )
        from urllib.parse import urlencode
        login_url = f"/login?{urlencode({'next': str(request.url.path)})}"
        return RedirectResponse(url=login_url, status_code=303)

    response = await call_next(request)

    # Se l'utente ha usato ?token=... per il primo accesso, salva il cookie per 10 anni
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

# Montaggio Cartelle Risorse Statiche
static_dir = Path(__file__).resolve().parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Registrazione dei Router Modulari
app.include_router(weather_router)
app.include_router(alerts_router)
app.include_router(energy_router)
app.include_router(devices_router)
app.include_router(system_router)
app.include_router(views_router)

if __name__ == "__main__":
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
