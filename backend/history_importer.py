import os
import json
import time
import math
import logging
import asyncio
import urllib.request
import urllib.error
from datetime import datetime, date, timedelta, timezone
from typing import Dict, Any, Optional, List, Tuple, Callable
from concurrent.futures import ThreadPoolExecutor

from backend.config import settings
from backend.database import get_connection, deg_to_compass, calc_dew_point, RECORD_DEFINITIONS, rebuild_all_historical_monthly_summaries
from backend.analytics import calc_vpd

logger = logging.getLogger("weather_hub.importer")

WU_PUBLIC_API_KEY = "e1f10a1e78da46f5b10a1e78da96f525"
DEFAULT_STATION_ID = "ICORIG10"
EARLIEST_STATION_DATE = date(2022, 7, 9)

class WeatherHistoryImporter:
    """
    Gestisce il recupero, parsing, normalizzazione e salvataggio dello storico meteorologico
    pluriennale da Weather Underground (stazione ICORIG10) ed Ecowitt nel database SQLite locale.
    """
    def __init__(self):
        self.is_running: bool = False
        self.progress_pct: float = 0.0
        self.current_date_str: Optional[str] = None
        self.total_days: int = 0
        self.processed_days: int = 0
        self.records_inserted: int = 0
        self.extremes_updated: int = 0
        self.status_message: str = "In attesa"
        self.start_time: Optional[float] = None
        self.error_message: Optional[str] = None
        self._lock = asyncio.Lock()

    def get_status(self) -> Dict[str, Any]:
        elapsed = round(time.time() - self.start_time, 1) if (self.start_time and self.is_running) else None
        return {
            "is_running": self.is_running,
            "progress_pct": round(self.progress_pct, 1),
            "current_date": self.current_date_str,
            "processed_days": self.processed_days,
            "total_days": self.total_days,
            "records_inserted": self.records_inserted,
            "extremes_updated": self.extremes_updated,
            "status_message": self.status_message,
            "elapsed_seconds": elapsed,
            "error_message": self.error_message
        }

    @staticmethod
    def _fetch_json(url: str, max_retries: int = 3, timeout_sec: int = 15) -> Optional[Dict[str, Any]]:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json"
            }
        )
        for attempt in range(1, max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                    if resp.status == 200:
                        raw = resp.read().decode("utf-8")
                        return json.loads(raw)
            except urllib.error.HTTPError as e:
                if e.code == 404 or e.code == 204:
                    return None
                if attempt == max_retries:
                    logger.warning(f"[IMPORTER] HTTP Error {e.code} for {url}")
                    return None
                time.sleep(1.0 * attempt)
            except Exception as e:
                if attempt == max_retries:
                    logger.warning(f"[IMPORTER] Request error: {e} for {url}")
                    return None
                time.sleep(1.0 * attempt)
        return None

    def fetch_day_hourly(self, station_id: str, day_dt: date) -> List[Dict[str, Any]]:
        """Recupera le osservazioni orarie (~24 campioni) per un dato giorno."""
        dt_str = day_dt.strftime("%Y%m%d")
        url = f"https://api.weather.com/v2/pws/history/hourly?stationId={station_id}&format=json&units=m&date={dt_str}&apiKey={WU_PUBLIC_API_KEY}"
        data = self._fetch_json(url)
        if not data or "observations" not in data:
            return []
        return data.get("observations", [])

    def fetch_day_summary(self, station_id: str, day_dt: date) -> Optional[Dict[str, Any]]:
        """Recupera il riassunto giornaliero (estremi aggregati del giorno)."""
        dt_str = day_dt.strftime("%Y%m%d")
        url = f"https://api.weather.com/v2/pws/history/daily?stationId={station_id}&format=json&units=m&date={dt_str}&apiKey={WU_PUBLIC_API_KEY}"
        data = self._fetch_json(url)
        if not data or "observations" not in data or len(data["observations"]) == 0:
            return None
        return data["observations"][0]

    def _normalize_observation(self, obs: Dict[str, Any], day_summary: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Normalizza una lettura oraria da Weather Underground nel formato dello schema `weather_records`.
        """
        obs_utc_str = obs.get("obsTimeUtc")
        if not obs_utc_str:
            epoch = obs.get("epoch")
            if epoch:
                obs_utc_str = datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
            else:
                return None
        else:
            try:
                dt = datetime.fromisoformat(obs_utc_str.replace("Z", "+00:00"))
                obs_utc_str = dt.isoformat()
            except Exception:
                pass

        metric = obs.get("metric", {})
        temp_c = metric.get("tempAvg") if metric.get("tempAvg") is not None else metric.get("tempHigh")
        hum = obs.get("humidityAvg") if obs.get("humidityAvg") is not None else obs.get("humidityHigh")
        dew_c = metric.get("dewptAvg") if metric.get("dewptAvg") is not None else metric.get("dewptHigh")
        if dew_c is None and temp_c is not None and hum is not None:
            dew_c = calc_dew_point(temp_c, hum)

        wind_spd = metric.get("windspeedAvg") if metric.get("windspeedAvg") is not None else metric.get("windspeedHigh")
        wind_gust = metric.get("windgustHigh") if metric.get("windgustHigh") is not None else metric.get("windgustAvg")
        wind_dir = obs.get("winddirAvg")

        press = metric.get("pressureMax") if metric.get("pressureMax") is not None else metric.get("pressureMin")
        rain_rate = metric.get("precipRate", 0.0)
        daily_rain = metric.get("precipTotal", 0.0)

        if (daily_rain is None or daily_rain == 0.0) and day_summary:
            sum_metric = day_summary.get("metric", {})
            if sum_metric.get("precipTotal") and sum_metric.get("precipTotal") > 0:
                daily_rain = float(sum_metric.get("precipTotal"))

        solar = obs.get("solarRadiationHigh")
        uv = obs.get("uvHigh")
        vpd_val = calc_vpd(temp_c, hum) if (temp_c is not None and hum is not None) else None

        max_daily_gust = None
        if day_summary:
            sum_metric = day_summary.get("metric", {})
            max_daily_gust = sum_metric.get("windgustHigh")

        return {
            "timestamp": obs_utc_str,
            "temp_c": round(float(temp_c), 1) if temp_c is not None else None,
            "humidity": round(float(hum)) if hum is not None else None,
            "dew_point_c": round(float(dew_c), 1) if dew_c is not None else None,
            "temp_in_c": None,
            "humidity_in": None,
            "pressure_rel_hpa": round(float(press), 1) if press is not None else None,
            "pressure_abs_hpa": None,
            "wind_speed_kmh": round(float(wind_spd), 1) if wind_spd is not None else None,
            "wind_gust_kmh": round(float(wind_gust), 1) if wind_gust is not None else None,
            "wind_dir_deg": int(wind_dir) if wind_dir is not None else None,
            "max_daily_gust_kmh": round(float(max_daily_gust), 1) if max_daily_gust is not None else None,
            "rain_rate_mm_hr": round(float(rain_rate), 1) if rain_rate is not None else 0.0,
            "daily_rain_mm": round(float(daily_rain), 1) if daily_rain is not None else 0.0,
            "event_rain_mm": None,
            "yearly_rain_mm": None,
            "solar_radiation": round(float(solar), 1) if solar is not None else None,
            "uv_index": int(uv) if uv is not None else None,
            "vpd": vpd_val,
            "lightning_count": None,
            "lightning_distance_km": None,
            "soil_moisture_json": "{}",
            "raw_data_json": json.dumps({"source": "wunderground_backfill", "station": obs.get("stationID")})
        }

    async def run_full_backfill(
        self,
        station_id: str = DEFAULT_STATION_ID,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        concurrency: int = 4
    ) -> Dict[str, Any]:
        """
        Esegue il backfill asincrono completo dall'intervallo specificato ad oggi.
        """
        if self.is_running:
            return {"status": "already_running", "message": "Importazione già in corso."}

        async with self._lock:
            self.is_running = True
            self.progress_pct = 0.0
            self.processed_days = 0
            self.records_inserted = 0
            self.extremes_updated = 0
            self.error_message = None
            self.start_time = time.time()
            self.status_message = "Avvio importazione archivio storico..."

        if start_date is None:
            start_date = EARLIEST_STATION_DATE
        if end_date is None:
            end_date = settings.now_local().date()

        total_days = (end_date - start_date).days + 1
        self.total_days = max(1, total_days)

        logger.info(f"[IMPORTER] Avvio backfill da {start_date} a {end_date} ({self.total_days} giorni) per stazione {station_id}")

        all_days = [start_date + timedelta(days=i) for i in range(self.total_days)]

        try:
            chunk_size = concurrency * 3
            loop = asyncio.get_running_loop()

            for i in range(0, len(all_days), chunk_size):
                chunk = all_days[i : i + chunk_size]
                self.current_date_str = chunk[0].strftime("%Y-%m-%d")
                self.status_message = f"Download dati da {chunk[0].strftime('%d/%m/%Y')} a {chunk[-1].strftime('%d/%m/%Y')}..."

                with ThreadPoolExecutor(max_workers=concurrency) as executor:
                    def _fetch_single_day(d: date):
                        sum_data = self.fetch_day_summary(station_id, d)
                        hourly_data = self.fetch_day_hourly(station_id, d)
                        return d, sum_data, hourly_data

                    results = await loop.run_in_executor(
                        executor, lambda: list(executor.map(_fetch_single_day, chunk))
                    )

                batch_records_to_insert = []
                for d, sum_data, hourly_data in results:
                    self.processed_days += 1
                    if hourly_data:
                        for obs in hourly_data:
                            norm = self._normalize_observation(obs, sum_data)
                            if norm:
                                batch_records_to_insert.append(norm)
                    elif sum_data:
                        norm = self._normalize_observation(sum_data, sum_data)
                        if norm:
                            batch_records_to_insert.append(norm)

                if batch_records_to_insert:
                    inserted = self._insert_records_batch(batch_records_to_insert)
                    self.records_inserted += inserted

                self.progress_pct = min(99.0, (self.processed_days / self.total_days) * 100.0)
                await asyncio.sleep(0.02)

            self.status_message = "Ricalcolo Albo dei Record e statistiche climatiche..."
            rebuilt_count = self.rebuild_records_and_extremes()
            self.extremes_updated = rebuilt_count

            self.progress_pct = 100.0
            self.status_message = f"Completato con successo! {self.records_inserted} record storici inseriti, Albo Record aggiornato."
            logger.info(f"[IMPORTER] {self.status_message}")

        except Exception as e:
            logger.error(f"[IMPORTER] Errore durante il backfill: {e}", exc_info=True)
            self.error_message = str(e)
            self.status_message = f"Errore: {e}"
        finally:
            self.is_running = False

        return self.get_status()

    def _insert_records_batch(self, records: List[Dict[str, Any]]) -> int:
        if not records:
            return 0

        conn = get_connection()
        cursor = conn.cursor()
        inserted_count = 0

        try:
            conn.execute("BEGIN TRANSACTION;")
            for r in records:
                cursor.execute("""
                    INSERT OR IGNORE INTO weather_records (
                        timestamp, temp_c, humidity, dew_point_c, temp_in_c, humidity_in,
                        pressure_rel_hpa, pressure_abs_hpa, wind_speed_kmh, wind_gust_kmh,
                        wind_dir_deg, max_daily_gust_kmh, rain_rate_mm_hr, daily_rain_mm,
                        event_rain_mm, yearly_rain_mm, solar_radiation, uv_index, vpd,
                        lightning_count, lightning_distance_km, soil_moisture_json, raw_data_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    r["timestamp"], r["temp_c"], r["humidity"], r["dew_point_c"],
                    r["temp_in_c"], r["humidity_in"], r["pressure_rel_hpa"], r["pressure_abs_hpa"],
                    r["wind_speed_kmh"], r["wind_gust_kmh"], r["wind_dir_deg"], r["max_daily_gust_kmh"],
                    r["rain_rate_mm_hr"], r["daily_rain_mm"], r["event_rain_mm"], r["yearly_rain_mm"],
                    r["solar_radiation"], r["uv_index"], r["vpd"], r["lightning_count"],
                    r["lightning_distance_km"], r["soil_moisture_json"], r["raw_data_json"]
                ))
                if cursor.rowcount > 0:
                    inserted_count += 1

            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"[IMPORTER] Batch insert error: {e}")
        finally:
            conn.close()

        return inserted_count

    def rebuild_records_and_extremes(self) -> int:
        conn = get_connection()
        cursor = conn.cursor()
        records_found = 0

        try:
            # 1. Temperatura Massima Assoluta
            cursor.execute("""
                SELECT temp_c, timestamp FROM weather_records
                WHERE temp_c IS NOT NULL AND temp_c < 65.0
                ORDER BY temp_c DESC, timestamp ASC LIMIT 1
            """)
            row = cursor.fetchone()
            if row and row["temp_c"] is not None:
                self._set_extreme(cursor, "temp_max", "temperature", "Temperatura Massima", float(row["temp_c"]), "°C", row["timestamp"])
                records_found += 1

            # 2. Temperatura Minima Assoluta
            cursor.execute("""
                SELECT temp_c, timestamp FROM weather_records
                WHERE temp_c IS NOT NULL AND temp_c > -50.0
                ORDER BY temp_c ASC, timestamp ASC LIMIT 1
            """)
            row = cursor.fetchone()
            if row and row["temp_c"] is not None:
                self._set_extreme(cursor, "temp_min", "temperature", "Temperatura Minima", float(row["temp_c"]), "°C", row["timestamp"])
                records_found += 1

            # 3. Notte Tropicale Record (Minima Più Alta mai registrata in un giorno)
            cursor.execute("""
                SELECT date(timestamp) as day_str, MIN(temp_c) as day_min, MIN(timestamp) as ts
                FROM weather_records
                WHERE temp_c IS NOT NULL
                GROUP BY date(timestamp)
                HAVING COUNT(*) >= 4
                ORDER BY day_min DESC LIMIT 1
            """)
            row = cursor.fetchone()
            if row and row["day_min"] is not None:
                self._set_extreme(
                    cursor, "temp_min_highest", "temperature", "Minima Più Alta (Notte Tropicale)",
                    float(row["day_min"]), "°C", row["ts"], {"date": row["day_str"]}
                )
                records_found += 1

            # 4. Punto di Rugiada Massimo (Dew Point Max)
            cursor.execute("""
                SELECT dew_point_c, timestamp FROM weather_records
                WHERE dew_point_c IS NOT NULL AND dew_point_c < 45.0
                ORDER BY dew_point_c DESC, timestamp ASC LIMIT 1
            """)
            row = cursor.fetchone()
            if row and row["dew_point_c"] is not None:
                self._set_extreme(cursor, "dew_point_max", "temperature", "Punto di Rugiada Max", float(row["dew_point_c"]), "°C", row["timestamp"])
                records_found += 1

            # 5. Raffica di Vento Massima (Wind Gust Max)
            cursor.execute("""
                SELECT wind_gust_kmh, wind_dir_deg, timestamp FROM weather_records
                WHERE wind_gust_kmh IS NOT NULL AND wind_gust_kmh < 300.0
                ORDER BY wind_gust_kmh DESC, timestamp ASC LIMIT 1
            """)
            row = cursor.fetchone()
            if row and row["wind_gust_kmh"] is not None:
                dir_str = deg_to_compass(row["wind_dir_deg"]) if row["wind_dir_deg"] is not None else "--"
                self._set_extreme(cursor, "wind_gust_max", "wind", "Raffica di Vento Max", float(row["wind_gust_kmh"]), "km/h", row["timestamp"], {"dir": dir_str})
                records_found += 1

            # 6. Velocità Media Vento Massima
            cursor.execute("""
                SELECT wind_speed_kmh, wind_dir_deg, timestamp FROM weather_records
                WHERE wind_speed_kmh IS NOT NULL AND wind_speed_kmh < 250.0
                ORDER BY wind_speed_kmh DESC, timestamp ASC LIMIT 1
            """)
            row = cursor.fetchone()
            if row and row["wind_speed_kmh"] is not None:
                dir_str = deg_to_compass(row["wind_dir_deg"]) if row["wind_dir_deg"] is not None else "--"
                self._set_extreme(cursor, "wind_speed_max", "wind", "Velocità Media Vento Max", float(row["wind_speed_kmh"]), "km/h", row["timestamp"], {"dir": dir_str})
                records_found += 1

            # 7. Intensità di Pioggia Massima (Rain Rate Max)
            cursor.execute("""
                SELECT rain_rate_mm_hr, timestamp FROM weather_records
                WHERE rain_rate_mm_hr IS NOT NULL AND rain_rate_mm_hr > 0.0 AND rain_rate_mm_hr < 500.0
                ORDER BY rain_rate_mm_hr DESC, timestamp ASC LIMIT 1
            """)
            row = cursor.fetchone()
            if row and row["rain_rate_mm_hr"] is not None:
                self._set_extreme(cursor, "rain_rate_max", "rain", "Intensità Pioggia Max", float(row["rain_rate_mm_hr"]), "mm/h", row["timestamp"])
                records_found += 1

            # 8. Accumulo Pioggia Giornaliero Massimo
            cursor.execute("""
                SELECT date(timestamp) as day_str, MAX(daily_rain_mm) as max_day_rain, MAX(timestamp) as ts
                FROM weather_records
                WHERE daily_rain_mm IS NOT NULL AND daily_rain_mm > 0.0 AND daily_rain_mm < 500.0
                GROUP BY date(timestamp)
                ORDER BY max_day_rain DESC LIMIT 1
            """)
            row = cursor.fetchone()
            if row and row["max_day_rain"] is not None:
                self._set_extreme(cursor, "rain_daily_max", "rain", "Accumulo Giornaliero Max", float(row["max_day_rain"]), "mm", row["ts"], {"date": row["day_str"]})
                records_found += 1

            # 9. Pressione Massima
            cursor.execute("""
                SELECT pressure_rel_hpa, timestamp FROM weather_records
                WHERE pressure_rel_hpa IS NOT NULL AND pressure_rel_hpa > 900.0 AND pressure_rel_hpa < 1100.0
                ORDER BY pressure_rel_hpa DESC, timestamp ASC LIMIT 1
            """)
            row = cursor.fetchone()
            if row and row["pressure_rel_hpa"] is not None:
                self._set_extreme(cursor, "pressure_max", "pressure", "Pressione Massima", float(row["pressure_rel_hpa"]), "hPa", row["timestamp"])
                records_found += 1

            # 10. Pressione Minima
            cursor.execute("""
                SELECT pressure_rel_hpa, timestamp FROM weather_records
                WHERE pressure_rel_hpa IS NOT NULL AND pressure_rel_hpa > 900.0 AND pressure_rel_hpa < 1100.0
                ORDER BY pressure_rel_hpa ASC, timestamp ASC LIMIT 1
            """)
            row = cursor.fetchone()
            if row and row["pressure_rel_hpa"] is not None:
                self._set_extreme(cursor, "pressure_min", "pressure", "Pressione Minima", float(row["pressure_rel_hpa"]), "hPa", row["timestamp"])
                records_found += 1

            # 11. Indice UV Massimo
            cursor.execute("""
                SELECT uv_index, timestamp FROM weather_records
                WHERE uv_index IS NOT NULL AND uv_index > 0 AND uv_index <= 18
                ORDER BY uv_index DESC, timestamp ASC LIMIT 1
            """)
            row = cursor.fetchone()
            if row and row["uv_index"] is not None:
                self._set_extreme(cursor, "uv_max", "solar", "Indice UV Massimo", float(row["uv_index"]), "UV", row["timestamp"])
                records_found += 1

            # 12. Radiazione Solare Massima
            cursor.execute("""
                SELECT solar_radiation, timestamp FROM weather_records
                WHERE solar_radiation IS NOT NULL AND solar_radiation > 0.0 AND solar_radiation <= 2000.0
                ORDER BY solar_radiation DESC, timestamp ASC LIMIT 1
            """)
            row = cursor.fetchone()
            if row and row["solar_radiation"] is not None:
                self._set_extreme(cursor, "solar_max", "solar", "Radiazione Solare Max", float(row["solar_radiation"]), "W/m²", row["timestamp"])
                records_found += 1

            conn.commit()
        finally:
            conn.close()

        # Ricalcola anche tutti i riepiloghi mensili e i record mensili storici
        try:
            rebuild_all_historical_monthly_summaries()
        except Exception as e_m:
            logger.warning(f"[IMPORTER] Errore aggiornamento record mensili: {e_m}")

        return records_found

    @staticmethod
    def _set_extreme(
        cursor, record_key: str, category: str, title: str,
        value: float, unit: str, timestamp: str, details: Optional[Dict[str, Any]] = None
    ):
        cursor.execute("""
            INSERT OR REPLACE INTO weather_extremes (record_key, category, title, value, unit, timestamp, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (record_key, category, title, value, unit, timestamp, json.dumps(details or {})))


history_importer = WeatherHistoryImporter()
