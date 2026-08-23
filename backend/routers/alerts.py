import logging
from typing import Optional
from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse

from backend.config import settings
from backend.notifier import notifier
from backend.alert_engine import engine
from backend.database import (
    get_alert_logs, get_unread_alerts_count, mark_alert_as_read, mark_all_alerts_as_read,
    delete_alert_log, clear_all_alert_logs,
    save_push_subscription, delete_push_subscription, get_all_push_subscriptions
)

logger = logging.getLogger("weather_hub")

router = APIRouter(tags=["Alerts & Notifications"])

@router.get("/api/alerts")
async def api_alerts(limit: int = 50, unread_only: bool = False):
    alerts = get_alert_logs(limit=limit, unread_only=unread_only)
    unread_count = get_unread_alerts_count()
    return {
        "alerts": alerts,
        "unread_count": unread_count,
        "total_count": len(alerts)
    }

@router.get("/api/alerts/unread-count")
async def api_alerts_unread_count():
    return {"unread_count": get_unread_alerts_count()}

@router.post("/api/alerts/{alert_id}/read")
async def api_mark_alert_read(alert_id: int):
    success = mark_alert_as_read(alert_id)
    return {"status": "ok" if success else "not_found", "unread_count": get_unread_alerts_count()}

@router.post("/api/alerts/mark-all-read")
@router.post("/api/alerts/mark-read-all")
async def api_mark_all_alerts_read():
    marked = mark_all_alerts_as_read()
    return {"status": "ok", "marked": marked, "unread_count": 0}

@router.delete("/api/alerts/{alert_id}")
async def api_delete_alert(alert_id: int):
    success = delete_alert_log(alert_id)
    return {"status": "ok" if success else "not_found", "unread_count": get_unread_alerts_count()}

@router.post("/api/alerts/clear-all")
async def api_clear_all_alerts():
    cleared = clear_all_alert_logs()
    return {"status": "ok", "cleared": cleared, "unread_count": 0}

# --- Web Push (PWA iOS / Android / Desktop) Endpoints ---

@router.get("/api/push/vapid-public-key")
async def api_push_vapid_key():
    key = notifier.get_vapid_public_key()
    if not key:
        return JSONResponse({"error": "VAPID non pronto"}, status_code=503)
    return {"public_key": key}

@router.post("/api/push/subscribe")
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

@router.post("/api/push/unsubscribe")
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

@router.get("/api/push/status")
async def api_push_status():
    subs = get_all_push_subscriptions()
    return {
        "enabled": bool(notifier.get_vapid_public_key()),
        "devices_count": len(subs),
        "vapid_public_key": notifier.get_vapid_public_key()
    }

@router.post("/api/test-alert")
async def api_test_alert(alert_type: str = Query("record")):
    if alert_type == "civil_protection":
        title = f"⚠️ Test Allerta Protezione Civile - {settings.LOCATION_NAME}"
        message = f"🛡️ [TEST] Allerta Arancione per Rischio Temporali e Idrogeologico per la giornata di domani."
        tags = ["warning", "rotating_light"]
        priority = "urgent"
    else:
        title = "🔔 Test Notifiche Weather Hub"
        message = "Se leggi questo messaggio, le Notifiche Push PWA (iOS/Android/PC) e ntfy funzionano alla perfezione!"
        tags = ["bell"]
        priority = "high"

    notifier.send_alert(
        alert_type=alert_type,
        title=title,
        message=message,
        priority=priority,
        tags=tags
    )
    return {
        "status": "sent",
        "devices_notified": len(get_all_push_subscriptions()),
        "ntfy_topic": settings.NTFY_TOPIC
    }

@router.post("/api/daily-digest/send")
async def api_send_daily_digest():
    """Invia manualmente o via test la notifica 'Buongiorno Meteo' del mattino."""
    res = engine.send_daily_digest()
    return res
