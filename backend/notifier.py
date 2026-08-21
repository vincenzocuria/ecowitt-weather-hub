import os
import json
import base64
import logging
import requests
from typing import Dict, Any, Optional
from backend.config import settings
from backend.database import log_alert_db, get_all_push_subscriptions, delete_push_subscription, get_unread_alerts_count

try:
    from py_vapid import Vapid
    from cryptography.hazmat.primitives import serialization
    from pywebpush import webpush, WebPushException
    HAS_WEBPUSH = True
except ImportError:
    HAS_WEBPUSH = False

logger = logging.getLogger("ecowitt_notifier")

class NotificationService:
    def __init__(self):
        self.vapid_private_pem_path = os.path.join(settings.DATA_DIR, "vapid_private.pem")
        self.vapid_public_txt_path = os.path.join(settings.DATA_DIR, "vapid_public_b64.txt")
        self.vapid_public_key_b64: Optional[str] = None
        self._init_vapid()

    def _init_vapid(self):
        """Inizializza o genera la coppia di chiavi VAPID per il Web Push nativo."""
        if not HAS_WEBPUSH:
            logger.warning("[VAPID] pywebpush / py_vapid non disponibili. Web Push disabilitato.")
            return

        try:
            os.makedirs(settings.DATA_DIR, exist_ok=True)
            if os.path.exists(self.vapid_private_pem_path) and os.path.exists(self.vapid_public_txt_path):
                with open(self.vapid_public_txt_path, "r", encoding="utf-8") as f:
                    self.vapid_public_key_b64 = f.read().strip()
                logger.info(f"[VAPID] Chiavi caricate correttamente ({self.vapid_public_key_b64[:12]}...)")
            else:
                logger.info("[VAPID] Generazione nuova coppia di chiavi VAPID per le notifiche PWA...")
                vapid = Vapid()
                vapid.generate_keys()
                
                # Salva file PEM privato
                with open(self.vapid_private_pem_path, "wb") as f:
                    f.write(vapid.private_pem())
                
                # Calcola Public Key base64 url-safe
                raw_pub = vapid.public_key.public_bytes(
                    serialization.Encoding.X962,
                    serialization.PublicFormat.UncompressedPoint
                )
                self.vapid_public_key_b64 = base64.urlsafe_b64encode(raw_pub).decode('utf-8').rstrip('=')
                with open(self.vapid_public_txt_path, "w", encoding="utf-8") as f:
                    f.write(self.vapid_public_key_b64)
                logger.info(f"[VAPID] Nuova chiave pubblica VAPID generata con successo: {self.vapid_public_key_b64}")
        except Exception as e:
            logger.error(f"[VAPID] Errore inizializzazione chiavi VAPID: {e}", exc_info=True)

    def get_vapid_public_key(self) -> Optional[str]:
        return self.vapid_public_key_b64

    def _send_web_push(self, alert_type: str, title: str, message: str, extra_data: Optional[Dict[str, Any]] = None):
        """Invia notifiche push native a tutti i dispositivi PWA (iOS / Android / Desktop) iscritti."""
        if not HAS_WEBPUSH or not self.vapid_public_key_b64 or not os.path.exists(self.vapid_private_pem_path):
            return

        subs = get_all_push_subscriptions()
        if not subs:
            return

        unread_count = get_unread_alerts_count()
        payload = json.dumps({
            "title": title,
            "body": message,
            "icon": "/static/icons/icon-192.png",
            "badge": "/static/icons/badge-96.png",
            "tag": f"meteo-{alert_type}",
            "unread_count": unread_count,
            "data": {
                "url": "/alerts-page",
                "alert_type": alert_type,
                "unread_count": unread_count,
                "extra": extra_data or {}
            }
        })

        for sub in subs:
            endpoint = sub.get("endpoint")
            p256dh = sub.get("p256dh")
            auth = sub.get("auth")
            if not endpoint or not p256dh or not auth:
                continue

            sub_info = {
                "endpoint": endpoint,
                "keys": {
                    "p256dh": p256dh,
                    "auth": auth
                }
            }
            try:
                webpush(
                    subscription_info=sub_info,
                    data=payload,
                    vapid_private_key=self.vapid_private_pem_path,
                    vapid_claims={"sub": settings.VAPID_CLAIM_EMAIL},
                    ttl=3600
                )
                logger.info(f"[WEBPUSH] Notifica inviata con successo al dispositivo {endpoint[:35]}...")
            except WebPushException as ex:
                logger.warning(f"[WEBPUSH] Errore invio notifica a {endpoint[:35]}...: {ex}")
                # Rimozione automatica dei dispositivi disinstallati/scaduti (HTTP 404 o 410)
                if ex.response is not None and ex.response.status_code in (404, 410):
                    logger.info(f"[WEBPUSH] Rimozione sottoscrizione scaduta: {endpoint[:35]}...")
                    delete_push_subscription(endpoint)
            except Exception as e:
                logger.error(f"[WEBPUSH] Errore generico invio notifica: {e}")

    def send_alert(
        self,
        alert_type: str,
        title: str,
        message: str,
        priority: str = "high",
        extra_data: Optional[Dict[str, str]] = None
    ):
        """
        Invia notifiche push via Web Push nativo (PWA) e via ntfy.sh (se attivo),
        registrando l'evento nel database storico.
        """
        logger.info(f"[NOTIFICA] [{alert_type}] {title}: {message}")
        log_alert_db(alert_type, title, message, extra_data)

        # 1. Web Push Nativo PWA
        try:
            self._send_web_push(alert_type, title, message, extra_data)
        except Exception as e:
            logger.error(f"[WEBPUSH] Eccezione non gestita: {e}")

        # 2. ntfy.sh (invio JSON compatibile al 100% con caratteri UTF-8, emoji e formattazione)
        if settings.ENABLE_NTFY and settings.NTFY_TOPIC:
            try:
                tags = self._get_tags(alert_type).split(",")
                prio_val = 5 if priority == "urgent" else (4 if priority == "high" else 3)
                ntfy_payload = {
                    "topic": settings.NTFY_TOPIC,
                    "title": title,
                    "message": message,
                    "priority": prio_val,
                    "tags": tags
                }
                # Icona personalizzata per ntfy
                icon_url = self.get_icon_url_for_alert(alert_type)
                ntfy_payload["icon"] = icon_url

                if settings.NTFY_CLICK_URL:
                    ntfy_payload["click"] = settings.NTFY_CLICK_URL
                    ntfy_payload["actions"] = [
                        {
                            "action": "view",
                            "label": "Apri Hub Meteo",
                            "url": settings.NTFY_CLICK_URL
                        }
                    ]
                res = requests.post(
                    "https://ntfy.sh",
                    json=ntfy_payload,
                    headers={"Content-Type": "application/json; charset=utf-8"},
                    timeout=8
                )
                if res.status_code == 200:
                    logger.info(f"[NTFY] Notifica inviata con successo su topic '{settings.NTFY_TOPIC}'")
                else:
                    logger.warning(f"[NTFY] Risposta server ntfy HTTP {res.status_code}: {res.text}")
            except Exception as e:
                logger.error(f"[NTFY] Errore invio notifica ntfy: {e}")

    @staticmethod
    def get_icon_url_for_alert(alert_type: str) -> str:
        """Restituisce l'URL pubblico dell'icona 3D ad alta definizione per l'allerta ntfy."""
        if settings.NTFY_ICON_URL:
            return settings.NTFY_ICON_URL

        # Se NTFY_CLICK_URL è un dominio pubblico HTTPS (non localhost/IP privato), usa l'icona locale
        if settings.NTFY_CLICK_URL and settings.NTFY_CLICK_URL.startswith("https://"):
            domain_lower = settings.NTFY_CLICK_URL.lower()
            if not any(private in domain_lower for private in ("localhost", "127.0.0.1", "192.168.", "10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.", "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.")):
                return f"{settings.NTFY_CLICK_URL.rstrip('/')}/static/icons/ntfy-icon.png"

        # Icone 3D ad alta definizione dedicate per ogni tipologia di allerta meteo (Microsoft Fluent 3D via jsDelivr CDN)
        cdn_base = "https://cdn.jsdelivr.net/gh/microsoft/fluentui-emoji@main/assets"
        icons_map = {
            "lightning": f"{cdn_base}/High%20voltage/3D/high_voltage_3d.png",
            "storm": f"{cdn_base}/Cloud%20with%20lightning%20and%20rain/3D/cloud_with_lightning_and_rain_3d.png",
            "rain": f"{cdn_base}/Cloud%20with%20rain/3D/cloud_with_rain_3d.png",
            "rain_start": f"{cdn_base}/Sun%20behind%20rain%20cloud/3D/sun_behind_rain_cloud_3d.png",
            "rain_forecast": f"{cdn_base}/Umbrella%20with%20rain%20drops/3D/umbrella_with_rain_drops_3d.png",
            "freeze": f"{cdn_base}/Snowflake/3D/snowflake_3d.png",
            "heatwave": f"{cdn_base}/Fire/3D/fire_3d.png",
            "wind_spike": f"{cdn_base}/Dashing%20away/3D/dashing_away_3d.png",
            "soil_dry": f"{cdn_base}/Seedling/3D/seedling_3d.png",
            "soil_wet": f"{cdn_base}/Droplet/3D/droplet_3d.png",
            "soil_recovered": f"{cdn_base}/Seedling/3D/seedling_3d.png",
            "tropical_night": f"{cdn_base}/Palm%20tree/3D/palm_tree_3d.png",
            "record": f"{cdn_base}/Trophy/3D/trophy_3d.png",
            "digest": f"{cdn_base}/Hot%20beverage/3D/hot_beverage_3d.png",
            "offline": f"{cdn_base}/Satellite%20antenna/3D/satellite_antenna_3d.png",
            "online": f"{cdn_base}/Check%20mark%20button/3D/check_mark_button_3d.png",
            "battery_low": f"{cdn_base}/Battery/3D/battery_3d.png",
            "uv_extreme": f"{cdn_base}/Sun/3D/sun_3d.png",
            "anomaly": f"{cdn_base}/Warning/3D/warning_3d.png",
            "leak": f"{cdn_base}/Droplet/3D/droplet_3d.png"
        }
        return icons_map.get(alert_type, f"{cdn_base}/Sun%20behind%20cloud/3D/sun_behind_cloud_3d.png")

    @staticmethod
    def _get_tags(alert_type: str) -> str:
        mapping = {
            "offline": "warning,rotating_light,satellite",
            "online": "white_check_mark,satellite",
            "record": "trophy,star,tada",
            "lightning": "warning,zap",
            "soil_dry": "herb,droplet,warning",
            "soil_wet": "droplet,warning,herb",
            "soil_recovered": "seedling,white_check_mark",
            "tropical_night": "palm_tree,hot_face,crescent_moon",
            "freeze": "snowflake,cold_face",
            "heatwave": "hot_face,sunny",
            "rain": "cloud_with_rain",
            "rain_start": "cloud_with_rain,droplet",
            "rain_forecast": "umbrella,cloud_with_rain",
            "storm": "cyclone,thunder_cloud_and_rain",
            "anomaly": "warning,exclamation",
            "wind_spike": "wind_blowing_face,warning",
            "uv_extreme": "sunglasses,fire",
            "battery_low": "battery,warning",
            "digest": "coffee,sunrise,partly_sunny"
        }
        return mapping.get(alert_type, "loudspeaker")

notifier = NotificationService()
