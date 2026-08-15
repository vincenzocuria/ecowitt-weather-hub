import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import requests

from backend.config import settings
from backend.database import save_energy_reading
from backend.alert_engine import engine

logger = logging.getLogger("weather_hub.aton")

class AtonService:
    def __init__(self):
        self.base_url = "https://www.atonstorage.com/atonTC/"
        self.login_url = self.base_url + "index.php"
        self.monitor_url = self.base_url + "get_monitor.php"
        
        self.session: Optional[requests.Session] = None
        self.latest_data: Optional[Dict[str, Any]] = None
        self.last_fetch_time: float = 0.0
        self.is_connected: bool = False
        self.failed_attempts: int = 0
        self._running: bool = False

    def _ensure_session(self) -> bool:
        """Verifica o crea la sessione autenticata su Aton Server."""
        if not settings.ATON_ENABLED or not settings.ATON_USERNAME or not settings.ATON_PASSWORD:
            return False

        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Origin": "https://www.atonstorage.com",
                "Referer": self.base_url + "login.php",
                "Content-Type": "application/x-www-form-urlencoded"
            })

        # Test rapido o login
        try:
            # Step 1: Pre-carica login.php per ottenere PHPSESSID se non presente
            self.session.get(self.base_url + "login.php", timeout=10)
            
            # Step 2: POST index.php con credenziali
            payload = {
                "username": settings.ATON_USERNAME,
                "password": settings.ATON_PASSWORD
            }
            r_login = self.session.post(self.login_url, data=payload, allow_redirects=True, timeout=15)
            
            if r_login.status_code == 200 and "login.php" not in r_login.url:
                logger.info(f"✅ [ATON] Autenticazione riuscita per utente {settings.ATON_USERNAME}")
                return True
            else:
                logger.warning(f"⚠️ [ATON] Login non riuscito (Status: {r_login.status_code}, URL: {r_login.url})")
                return False
        except Exception as e:
            logger.error(f"❌ [ATON] Errore di connessione durante login: {e}")
            return False

    def fetch_telemetry_sync(self) -> Optional[Dict[str, Any]]:
        """Esegue il fetch sincrono dei dati di monitoraggio da Aton."""
        if not settings.ATON_ENABLED:
            return None

        sn = settings.ATON_SN or "R21MY00735F"
        ts = int(time.time() * 1000)
        url = f"{self.monitor_url}?sn={sn}&_={ts}"

        if self.session is None:
            if not self._ensure_session():
                return None

        try:
            resp = self.session.get(url, timeout=12)
            
            # Se la sessione è scaduta (es. redirect o risposta non valida), riautentica
            if resp.status_code != 200 or "pSolare" not in resp.text:
                logger.info("[ATON] Rinnovo sessione scaduta...")
                if self._ensure_session():
                    resp = self.session.get(url, timeout=12)
                else:
                    return None

            if resp.status_code == 200:
                raw = resp.json()
                return self._parse_telemetry(raw)
        except Exception as e:
            logger.error(f"❌ [ATON] Errore durante richiesta get_monitor: {e}")
            self.session = None # Reset sessione per ritentare al prossimo giro
            return None

    def _parse_telemetry(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Converte e normalizza i campi di telemetria Aton in formato pulito."""
        def safe_float(val, default=0.0):
            try:
                if val is None or val == "":
                    return default
                return float(val)
            except (ValueError, TypeError):
                return default

        p_solare = safe_float(raw.get("pSolare"))
        p_utenze = safe_float(raw.get("pUtenze") or raw.get("pUtenzeReal"))
        p_batteria = safe_float(raw.get("pBatteria"))
        p_rete = safe_float(raw.get("pRete") or raw.get("pReteReal"))
        p_rete_in = safe_float(raw.get("pReteIn"))
        p_rete_out = safe_float(raw.get("pReteOut"))
        soc = safe_float(raw.get("soc"))
        
        # Correzioni e direzione flussi
        # In Aton: pBatteria > 0 = scarica batteria (eroga potenza verso la casa: P_FV + P_Batt = P_Utenze),
        #          pBatteria < 0 = carica batteria (assorbe potenza dal FV/Rete).
        battery_discharging = p_batteria > 0
        battery_charging = p_batteria < 0
        battery_power_abs = abs(p_batteria)
        battery_status = "discharging" if battery_discharging else ("charging" if battery_charging else "idle")

        parsed = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data_aton": raw.get("data"),
            "serial_number": raw.get("serialNumber") or settings.ATON_SN,
            "p_solare": p_solare,
            "p_utenze": p_utenze,
            "p_batteria": p_batteria,
            "battery_power_abs": battery_power_abs,
            "battery_charging": battery_charging,
            "battery_discharging": battery_discharging,
            "battery_status": battery_status,
            "p_rete": p_rete,
            "p_rete_in": p_rete_in,
            "p_rete_out": p_rete_out,
            "soc": min(100.0, max(0.0, soc)),
            "vb": safe_float(raw.get("vb")),
            "ib": safe_float(raw.get("ib")),
            "temp_battery": safe_float(raw.get("temperatura")),
            "string1_v": safe_float(raw.get("string1V")),
            "string1_i": safe_float(raw.get("string1I")),
            "string2_v": safe_float(raw.get("string2V")),
            "string2_i": safe_float(raw.get("string2I")),
            "grid_v": safe_float(raw.get("gridV")),
            "grid_hz": safe_float(raw.get("gridHz")),
            "e_pannelli_wh": safe_float(raw.get("ePannelli")),
            "e_comprata_wh": safe_float(raw.get("eComprata")),
            "e_venduta_wh": safe_float(raw.get("eVenduta")),
            "e_batteria_wh": safe_float(raw.get("eBatteria")),
            "solar_today_kwh": round(safe_float(raw.get("ePannelli")) / 1000.0, 2),
            "bought_today_kwh": round(safe_float(raw.get("eComprata")) / 1000.0, 2),
            "sold_today_kwh": round(safe_float(raw.get("eVenduta")) / 1000.0, 2),
            "raw_data": raw
        }
        return parsed

    async def worker_loop(self):
        """Loop di polling periodico asincrono in background."""
        logger.info(f"🚀 [ATON] Worker avviato (polling ogni {settings.ATON_POLL_INTERVAL_SEC}s per SN: {settings.ATON_SN})")
        self._running = True
        
        while self._running:
            try:
                if settings.ATON_ENABLED:
                    # Esegue il fetch in thread separato per non bloccare l'event loop di FastAPI
                    data = await asyncio.to_thread(self.fetch_telemetry_sync)
                    if data:
                        self.latest_data = data
                        self.last_fetch_time = time.time()
                        self.is_connected = True
                        self.failed_attempts = 0
                        
                        # Salva lettura nel database locale SQLite
                        save_energy_reading(data)
                        
                        # Valuta allarmi energetici
                        engine.evaluate_energy(data)
                    else:
                        self.failed_attempts += 1
                        if self.failed_attempts > 3:
                            self.is_connected = False
            except Exception as e:
                logger.error(f"❌ [ATON] Errore nel loop del worker: {e}", exc_info=True)
                self.is_connected = False

            await asyncio.sleep(max(10, settings.ATON_POLL_INTERVAL_SEC))

    def stop(self):
        self._running = False

aton_service = AtonService()
