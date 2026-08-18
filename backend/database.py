import os
import json
import math
import sqlite3
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone, timedelta
from backend.config import settings

DB_DIR = settings.DATA_DIR
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "weather_history.db")

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=20.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.row_factory = sqlite3.Row
    return conn

def to_local_datetime_str(iso_str: Optional[str], fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Converte una stringa timestamp ISO UTC nel fuso orario locale configurato (default Europe/Rome)."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local_dt = dt.astimezone(settings.get_tz())
        return local_dt.strftime(fmt)
    except Exception:
        return str(iso_str).replace("T", " ")[:19]

# Definizioni dei record tracciati nell'Albo dei Record
RECORD_DEFINITIONS = [
    {"key": "temp_max", "category": "temperature", "title": "Temperatura Massima", "unit": "°C", "type": "max"},
    {"key": "temp_min", "category": "temperature", "title": "Temperatura Minima", "unit": "°C", "type": "min"},
    {"key": "dew_point_max", "category": "temperature", "title": "Punto di Rugiada Max", "unit": "°C", "type": "max"},
    {"key": "wind_gust_max", "category": "wind", "title": "Raffica di Vento Max", "unit": "km/h", "type": "max"},
    {"key": "wind_speed_max", "category": "wind", "title": "Velocità Media Vento Max", "unit": "km/h", "type": "max"},
    {"key": "rain_rate_max", "category": "rain", "title": "Intensità Pioggia Max", "unit": "mm/h", "type": "max"},
    {"key": "rain_daily_max", "category": "rain", "title": "Accumulo Giornaliero Max", "unit": "mm", "type": "max"},
    {"key": "pressure_max", "category": "pressure", "title": "Pressione Massima", "unit": "hPa", "type": "max"},
    {"key": "pressure_min", "category": "pressure", "title": "Pressione Minima", "unit": "hPa", "type": "min"},
    {"key": "uv_max", "category": "solar", "title": "Indice UV Massimo", "unit": "UV", "type": "max"},
    {"key": "solar_max", "category": "solar", "title": "Radiazione Solare Max", "unit": "W/m²", "type": "max"},
    {"key": "lightning_closest", "category": "lightning", "title": "Fulmine Più Vicino", "unit": "km", "type": "min"}
]

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Letture Meteorologiche Principali
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS weather_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            temp_c REAL,
            humidity REAL,
            dew_point_c REAL,
            temp_in_c REAL,
            humidity_in REAL,
            pressure_rel_hpa REAL,
            pressure_abs_hpa REAL,
            wind_speed_kmh REAL,
            wind_gust_kmh REAL,
            wind_dir_deg INTEGER,
            max_daily_gust_kmh REAL,
            rain_rate_mm_hr REAL,
            daily_rain_mm REAL,
            event_rain_mm REAL,
            yearly_rain_mm REAL,
            solar_radiation REAL,
            uv_index INTEGER,
            vpd REAL,
            lightning_count INTEGER,
            lightning_distance_km REAL,
            lightning_last_time TEXT,
            soil_moisture_json TEXT,
            raw_data_json TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON weather_records (timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_temp ON weather_records (temp_c)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wind_gust ON weather_records (wind_gust_kmh)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rain_rate ON weather_records (rain_rate_mm_hr)")

    # 2. Albo dei Record Attuali
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS weather_extremes (
            record_key TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            value REAL NOT NULL,
            unit TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            details_json TEXT
        )
    """)

    # 3. Cronologia dei Record Battuti nel Tempo
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS records_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_key TEXT NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            old_value REAL,
            new_value REAL NOT NULL,
            unit TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            details_json TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_record_key ON records_history (record_key)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rec_timestamp ON records_history (timestamp)")

    # 4. Log Allarmi / Notifiche
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alert_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            data_json TEXT,
            is_read INTEGER DEFAULT 0
        )
    """)
    try:
        cursor.execute("ALTER TABLE alert_logs ADD COLUMN is_read INTEGER DEFAULT 0")
    except Exception:
        pass
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_alert_is_read ON alert_logs (is_read)")

    # 5. Sottoscrizioni Web Push PWA (iOS / Android / Desktop)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint TEXT UNIQUE NOT NULL,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            user_agent TEXT,
            created_at TEXT NOT NULL,
            last_seen TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_push_endpoint ON push_subscriptions (endpoint)")

    # 6. Telemetria Energetica Aton Green Storage & Fotovoltaico
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS energy_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            p_solare REAL,
            p_utenze REAL,
            p_batteria REAL,
            p_rete REAL,
            p_rete_in REAL,
            p_rete_out REAL,
            soc REAL,
            vb REAL,
            ib REAL,
            temp_battery REAL,
            string1_v REAL,
            string1_i REAL,
            string2_v REAL,
            string2_i REAL,
            grid_v REAL,
            grid_hz REAL,
            e_pannelli_wh REAL,
            e_comprata_wh REAL,
            e_venduta_wh REAL,
            e_batteria_wh REAL,
            raw_json TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_energy_timestamp ON energy_records (timestamp)")

    # 7. Alias e Nomi Personalizzati dei Sensori
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sensor_aliases (
            sensor_id TEXT PRIMARY KEY,
            alias TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    
    conn.commit()
    conn.close()

init_db()

# ----------------- CALCOLI METEO SCIENTIFICI -----------------

def calc_dew_point(temp_c: Optional[float], humidity: Optional[float]) -> Optional[float]:
    """Punto di rugiada (Formula di Magnus-Tetens)."""
    if temp_c is None or humidity is None or humidity <= 0:
        return None
    try:
        a = 17.27
        b = 237.7
        alpha = ((a * float(temp_c)) / (b + float(temp_c))) + math.log(float(humidity) / 100.0)
        dp = (b * alpha) / (a - alpha)
        return round(dp, 1)
    except Exception:
        return None

def calc_apparent_temp(temp_c: Optional[float], humidity: Optional[float], wind_kmh: Optional[float]) -> Optional[float]:
    """
    Temperatura Percepita (Sensazione Termica):
    - Wind Chill (se T <= 10°C e Vento >= 5 km/h)
    - Heat Index / Umidità (se T >= 26°C)
    - Altrimenti temperatura reale
    """
    if temp_c is None:
        return None
    t = float(temp_c)
    w = float(wind_kmh) if wind_kmh is not None else 0.0
    h = float(humidity) if humidity is not None else 50.0

    # Wind Chill
    if t <= 10.0 and w >= 4.8:
        wc = 13.12 + (0.6215 * t) - (11.37 * (w ** 0.16)) + (0.3965 * t * (w ** 0.16))
        return round(wc, 1)
    
    # Heat Index (Steadman / Rothfusz)
    if t >= 26.0 and h >= 40.0:
        tf = (t * 9.0 / 5.0) + 32.0
        hi = -42.379 + 2.04901523*tf + 10.14333127*h - 0.22475541*tf*h - 0.00683783*tf*tf - 0.05481717*h*h + 0.00122874*tf*tf*h + 0.00085282*tf*h*h - 0.00000199*tf*tf*h*h
        hi_c = (hi - 32.0) * 5.0 / 9.0
        return round(hi_c, 1)

    return round(t, 1)

def deg_to_compass(deg: Optional[float]) -> str:
    if deg is None:
        return "--"
    try:
        d = float(deg)
        val = int((d / 22.5) + 0.5)
        dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        return f"{int(d)}° ({dirs[val % 16]})"
    except Exception:
        return f"{deg}°"

# ----------------- ANALISI TREND & ANOMALIE -----------------

def get_pressure_trend(current_hpa: Optional[float]) -> Dict[str, Any]:
    """
    Analizza la variazione della pressione barometrica nelle ultime 3 ore.
    Determina la tendenza e rileva cali bruschi tipici di tempeste/burrasche.
    """
    if current_hpa is None:
        return {"trend": "stabile", "diff": 0.0, "text": "Stabile", "icon": "➡️", "is_storm_alert": False}

    conn = get_connection()
    cursor = conn.cursor()
    target_time = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    cursor.execute("""
        SELECT pressure_rel_hpa FROM weather_records
        WHERE timestamp <= ? AND pressure_rel_hpa IS NOT NULL
        ORDER BY timestamp DESC LIMIT 1
    """, (target_time,))
    row = cursor.fetchone()
    conn.close()

    if not row or row["pressure_rel_hpa"] is None:
        return {"trend": "stabile", "diff": 0.0, "text": "Stabile", "icon": "➡️", "is_storm_alert": False}

    old_hpa = float(row["pressure_rel_hpa"])
    diff = round(float(current_hpa) - old_hpa, 1)

    if diff <= -settings.PRESSURE_DROP_3H_THRESHOLD:
        return {
            "trend": "rapid_drop",
            "diff": diff,
            "text": f"In forte calo ({diff:+} hPa/3h) ⚠️ Burrasca in arrivo!",
            "icon": "⚠️ ↘️",
            "is_storm_alert": True
        }
    elif diff <= -1.0:
        return {"trend": "drop", "diff": diff, "text": f"In calo ({diff:+} hPa/3h)", "icon": "↘️", "is_storm_alert": False}
    elif diff >= 1.0:
        return {"trend": "rise", "diff": diff, "text": f"In aumento ({diff:+} hPa/3h) • Miglioramento", "icon": "↗️", "is_storm_alert": False}
    else:
        return {"trend": "steady", "diff": diff, "text": f"Stabile ({diff:+} hPa/3h)", "icon": "➡️", "is_storm_alert": False}

def get_temp_1h_change(current_temp: Optional[float]) -> Tuple[Optional[float], bool, bool]:
    """Restituisce (variazione_temp_1h, is_plunge, is_spike)."""
    if current_temp is None:
        return None, False, False

    conn = get_connection()
    cursor = conn.cursor()
    target_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    cursor.execute("""
        SELECT temp_c FROM weather_records
        WHERE timestamp <= ? AND temp_c IS NOT NULL
        ORDER BY timestamp DESC LIMIT 1
    """, (target_time,))
    row = cursor.fetchone()
    conn.close()

    if not row or row["temp_c"] is None:
        return None, False, False

    old_t = float(row["temp_c"])
    diff = round(float(current_temp) - old_t, 1)
    is_plunge = diff <= -settings.TEMP_DROP_1H_THRESHOLD
    is_spike = diff >= settings.TEMP_RISE_1H_THRESHOLD
    return diff, is_plunge, is_spike

# ----------------- STATUS & WATCHDOG -----------------

def get_station_status() -> Dict[str, Any]:
    """
    Verifica se la stazione è Online, In ritardo o Offline in base all'ultimo pacchetto.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp FROM weather_records ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    if not row or not row["timestamp"]:
        return {
            "status": "waiting",
            "is_online": False,
            "seconds_ago": None,
            "text": "In attesa dei primi dati dal gateway...",
            "badge_class": "badge-waiting"
        }

    try:
        last_dt = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        seconds_ago = int((now - last_dt).total_seconds())
        
        timeout_sec = settings.STATION_OFFLINE_TIMEOUT_MIN * 60

        if seconds_ago <= 120:
            return {
                "status": "online",
                "is_online": True,
                "seconds_ago": seconds_ago,
                "text": f"🟢 Online (ricevuto {seconds_ago}s fa)",
                "badge_class": "badge-live",
                "last_seen_iso": row["timestamp"]
            }
        elif seconds_ago <= timeout_sec:
            mins = seconds_ago // 60
            return {
                "status": "delayed",
                "is_online": True,
                "seconds_ago": seconds_ago,
                "text": f"🟡 In ritardo (ultimo dato {mins}m fa)",
                "badge_class": "badge-warning",
                "last_seen_iso": row["timestamp"]
            }
        else:
            mins = seconds_ago // 60
            return {
                "status": "offline",
                "is_online": False,
                "seconds_ago": seconds_ago,
                "text": f"🔴 OFFLINE da {mins} minuti!",
                "badge_class": "badge-offline",
                "last_seen_iso": row["timestamp"]
            }
    except Exception:
        return {"status": "unknown", "is_online": False, "seconds_ago": None, "text": "Stato sconosciuto", "badge_class": "badge-waiting"}

def save_reading(data: Dict[str, Any]) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    lightning = data.get("lightning", {})
    
    temp_c = data.get("temp_c")
    hum = data.get("humidity")
    dew_c = data.get("dew_point_c") or calc_dew_point(temp_c, hum)
    
    cursor.execute("""
        INSERT INTO weather_records (
            timestamp, temp_c, humidity, dew_point_c, temp_in_c, humidity_in,
            pressure_rel_hpa, pressure_abs_hpa, wind_speed_kmh, wind_gust_kmh,
            wind_dir_deg, max_daily_gust_kmh, rain_rate_mm_hr, daily_rain_mm,
            event_rain_mm, yearly_rain_mm, solar_radiation, uv_index, vpd,
            lightning_count, lightning_distance_km, lightning_last_time,
            soil_moisture_json, raw_data_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("timestamp"),
        temp_c,
        hum,
        dew_c,
        data.get("temp_in_c"),
        data.get("humidity_in"),
        data.get("pressure_rel_hpa"),
        data.get("pressure_abs_hpa"),
        data.get("wind_speed_kmh"),
        data.get("wind_gust_kmh"),
        data.get("wind_dir_deg"),
        data.get("max_daily_gust_kmh"),
        data.get("rain_rate_mm_hr"),
        data.get("daily_rain_mm"),
        data.get("event_rain_mm"),
        data.get("yearly_rain_mm"),
        data.get("solar_radiation"),
        data.get("uv_index"),
        data.get("vpd"),
        lightning.get("count_total"),
        lightning.get("distance_km"),
        lightning.get("last_strike_time"),
        json.dumps(data.get("soil_moisture", {})),
        json.dumps({k: v for k, v in data.get("raw_payload", {}).items() if k != "PASSKEY"})
    ))
    record_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return record_id

def get_latest_reading() -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM weather_records ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("soil_moisture_json"):
        try:
            d["soil_moisture"] = json.loads(d["soil_moisture_json"])
        except Exception:
            d["soil_moisture"] = {}
            
    # Arricchimento dati calcolati
    d["dew_point_c"] = d.get("dew_point_c") or calc_dew_point(d.get("temp_c"), d.get("humidity"))
    d["apparent_temp_c"] = calc_apparent_temp(d.get("temp_c"), d.get("humidity"), d.get("wind_speed_kmh"))
    d["pressure_trend"] = get_pressure_trend(d.get("pressure_rel_hpa"))
    return d

# ----------------- GESTIONE RECORD & EXTREMES -----------------

def check_and_update_records(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    ts = data.get("timestamp") or datetime.now(timezone.utc).isoformat()
    new_records_broken = []
    
    candidates = {
        "temp_max": (data.get("temp_c"), {}),
        "temp_min": (data.get("temp_c"), {}),
        "dew_point_max": (data.get("dew_point_c") or calc_dew_point(data.get("temp_c"), data.get("humidity")), {}),
        "wind_gust_max": (data.get("wind_gust_kmh"), {"dir": deg_to_compass(data.get("wind_dir_deg"))}),
        "wind_speed_max": (data.get("wind_speed_kmh"), {"dir": deg_to_compass(data.get("wind_dir_deg"))}),
        "rain_rate_max": (data.get("rain_rate_mm_hr"), {}),
        "rain_daily_max": (data.get("daily_rain_mm"), {}),
        "pressure_max": (data.get("pressure_rel_hpa"), {}),
        "pressure_min": (data.get("pressure_rel_hpa"), {}),
        "uv_max": (data.get("uv_index"), {}),
        "solar_max": (data.get("solar_radiation"), {})
    }
    
    lightning = data.get("lightning", {})
    l_dist = lightning.get("distance_km")
    if l_dist is not None and l_dist > 0:
        candidates["lightning_closest"] = (l_dist, {"count": lightning.get("count_total")})

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM weather_extremes")
    current_extremes = {row["record_key"]: dict(row) for row in cursor.fetchall()}

    for defn in RECORD_DEFINITIONS:
        key = defn["key"]
        if key not in candidates:
            continue
        
        val, details = candidates[key]
        if val is None:
            continue
            
        val = float(val)
        if defn["type"] == "max" and val <= 0 and key in ("rain_rate_max", "rain_daily_max", "uv_max", "solar_max"):
            continue

        curr = current_extremes.get(key)
        is_broken = False
        old_val = None

        if curr is None:
            is_broken = True
        else:
            old_val = curr["value"]
            if defn["type"] == "max" and val > old_val:
                is_broken = True
            elif defn["type"] == "min" and val < old_val:
                is_broken = True

        if is_broken:
            # Soglie minime di variazione per evitare spam nei log e notifiche per ogni 0.1
            min_step = 0.0
            if key in ("temp_max", "temp_min", "dew_point_max"):
                min_step = 0.5
            elif key in ("wind_gust_max", "wind_speed_max"):
                min_step = 5.0
            elif key in ("rain_rate_max", "rain_daily_max"):
                min_step = 1.0
            elif key in ("pressure_max", "pressure_min"):
                min_step = 2.0
            elif key == "solar_max":
                min_step = 50.0

            is_significant = (old_val is None) or (abs(val - old_val) >= min_step)

            # Aggiorna sempre il record estremo assoluto attuale
            cursor.execute("""
                INSERT OR REPLACE INTO weather_extremes (record_key, category, title, value, unit, timestamp, details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (key, defn["category"], defn["title"], val, defn["unit"], ts, json.dumps(details)))

            # Inserisci nella cronologia storica solo se l'incremento è significativo
            if is_significant:
                cursor.execute("""
                    INSERT INTO records_history (record_key, category, title, old_value, new_value, unit, timestamp, details_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (key, defn["category"], defn["title"], old_val, val, defn["unit"], ts, json.dumps(details)))

                # Non inviare notifiche push per pressione e solare
                should_notify = key not in ("pressure_max", "pressure_min", "solar_max")

                new_records_broken.append({
                    "key": key,
                    "title": defn["title"],
                    "category": defn["category"],
                    "old_value": old_val,
                    "new_value": val,
                    "unit": defn["unit"],
                    "timestamp": ts,
                    "details": details,
                    "should_notify": should_notify
                })

    conn.commit()
    conn.close()
    return new_records_broken

def get_all_records() -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM weather_extremes")
    stored = {row["record_key"]: dict(row) for row in cursor.fetchall()}
    conn.close()

    result = []
    for defn in RECORD_DEFINITIONS:
        key = defn["key"]
        if key in stored:
            item = stored[key]
            if item.get("details_json"):
                try:
                    item["details"] = json.loads(item["details_json"])
                except Exception:
                    item["details"] = {}
            result.append(item)
        else:
            result.append({
                "record_key": key,
                "category": defn["category"],
                "title": defn["title"],
                "value": None,
                "unit": defn["unit"],
                "timestamp": None,
                "details": {}
            })
    return result

def get_records_history(record_key: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    if record_key:
        cursor.execute("SELECT * FROM records_history WHERE record_key = ? ORDER BY id DESC LIMIT ?", (record_key, limit))
    else:
        cursor.execute("SELECT * FROM records_history ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    res = []
    for r in rows:
        d = dict(r)
        if d.get("details_json"):
            try:
                d["details"] = json.loads(d["details_json"])
            except Exception:
                d["details"] = {}
        res.append(d)
    return res

# ----------------- SERIE TEMPORALI PER GRAFICI -----------------

def get_timeseries(period: str = "24h") -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    if period == "7d":
        since = (now - timedelta(days=7)).isoformat()
        group_sql = "strftime('%Y-%m-%d %H:00:00', timestamp)"
    elif period == "30d":
        since = (now - timedelta(days=30)).isoformat()
        group_sql = "strftime('%Y-%m-%d %H:00:00', timestamp)"
    elif period == "1y":
        since = (now - timedelta(days=365)).isoformat()
        group_sql = "strftime('%Y-%m-%d', timestamp)"
    else:
        since = (now - timedelta(hours=24)).isoformat()
        group_sql = None

    conn = get_connection()
    cursor = conn.cursor()

    if group_sql:
        query = f"""
            SELECT 
                {group_sql} AS bucket,
                ROUND(AVG(temp_c), 1) AS temp_avg,
                ROUND(MIN(temp_c), 1) AS temp_min,
                ROUND(MAX(temp_c), 1) AS temp_max,
                ROUND(AVG(temp_in_c), 1) AS temp_in_avg,
                ROUND(AVG(humidity_in), 1) AS humidity_in_avg,
                ROUND(AVG(humidity), 1) AS humidity_avg,
                ROUND(AVG(dew_point_c), 1) AS dew_point_avg,
                ROUND(AVG(pressure_rel_hpa), 1) AS pressure_avg,
                ROUND(AVG(wind_speed_kmh), 1) AS wind_avg,
                ROUND(MAX(wind_gust_kmh), 1) AS wind_gust_max,
                ROUND(MAX(daily_rain_mm), 1) AS rain_day,
                ROUND(AVG(solar_radiation), 1) AS solar_avg,
                MAX(uv_index) AS uv_max
            FROM weather_records
            WHERE timestamp >= ?
            GROUP BY bucket
            ORDER BY bucket ASC
        """
        cursor.execute(query, (since,))
        rows = cursor.fetchall()
        conn.close()
        
        return {
            "period": period,
            "labels": [r["bucket"] for r in rows],
            "temp_c": [r["temp_avg"] for r in rows],
            "temp_min": [r["temp_min"] for r in rows],
            "temp_max": [r["temp_max"] for r in rows],
            "temp_in_c": [r["temp_in_avg"] for r in rows],
            "humidity_in": [r["humidity_in_avg"] for r in rows],
            "humidity": [r["humidity_avg"] for r in rows],
            "dew_point": [r["dew_point_avg"] for r in rows],
            "pressure": [r["pressure_avg"] for r in rows],
            "wind_speed": [r["wind_avg"] for r in rows],
            "wind_gust": [r["wind_gust_max"] for r in rows],
            "daily_rain": [r["rain_day"] for r in rows],
            "solar": [r["solar_avg"] for r in rows],
            "uv": [r["uv_max"] for r in rows]
        }
    else:
        cursor.execute("""
            SELECT timestamp, temp_c, temp_in_c, humidity, humidity_in, dew_point_c, pressure_rel_hpa,
                   wind_speed_kmh, wind_gust_kmh, rain_rate_mm_hr, daily_rain_mm,
                   solar_radiation, uv_index
            FROM weather_records
            WHERE timestamp >= ?
            ORDER BY timestamp ASC
            LIMIT 600
        """, (since,))
        rows = cursor.fetchall()
        conn.close()

        return {
            "period": "24h",
            "labels": [r["timestamp"] for r in rows],
            "temp_c": [r["temp_c"] for r in rows],
            "temp_in_c": [r["temp_in_c"] for r in rows],
            "humidity": [r["humidity"] for r in rows],
            "humidity_in": [r["humidity_in"] for r in rows],
            "dew_point": [r["dew_point_c"] for r in rows],
            "pressure": [r["pressure_rel_hpa"] for r in rows],
            "wind_speed": [r["wind_speed_kmh"] for r in rows],
            "wind_gust": [r["wind_gust_kmh"] for r in rows],
            "rain_rate": [r["rain_rate_mm_hr"] for r in rows],
            "daily_rain": [r["daily_rain_mm"] for r in rows],
            "solar": [r["solar_radiation"] for r in rows],
            "uv": [r["uv_index"] for r in rows]
        }

# ----------------- RICERCA ARCHIVIO & EXPORT -----------------

def search_history(start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    conn = get_connection()
    cursor = conn.cursor()
    
    where_clauses = []
    params = []
    if start_date:
        where_clauses.append("timestamp >= ?")
        params.append(start_date if "T" in start_date else f"{start_date}T00:00:00")
    if end_date:
        where_clauses.append("timestamp <= ?")
        params.append(end_date if "T" in end_date else f"{end_date}T23:59:59")

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    
    cursor.execute(f"SELECT COUNT(*) FROM weather_records {where_sql}", params)
    total_count = cursor.fetchone()[0]

    cursor.execute(f"""
        SELECT * FROM weather_records {where_sql}
        ORDER BY timestamp DESC
        LIMIT ? OFFSET ?
    """, params + [limit, offset])
    rows = cursor.fetchall()
    conn.close()

    records = []
    for r in rows:
        d = dict(r)
        if d.get("soil_moisture_json"):
            try:
                d["soil_moisture"] = json.loads(d["soil_moisture_json"])
            except Exception:
                d["soil_moisture"] = {}
        records.append(d)
    return records, total_count

def log_alert_db(alert_type: str, title: str, message: str, data: Optional[Dict[str, Any]] = None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO alert_logs (timestamp, alert_type, title, message, data_json, is_read)
        VALUES (?, ?, ?, ?, ?, 0)
    """, (datetime.now(timezone.utc).isoformat(), alert_type, title, message, json.dumps(data or {})))
    conn.commit()
    conn.close()

def get_alert_logs(limit: int = 50, unread_only: bool = False) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    if unread_only:
        cursor.execute("SELECT * FROM alert_logs WHERE is_read = 0 ORDER BY id DESC LIMIT ?", (limit,))
    else:
        cursor.execute("SELECT * FROM alert_logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_unread_alerts_count() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM alert_logs WHERE is_read = 0")
    row = cursor.fetchone()
    conn.close()
    return int(row[0]) if row else 0

def mark_alert_as_read(alert_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE alert_logs SET is_read = 1 WHERE id = ?", (alert_id,))
    conn.commit()
    affected = cursor.rowcount > 0
    conn.close()
    return affected

def mark_all_alerts_as_read() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE alert_logs SET is_read = 1 WHERE is_read = 0")
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected

def delete_alert_log(alert_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM alert_logs WHERE id = ?", (alert_id,))
    conn.commit()
    affected = cursor.rowcount > 0
    conn.close()
    return affected

def clear_all_alert_logs() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM alert_logs")
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected

# ----------------- ANALISI GIORNALIERA & CONFRONTI -----------------

def get_today_extremes() -> Dict[str, Any]:
    """
    Recupera i valori minimi e massimi registrati nella giornata odierna
    (da mezzanotte locale a oggi) con i rispettivi timestamp formattati nel fuso orario locale.
    """
    tz = settings.get_tz()
    now = settings.now_local()
    today_start_local = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=tz)
    today_start_utc = today_start_local.astimezone(timezone.utc).isoformat()

    conn = get_connection()
    cursor = conn.cursor()

    # Max Temp
    cursor.execute("""
        SELECT temp_c, timestamp FROM weather_records
        WHERE timestamp >= ? AND temp_c IS NOT NULL
        ORDER BY temp_c DESC, timestamp ASC LIMIT 1
    """, (today_start_utc,))
    max_t_row = cursor.fetchone()

    # Min Temp
    cursor.execute("""
        SELECT temp_c, timestamp FROM weather_records
        WHERE timestamp >= ? AND temp_c IS NOT NULL
        ORDER BY temp_c ASC, timestamp ASC LIMIT 1
    """, (today_start_utc,))
    min_t_row = cursor.fetchone()

    # Max Temp Interna
    cursor.execute("""
        SELECT temp_in_c, timestamp FROM weather_records
        WHERE timestamp >= ? AND temp_in_c IS NOT NULL
        ORDER BY temp_in_c DESC, timestamp ASC LIMIT 1
    """, (today_start_utc,))
    max_t_in_row = cursor.fetchone()

    # Min Temp Interna
    cursor.execute("""
        SELECT temp_in_c, timestamp FROM weather_records
        WHERE timestamp >= ? AND temp_in_c IS NOT NULL
        ORDER BY temp_in_c ASC, timestamp ASC LIMIT 1
    """, (today_start_utc,))
    min_t_in_row = cursor.fetchone()

    # Max Raffica Vento Oggi
    cursor.execute("""
        SELECT wind_gust_kmh, timestamp FROM weather_records
        WHERE timestamp >= ? AND wind_gust_kmh IS NOT NULL
        ORDER BY wind_gust_kmh DESC LIMIT 1
    """, (today_start_utc,))
    gust_row = cursor.fetchone()

    # Pioggia Massima di Oggi (o ultimo daily_rain_mm registrato)
    cursor.execute("""
        SELECT daily_rain_mm FROM weather_records
        WHERE timestamp >= ? AND daily_rain_mm IS NOT NULL
        ORDER BY daily_rain_mm DESC LIMIT 1
    """, (today_start_utc,))
    rain_row = cursor.fetchone()

    conn.close()

    def _fmt_time(ts_str):
        if not ts_str:
            return None
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone(tz)
            return dt.strftime("%H:%M")
        except Exception:
            return ts_str[11:16] if len(ts_str) >= 16 else ts_str

    max_t = float(max_t_row["temp_c"]) if max_t_row and max_t_row["temp_c"] is not None else None
    min_t = float(min_t_row["temp_c"]) if min_t_row and min_t_row["temp_c"] is not None else None
    max_t_time = _fmt_time(max_t_row["timestamp"]) if max_t_row else None
    min_t_time = _fmt_time(min_t_row["timestamp"]) if min_t_row else None

    max_t_in = float(max_t_in_row["temp_in_c"]) if max_t_in_row and max_t_in_row["temp_in_c"] is not None else None
    min_t_in = float(min_t_in_row["temp_in_c"]) if min_t_in_row and min_t_in_row["temp_in_c"] is not None else None
    max_t_in_time = _fmt_time(max_t_in_row["timestamp"]) if max_t_in_row else None
    min_t_in_time = _fmt_time(min_t_in_row["timestamp"]) if min_t_in_row else None

    range_t = round(max_t - min_t, 1) if (max_t is not None and min_t is not None) else None
    max_gust = float(gust_row["wind_gust_kmh"]) if gust_row and gust_row["wind_gust_kmh"] is not None else None
    today_rain = float(rain_row["daily_rain_mm"]) if rain_row and rain_row["daily_rain_mm"] is not None else 0.0

    return {
        "temp_max": max_t,
        "temp_max_time": max_t_time,
        "temp_min": min_t,
        "temp_min_time": min_t_time,
        "temp_range": range_t,
        "temp_in_max": max_t_in,
        "temp_in_max_time": max_t_in_time,
        "temp_in_min": min_t_in,
        "temp_in_min_time": min_t_in_time,
        "max_gust": max_gust,
        "today_rain": today_rain
    }

def get_yesterday_same_time(current_temp: Optional[float]) -> Dict[str, Any]:
    """
    Recupera la lettura della temperatura di ieri a quest'ora (tra 23h e 25h fa)
    e calcola la differenza termica (+X°C / -X°C rispetto a ieri).
    """
    if current_temp is None:
        return {"temp_c": None, "diff_c": None, "text": "In attesa dati"}

    now_utc = datetime.now(timezone.utc)
    target_start = (now_utc - timedelta(hours=25)).isoformat()
    target_end = (now_utc - timedelta(hours=23)).isoformat()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT temp_c, timestamp FROM weather_records
        WHERE timestamp >= ? AND timestamp <= ? AND temp_c IS NOT NULL
        ORDER BY ABS(strftime('%s', timestamp) - strftime('%s', ?)) ASC
        LIMIT 1
    """, (target_start, target_end, (now_utc - timedelta(hours=24)).isoformat()))
    row = cursor.fetchone()
    conn.close()

    if not row or row["temp_c"] is None:
        return {"temp_c": None, "diff_c": None, "text": "Nessun dato 24h fa"}

    old_temp = float(row["temp_c"])
    diff = round(float(current_temp) - old_temp, 1)
    sign = "+" if diff > 0 else ""
    return {
        "temp_c": old_temp,
        "diff_c": diff,
        "text": f"{sign}{diff}°C vs ieri a quest'ora"
    }

def get_recent_rain_totals() -> Dict[str, float]:
    """
    Calcola gli accumuli pioggia degli ultimi 7 giorni, del mese in corso e dell'anno dal 1° gennaio.
    """
    tz = settings.get_tz()
    now = settings.now_local()
    year_start_local = datetime(now.year, 1, 1, 0, 0, 0, tzinfo=tz)
    year_start_utc = year_start_local.astimezone(timezone.utc).isoformat()
    month_start_local = datetime(now.year, now.month, 1, 0, 0, 0, tzinfo=tz)
    month_start_utc = month_start_local.astimezone(timezone.utc).isoformat()
    week_start_utc = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    conn = get_connection()
    cursor = conn.cursor()

    # Ultimi 7 giorni: somma dei massimi giornalieri
    cursor.execute("""
        SELECT date(timestamp) as day, MAX(daily_rain_mm) as day_rain
        FROM weather_records
        WHERE timestamp >= ? AND daily_rain_mm IS NOT NULL
        GROUP BY date(timestamp)
    """, (week_start_utc,))
    week_rows = cursor.fetchall()
    week_rain = round(sum([float(r["day_rain"] or 0) for r in week_rows]), 1)

    # Mese corrente: somma dei massimi giornalieri
    cursor.execute("""
        SELECT date(timestamp) as day, MAX(daily_rain_mm) as day_rain
        FROM weather_records
        WHERE timestamp >= ? AND daily_rain_mm IS NOT NULL
        GROUP BY date(timestamp)
    """, (month_start_utc,))
    month_rows = cursor.fetchall()
    month_rain = round(sum([float(r["day_rain"] or 0) for r in month_rows]), 1)

    # Anno corrente dal 1° Gennaio (calcolato da DB)
    cursor.execute("""
        SELECT date(timestamp) as day, MAX(daily_rain_mm) as day_rain
        FROM weather_records
        WHERE timestamp >= ? AND daily_rain_mm IS NOT NULL
        GROUP BY date(timestamp)
    """, (year_start_utc,))
    year_rows = cursor.fetchall()
    year_rain = round(sum([float(r["day_rain"] or 0) for r in year_rows]), 1)

    conn.close()
    return {
        "week_rain_mm": week_rain,
        "month_rain_mm": month_rain,
        "year_rain_mm": year_rain
    }

# ----------------- SOTTOSCRIZIONI WEB PUSH PWA -----------------

def save_push_subscription(endpoint: str, p256dh: str, auth: str, user_agent: Optional[str] = None):
    conn = get_connection()
    cursor = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        INSERT INTO push_subscriptions (endpoint, p256dh, auth, user_agent, created_at, last_seen)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(endpoint) DO UPDATE SET
            p256dh=excluded.p256dh,
            auth=excluded.auth,
            user_agent=excluded.user_agent,
            last_seen=excluded.last_seen
    """, (endpoint, p256dh, auth, user_agent, now_iso, now_iso))
    conn.commit()
    conn.close()

def delete_push_subscription(endpoint: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
    conn.commit()
    conn.close()

def get_all_push_subscriptions() -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM push_subscriptions")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ----------------- TELEMETRIA ENERGETICA ATON & FV -----------------

def save_energy_reading(data: Dict[str, Any]) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO energy_records (
            timestamp, p_solare, p_utenze, p_batteria, p_rete, p_rete_in, p_rete_out,
            soc, vb, ib, temp_battery, string1_v, string1_i, string2_v, string2_i,
            grid_v, grid_hz, e_pannelli_wh, e_comprata_wh, e_venduta_wh, e_batteria_wh
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        data.get("p_solare"),
        data.get("p_utenze"),
        data.get("p_batteria"),
        data.get("p_rete"),
        data.get("p_rete_in"),
        data.get("p_rete_out"),
        data.get("soc"),
        data.get("vb"),
        data.get("ib"),
        data.get("temp_battery"),
        data.get("string1_v"),
        data.get("string1_i"),
        data.get("string2_v"),
        data.get("string2_i"),
        data.get("grid_v"),
        data.get("grid_hz"),
        data.get("e_pannelli_wh"),
        data.get("e_comprata_wh"),
        data.get("e_venduta_wh"),
        data.get("e_batteria_wh")
    ))
    record_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return record_id

def get_latest_energy() -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM energy_records ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_energy_timeseries(hours: int = 24) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    since_dt = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    cursor.execute("""
        SELECT timestamp, p_solare, p_utenze, p_batteria, p_rete, soc
        FROM energy_records
        WHERE timestamp >= ?
        ORDER BY id ASC
    """, (since_dt,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_today_energy_summary() -> Dict[str, Any]:
    """
    Calcola il bilancio energetico odierno:
    - Integrazione esatta dei consumi di casa a partire dalla potenza assorbita dalle utenze (P_utenze)
    - Autosufficienza energetica reale: (1 - energia_prelevata_rete / consumo_totale_casa) * 100
    - Autoconsumo reale: quota di energia solare utilizzata rispetto al totale prodotto
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    now_local = settings.now_local()
    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start_local.astimezone(timezone.utc).isoformat()
    
    # 1. Recupera tutte le letture odierne in ordine cronologico per integrazione
    cursor.execute("""
        SELECT timestamp, p_solare, p_utenze, p_batteria, p_rete, p_rete_in, p_rete_out,
               soc, e_pannelli_wh, e_comprata_wh, e_venduta_wh, e_batteria_wh
        FROM energy_records 
        WHERE timestamp >= ? 
        ORDER BY id ASC
    """, (today_start_utc,))
    rows = cursor.fetchall()
    
    if not rows:
        cursor.execute("SELECT * FROM energy_records ORDER BY id DESC LIMIT 1")
        last_row = cursor.fetchone()
        rows = [last_row] if last_row else []
    
    conn.close()

    if not rows:
        return {
            "solar_today_kwh": 0.0,
            "bought_today_kwh": 0.0,
            "sold_today_kwh": 0.0,
            "battery_soc": 0.0,
            "self_consumed_kwh": 0.0,
            "total_house_kwh": 0.0,
            "self_consumption_pct": 0.0,
            "autarky_pct": 0.0,
            "max_solar_w": 0.0,
            "max_consumption_w": 0.0
        }

    latest_dict = dict(rows[-1])
    solar_kwh = round((latest_dict.get("e_pannelli_wh") or 0.0) / 1000.0, 2)
    bought_kwh = round((latest_dict.get("e_comprata_wh") or 0.0) / 1000.0, 2)
    sold_kwh = round((latest_dict.get("e_venduta_wh") or 0.0) / 1000.0, 2)
    soc = latest_dict.get("soc") or 0.0

    # Integrazione numerica di P_utenze (Watt) nel tempo per calcolare il consumo totale effettivo della casa in kWh
    integrated_wh = 0.0
    max_solar_w = 0.0
    max_consumption_w = 0.0

    for i in range(len(rows)):
        r = dict(rows[i])
        p_u = float(r.get("p_utenze") or 0.0)
        p_s = float(r.get("p_solare") or 0.0)
        max_consumption_w = max(max_consumption_w, p_u)
        max_solar_w = max(max_solar_w, p_s)

        if i > 0:
            r_prev = dict(rows[i - 1])
            try:
                t_curr = datetime.fromisoformat(str(r["timestamp"]).replace("Z", "+00:00"))
                t_prev = datetime.fromisoformat(str(r_prev["timestamp"]).replace("Z", "+00:00"))
                dt_hours = (t_curr - t_prev).total_seconds() / 3600.0
                if 0.0 < dt_hours <= 0.5: # scarta gap anomali superiori a 30 min
                    p_u_prev = float(r_prev.get("p_utenze") or 0.0)
                    integrated_wh += ((p_u + p_u_prev) / 2.0) * dt_hours
            except Exception:
                pass

    integrated_house_kwh = round(integrated_wh / 1000.0, 2)
    
    # Se abbiamo campioni sufficienti usiamo il carico integrato reale, altrimenti stima conservativa
    self_consumed_kwh = max(0.0, solar_kwh - sold_kwh)
    if integrated_house_kwh >= 0.1:
        total_house_kwh = integrated_house_kwh
    else:
        total_house_kwh = round(self_consumed_kwh + bought_kwh, 2)

    # % Autosufficienza energetica reale: 1 - (energia prelevata dalla rete / consumo totale casa)
    if total_house_kwh > 0.0:
        autarky_pct = round(max(0.0, (1.0 - (bought_kwh / total_house_kwh))) * 100.0, 1)
        autarky_pct = min(100.0, autarky_pct)
    else:
        autarky_pct = 0.0

    # % Autoconsumo reale solare: quota di FV prodotta non immessa in rete
    self_consumption_pct = round((self_consumed_kwh / solar_kwh * 100.0), 1) if solar_kwh > 0 else 100.0
    self_consumption_pct = min(100.0, max(0.0, self_consumption_pct))

    return {
        "solar_today_kwh": solar_kwh,
        "bought_today_kwh": bought_kwh,
        "sold_today_kwh": sold_kwh,
        "self_consumed_kwh": round(self_consumed_kwh, 2),
        "total_house_kwh": total_house_kwh,
        "battery_soc": soc,
        "self_consumption_pct": self_consumption_pct,
        "autarky_pct": autarky_pct,
        "max_solar_w": max_solar_w,
        "max_consumption_w": max_consumption_w,
        "last_update": latest_dict.get("timestamp")
    }

# ----------------- GESTIONE ALIAS SENSORI -----------------

def get_sensor_aliases() -> Dict[str, str]:
    """Restituisce la mappa di tutti gli alias personalizzati dei sensori (es: {'soil_ch1': 'Piante Salotto'})."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT sensor_id, alias FROM sensor_aliases")
    rows = cursor.fetchall()
    conn.close()
    return {r["sensor_id"]: r["alias"] for r in rows}

def save_sensor_alias(sensor_id: str, alias: str) -> None:
    """Salva o aggiorna il nome personalizzato di un sensore."""
    conn = get_connection()
    cursor = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    if not alias or not alias.strip():
        cursor.execute("DELETE FROM sensor_aliases WHERE sensor_id = ?", (sensor_id,))
    else:
        cursor.execute("""
            INSERT INTO sensor_aliases (sensor_id, alias, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(sensor_id) DO UPDATE SET alias=excluded.alias, updated_at=excluded.updated_at
        """, (sensor_id.strip(), alias.strip(), now_iso))
    conn.commit()
    conn.close()

# ----------------- STATISTICHE & MANUTENZIONE DATABASE -----------------

def get_database_stats() -> Dict[str, Any]:
    """Restituisce statistiche approfondite sull'utilizzo e le dimensioni del database SQLite."""
    db_size_bytes = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    wal_path = f"{DB_PATH}-wal"
    wal_size_bytes = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM weather_records")
    weather_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM weather_records")
    w_min, w_max = cursor.fetchone()
    
    cursor.execute("SELECT COUNT(*) FROM energy_records")
    energy_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM records_history")
    records_broken_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM alert_logs")
    alerts_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM push_subscriptions")
    push_count = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        "db_path": DB_PATH,
        "db_size_mb": round((db_size_bytes + wal_size_bytes) / (1024 * 1024), 2),
        "db_size_bytes": db_size_bytes + wal_size_bytes,
        "wal_size_kb": round(wal_size_bytes / 1024, 1),
        "weather_records_count": weather_count,
        "energy_records_count": energy_count,
        "records_broken_count": records_broken_count,
        "alerts_count": alerts_count,
        "push_devices_count": push_count,
        "first_reading_utc": w_min,
        "last_reading_utc": w_max,
        "wal_mode_enabled": True
    }

def perform_database_maintenance(retention_days: int = 60) -> Dict[str, Any]:
    """
    Esegue la compattazione e il downsampling intelligente dello storico:
    - Conserva tutte le letture ad alta frequenza (16s) degli ultimi 'retention_days' giorni (default 60).
    - Per i dati più vecchi di 60 giorni, condensa le registrazioni a 1 lettura per ora con medie,
      minime, massime, piogge e raffiche aggregate intatte (nessuna perdita di trend storici).
    - I record estremi (Albo dei Record e storico record infranti) NON vengono mai cancellati né alterati.
    - Esegue il checkpoint del file WAL e PRAGMA optimize.
    """
    cutoff_utc = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Recupera i bucket orari da condensare
    cursor.execute("""
        SELECT strftime('%Y-%m-%d %H:00:00', timestamp) AS hour_bucket, COUNT(*) AS cnt
        FROM weather_records
        WHERE timestamp < ?
        GROUP BY hour_bucket
        HAVING cnt > 1
    """, (cutoff_utc,))
    buckets_to_downsample = cursor.fetchall()
    
    compressed_buckets = 0
    purged_records = 0
    
    for row in buckets_to_downsample:
        h_bucket = row["hour_bucket"]
        # Calcola le aggregazioni scientifiche per l'ora
        cursor.execute("""
            SELECT 
                ROUND(AVG(temp_c), 1) as avg_temp,
                ROUND(MIN(temp_c), 1) as min_temp,
                ROUND(MAX(temp_c), 1) as max_temp,
                ROUND(AVG(humidity), 1) as avg_hum,
                ROUND(AVG(dew_point_c), 1) as avg_dew,
                ROUND(AVG(temp_in_c), 1) as avg_temp_in,
                ROUND(AVG(humidity_in), 1) as avg_hum_in,
                ROUND(AVG(pressure_rel_hpa), 1) as avg_press,
                ROUND(AVG(pressure_abs_hpa), 1) as avg_press_abs,
                ROUND(AVG(wind_speed_kmh), 1) as avg_wind_spd,
                ROUND(MAX(wind_gust_kmh), 1) as max_wind_gust,
                ROUND(AVG(wind_dir_deg), 0) as avg_wind_dir,
                ROUND(MAX(max_daily_gust_kmh), 1) as max_day_gust,
                ROUND(MAX(rain_rate_mm_hr), 1) as max_rain_rate,
                ROUND(MAX(daily_rain_mm), 1) as max_daily_rain,
                ROUND(MAX(event_rain_mm), 1) as max_event_rain,
                ROUND(MAX(yearly_rain_mm), 1) as max_yearly_rain,
                ROUND(AVG(solar_radiation), 1) as avg_solar,
                MAX(uv_index) as max_uv,
                ROUND(AVG(vpd), 2) as avg_vpd,
                MAX(lightning_count) as max_l_count,
                MIN(lightning_distance_km) as min_l_dist,
                COUNT(*) as bucket_count
            FROM weather_records
            WHERE timestamp >= ? AND timestamp < datetime(?, '+1 hour')
        """, (h_bucket, h_bucket))
        agg = cursor.fetchone()
        
        if agg and agg["bucket_count"] > 1:
            # Elimina i record singoli ad alta frequenza del bucket
            cursor.execute("""
                DELETE FROM weather_records
                WHERE timestamp >= ? AND timestamp < datetime(?, '+1 hour')
            """, (h_bucket, h_bucket))
            purged_records += (agg["bucket_count"] - 1)
            
            # Inserisce la singola lettura oraria consolidata
            cursor.execute("""
                INSERT INTO weather_records (
                    timestamp, temp_c, humidity, dew_point_c, temp_in_c, humidity_in,
                    pressure_rel_hpa, pressure_abs_hpa, wind_speed_kmh, wind_gust_kmh,
                    wind_dir_deg, max_daily_gust_kmh, rain_rate_mm_hr, daily_rain_mm,
                    event_rain_mm, yearly_rain_mm, solar_radiation, uv_index, vpd,
                    lightning_count, lightning_distance_km
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                h_bucket, agg["avg_temp"], agg["avg_hum"], agg["avg_dew"], agg["avg_temp_in"], agg["avg_hum_in"],
                agg["avg_press"], agg["avg_press_abs"], agg["avg_wind_spd"], agg["max_wind_gust"],
                agg["avg_wind_dir"], agg["max_day_gust"], agg["max_rain_rate"], agg["max_daily_rain"],
                agg["max_event_rain"], agg["max_yearly_rain"], agg["avg_solar"], agg["max_uv"], agg["avg_vpd"],
                agg["max_l_count"], agg["min_l_dist"]
            ))
            compressed_buckets += 1

    # 2. Downsampling analogo per telemetria energetica Aton > retention_days
    cursor.execute("""
        SELECT strftime('%Y-%m-%d %H:00:00', timestamp) AS hour_bucket, COUNT(*) AS cnt
        FROM energy_records
        WHERE timestamp < ?
        GROUP BY hour_bucket
        HAVING cnt > 1
    """, (cutoff_utc,))
    energy_buckets = cursor.fetchall()
    
    purged_energy = 0
    for erow in energy_buckets:
        eh_bucket = erow["hour_bucket"]
        cursor.execute("""
            SELECT 
                ROUND(AVG(p_solare), 1) as avg_p_solare,
                ROUND(AVG(p_utenze), 1) as avg_p_utenze,
                ROUND(AVG(p_batteria), 1) as avg_p_batteria,
                ROUND(AVG(p_rete), 1) as avg_p_rete,
                ROUND(AVG(soc), 1) as avg_soc,
                ROUND(AVG(temp_battery), 1) as avg_temp_batt,
                MAX(e_pannelli_wh) as max_e_pan,
                MAX(e_comprata_wh) as max_e_comp,
                MAX(e_venduta_wh) as max_e_vend,
                MAX(e_batteria_wh) as max_e_batt,
                COUNT(*) as b_cnt
            FROM energy_records
            WHERE timestamp >= ? AND timestamp < datetime(?, '+1 hour')
        """, (eh_bucket, eh_bucket))
        eagg = cursor.fetchone()
        if eagg and eagg["b_cnt"] > 1:
            cursor.execute("""
                DELETE FROM energy_records
                WHERE timestamp >= ? AND timestamp < datetime(?, '+1 hour')
            """, (eh_bucket, eh_bucket))
            purged_energy += (eagg["b_cnt"] - 1)
            
            cursor.execute("""
                INSERT INTO energy_records (
                    timestamp, p_solare, p_utenze, p_batteria, p_rete, soc,
                    temp_battery, e_pannelli_wh, e_comprata_wh, e_venduta_wh, e_batteria_wh
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                eh_bucket, eagg["avg_p_solare"], eagg["avg_p_utenze"], eagg["avg_p_batteria"],
                eagg["avg_p_rete"], eagg["avg_soc"], eagg["avg_temp_batt"],
                eagg["max_e_pan"], eagg["max_e_comp"], eagg["max_e_vend"], eagg["max_e_batt"]
            ))

    conn.commit()
    
    # 3. Checkpoint WAL & Ottimizzazione indici SQLite
    try:
        cursor.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        cursor.execute("PRAGMA optimize;")
    except Exception:
        pass
        
    conn.close()
    
    return {
        "status": "success",
        "retention_days_raw": retention_days,
        "compressed_hours": compressed_buckets,
        "weather_records_purged": purged_records,
        "energy_records_purged": purged_energy,
        "stats_after": get_database_stats()
    }

