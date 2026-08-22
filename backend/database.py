import os
import json
import math
import sqlite3
from typing import Dict, Any, Optional, List, Tuple, Union
from datetime import datetime, timezone, timedelta
from backend.config import settings

DB_DIR = settings.DATA_DIR
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "weather_history.db")

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
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

ITALIAN_MONTHS = {
    1: "Gennaio", 2: "Febbraio", 3: "Marzo", 4: "Aprile", 5: "Maggio", 6: "Giugno",
    7: "Luglio", 8: "Agosto", 9: "Settembre", 10: "Ottobre", 11: "Novembre", 12: "Dicembre"
}

# Definizioni dei record tracciati nell'Albo dei Record
RECORD_DEFINITIONS = [
    {"key": "temp_max", "category": "temperature", "title": "Temperatura Massima", "unit": "°C", "type": "max"},
    {"key": "temp_min", "category": "temperature", "title": "Temperatura Minima", "unit": "°C", "type": "min"},
    {"key": "temp_min_highest", "category": "temperature", "title": "Minima Più Alta (Notte Tropicale)", "unit": "°C", "type": "max"},
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
    conn.isolation_level = None
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    conn.isolation_level = ""
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

    # 8. Configurazione e Attivazione Dispositivi Tuya / Smart Life
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tuya_devices_config (
            device_id TEXT PRIMARY KEY,
            enabled INTEGER DEFAULT 1,
            custom_name TEXT,
            category TEXT,
            icon TEXT,
            updated_at TEXT NOT NULL
        )
    """)

    # 9. Configurazione Automazioni Intelligenti Climatizzatori (LG ThinQ)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS climate_automations_config (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
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
    try:
        cursor = conn.cursor()
        lightning = data.get("lightning", {})
        
        ts = data.get("timestamp") or datetime.now(timezone.utc).isoformat()
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
            ts,
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
            json.dumps({k: v for k, v in data.get("raw_payload", {}).items() if k != "PASSKEY"}) if isinstance(data.get("raw_payload"), dict) else json.dumps({})
        ))
        record_id = cursor.lastrowid
        conn.commit()
        return record_id
    finally:
        conn.close()

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

def check_and_update_records(
    data_or_key: Union[Dict[str, Any], str],
    val_arg: Optional[float] = None,
    ts_arg: Optional[str] = None,
    details_arg: Optional[Dict[str, Any]] = None
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Controlla e aggiorna l'Albo dei Record e la cronologia storica.
    Supporta sia payload completo da stazione (dict) che singola chiave (str).
    """
    conn = get_connection()
    cursor = conn.cursor()

    if isinstance(data_or_key, str):
        key = data_or_key
        val = float(val_arg) if val_arg is not None else None
        ts = ts_arg or datetime.now(timezone.utc).isoformat()
        details = details_arg or {}

        defn = next((d for d in RECORD_DEFINITIONS if d["key"] == key), {
            "key": key, "category": "custom", "title": key, "type": "max", "unit": ""
        })

        cursor.execute("SELECT * FROM weather_extremes WHERE record_key = ?", (key,))
        row = cursor.fetchone()
        curr = dict(row) if row else None

        if val is None:
            conn.close()
            return {"is_new": False, "old_value": None, "new_value": None}

        if curr is None:
            cursor.execute("""
                INSERT OR REPLACE INTO weather_extremes (record_key, category, title, value, unit, timestamp, details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (key, defn["category"], defn["title"], val, defn["unit"], ts, json.dumps(details)))
            conn.commit()
            conn.close()
            return {"is_new": True, "old_value": None, "new_value": val}

        old_val = float(curr["value"]) if curr.get("value") is not None else None
        is_broken = False
        if old_val is None:
            is_broken = True
        elif defn["type"] == "max" and val > old_val:
            is_broken = True
        elif defn["type"] == "min" and val < old_val:
            is_broken = True

        if not is_broken:
            conn.close()
            return {"is_new": False, "old_value": old_val, "new_value": val}

        min_step = 0.2
        if key in ("temp_max", "temp_min", "temp_min_highest", "dew_point_max"):
            min_step = 0.2
        elif key in ("wind_gust_max", "wind_speed_max"):
            min_step = 2.0
        elif key in ("rain_rate_max", "rain_daily_max"):
            min_step = 1.0
        elif key in ("pressure_max", "pressure_min"):
            min_step = 1.5
        elif key == "solar_max":
            min_step = 50.0
        elif key == "uv_max":
            min_step = 1.0

        is_significant = abs(val - old_val) >= min_step

        if is_significant:
            cursor.execute("""
                INSERT OR REPLACE INTO weather_extremes (record_key, category, title, value, unit, timestamp, details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (key, defn["category"], defn["title"], val, defn["unit"], ts, json.dumps(details)))
            cursor.execute("""
                INSERT INTO records_history (record_key, category, title, old_value, new_value, unit, timestamp, details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (key, defn["category"], defn["title"], old_val, val, defn["unit"], ts, json.dumps(details)))
            conn.commit()
            conn.close()
            return {"is_new": True, "old_value": old_val, "new_value": val}
        else:
            conn.close()
            return {"is_new": False, "old_value": old_val, "new_value": val}

    # Modalità dict: payload completo
    data = data_or_key
    ts = data.get("timestamp") or datetime.now(timezone.utc).isoformat()
    new_records_broken = []
    
    candidates = {
        "temp_max": (data.get("temp_c"), {}),
        "temp_min": (data.get("temp_c"), {}),
        "temp_min_highest": (data.get("temp_min_highest"), {"date": data.get("temp_min_highest_date") or ts[:10]}) if data.get("temp_min_highest") is not None else (None, {}),
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
        if curr is None:
            # Primo valore mai salvato: imposta il record senza generare allarmi a valanga
            cursor.execute("""
                INSERT OR REPLACE INTO weather_extremes (record_key, category, title, value, unit, timestamp, details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (key, defn["category"], defn["title"], val, defn["unit"], ts, json.dumps(details)))
            continue
        else:
            old_val = float(curr["value"]) if curr.get("value") is not None else None
            is_broken = False
            if old_val is None:
                is_broken = True
            elif defn["type"] == "max" and val > old_val:
                is_broken = True
            elif defn["type"] == "min" and val < old_val:
                is_broken = True

            if is_broken and old_val is not None:
                # Soglie minime di variazione per evitare spam nei log e notifiche per ogni 0.1
                min_step = 0.2
                if key in ("temp_max", "temp_min", "temp_min_highest", "dew_point_max"):
                    min_step = 0.2
                elif key in ("wind_gust_max", "wind_speed_max"):
                    min_step = 2.0
                elif key in ("rain_rate_max", "rain_daily_max"):
                    min_step = 1.0
                elif key in ("pressure_max", "pressure_min"):
                    min_step = 1.5
                elif key == "solar_max":
                    min_step = 50.0
                elif key == "uv_max":
                    min_step = 1.0

                is_significant = abs(val - old_val) >= min_step

                # Aggiorna sempre il record estremo assoluto attuale
                cursor.execute("""
                    INSERT OR REPLACE INTO weather_extremes (record_key, category, title, value, unit, timestamp, details_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (key, defn["category"], defn["title"], val, defn["unit"], ts, json.dumps(details)))

                # Inserisci nella cronologia storica e invia alert solo se l'incremento è significativo
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
                MAX(uv_index) AS uv_max,
                GROUP_CONCAT(soil_moisture_json, '||') as soil_jsons
            FROM weather_records
            WHERE timestamp >= ?
            GROUP BY bucket
            ORDER BY bucket ASC
        """
        cursor.execute(query, (since,))
        rows = cursor.fetchall()
        conn.close()
        
        soil_channels = set()
        bucket_soil_averages = []
        for r in rows:
            raw_concat = r["soil_jsons"] if "soil_jsons" in r.keys() and r["soil_jsons"] else ""
            ch_sums = {}
            ch_counts = {}
            if raw_concat:
                for piece in raw_concat.split("||"):
                    if piece and piece != "{}":
                        try:
                            item = json.loads(piece)
                            if isinstance(item, dict):
                                for k, v in item.items():
                                    if v is not None:
                                        soil_channels.add(k)
                                        ch_sums[k] = ch_sums.get(k, 0.0) + float(v)
                                        ch_counts[k] = ch_counts.get(k, 0) + 1
                        except Exception:
                            pass
            b_avg = {k: round(ch_sums[k] / ch_counts[k], 1) for k in ch_sums if ch_counts.get(k, 0) > 0}
            bucket_soil_averages.append(b_avg)
            
        soil_moisture_series = {}
        for ch in sorted(soil_channels):
            soil_moisture_series[ch] = [b.get(ch) for b in bucket_soil_averages]

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
            "uv": [r["uv_max"] for r in rows],
            "soil_moisture": soil_moisture_series
        }
    else:
        cursor.execute("""
            SELECT timestamp, temp_c, temp_in_c, humidity, humidity_in, dew_point_c, pressure_rel_hpa,
                   wind_speed_kmh, wind_gust_kmh, rain_rate_mm_hr, daily_rain_mm,
                   solar_radiation, uv_index, soil_moisture_json
            FROM weather_records
            WHERE timestamp >= ?
            ORDER BY timestamp ASC
            LIMIT 600
        """, (since,))
        rows = cursor.fetchall()
        conn.close()

        soil_channels = set()
        parsed_rows_soil = []
        for r in rows:
            s_val = {}
            raw_s = r["soil_moisture_json"] if "soil_moisture_json" in r.keys() else None
            if raw_s:
                try:
                    s_val = json.loads(raw_s) if isinstance(raw_s, str) else raw_s
                    if isinstance(s_val, dict):
                        soil_channels.update(s_val.keys())
                except Exception:
                    pass
            parsed_rows_soil.append(s_val if isinstance(s_val, dict) else {})
        
        soil_moisture_series = {}
        for ch in sorted(soil_channels):
            soil_moisture_series[ch] = [p.get(ch) for p in parsed_rows_soil]

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
            "uv": [r["uv_index"] for r in rows],
            "soil_moisture": soil_moisture_series
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
        SELECT id, timestamp, temp_c, temp_in_c, humidity, humidity_in, dew_point_c, pressure_rel_hpa,
               wind_speed_kmh, wind_gust_kmh, wind_dir_deg, rain_rate_mm_hr, daily_rain_mm,
               solar_radiation, uv_index, soil_moisture_json
        FROM weather_records
        {where_sql}
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
        else:
            d["soil_moisture"] = {}
        records.append(d)
        
    return records, total_count

def get_history_kpis(start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
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
    
    cursor.execute(f"""
        SELECT 
            COUNT(*) as total_records,
            MIN(temp_c) as min_temp,
            MAX(temp_c) as max_temp,
            AVG(temp_c) as avg_temp,
            MIN(humidity) as min_hum,
            MAX(humidity) as max_hum,
            AVG(humidity) as avg_hum,
            MIN(temp_in_c) as min_temp_in,
            MAX(temp_in_c) as max_temp_in,
            AVG(temp_in_c) as avg_temp_in,
            MIN(humidity_in) as min_hum_in,
            MAX(humidity_in) as max_hum_in,
            AVG(humidity_in) as avg_hum_in,
            MAX(wind_speed_kmh) as max_wind,
            AVG(wind_speed_kmh) as avg_wind,
            MAX(wind_gust_kmh) as max_gust,
            MIN(pressure_rel_hpa) as min_press,
            MAX(pressure_rel_hpa) as max_press,
            AVG(pressure_rel_hpa) as avg_press,
            MAX(solar_radiation) as max_solar,
            MAX(uv_index) as max_uv,
            MAX(rain_rate_mm_hr) as max_rain_rate,
            MIN(timestamp) as first_ts,
            MAX(timestamp) as last_ts
        FROM weather_records {where_sql}
    """, params)
    row = cursor.fetchone()
    
    cursor.execute(f"""
        SELECT COALESCE(SUM(day_rain), 0.0) FROM (
            SELECT date(timestamp) as day, MAX(daily_rain_mm) as day_rain
            FROM weather_records {where_sql}
            GROUP BY date(timestamp)
        )
    """, params)
    rain_row = cursor.fetchone()
    total_rain = rain_row[0] if rain_row and rain_row[0] is not None else 0.0

    # Conteggio Notti Tropicali (Tmin >= 20°C) e Notti Roventi (Tmin >= 25°C) nel periodo
    where_temp_sql = ("WHERE temp_c IS NOT NULL AND " + " AND ".join(where_clauses)) if where_clauses else "WHERE temp_c IS NOT NULL"
    cursor.execute(f"""
        SELECT 
            COUNT(CASE WHEN day_min >= 20.0 THEN 1 END) as tropical_nights_count,
            COUNT(CASE WHEN day_min >= 25.0 THEN 1 END) as very_hot_nights_count
        FROM (
            SELECT date(timestamp) as day, MIN(temp_c) as day_min
            FROM weather_records {where_temp_sql}
            GROUP BY date(timestamp)
        )
    """, params)
    trop_row = cursor.fetchone()
    tropical_nights_count = trop_row["tropical_nights_count"] if trop_row else 0
    very_hot_nights_count = trop_row["very_hot_nights_count"] if trop_row else 0
    
    conn.close()
    
    if not row or row["total_records"] == 0:
        return {
            "total_records": 0,
            "min_temp": None, "max_temp": None, "avg_temp": None,
            "min_hum": None, "max_hum": None, "avg_hum": None,
            "min_temp_in": None, "max_temp_in": None, "avg_temp_in": None,
            "min_hum_in": None, "max_hum_in": None, "avg_hum_in": None,
            "max_wind": None, "avg_wind": None, "max_gust": None,
            "min_press": None, "max_press": None, "avg_press": None,
            "max_solar": None, "max_uv": None,
            "max_rain_rate": None, "total_rain": 0.0,
            "tropical_nights": 0, "very_hot_nights": 0,
            "first_ts": None, "last_ts": None
        }
        
    return {
        "total_records": row["total_records"],
        "min_temp": round(row["min_temp"], 1) if row["min_temp"] is not None else None,
        "max_temp": round(row["max_temp"], 1) if row["max_temp"] is not None else None,
        "avg_temp": round(row["avg_temp"], 1) if row["avg_temp"] is not None else None,
        "min_hum": round(row["min_hum"]) if row["min_hum"] is not None else None,
        "max_hum": round(row["max_hum"]) if row["max_hum"] is not None else None,
        "avg_hum": round(row["avg_hum"]) if row["avg_hum"] is not None else None,
        "min_temp_in": round(row["min_temp_in"], 1) if row["min_temp_in"] is not None else None,
        "max_temp_in": round(row["max_temp_in"], 1) if row["max_temp_in"] is not None else None,
        "avg_temp_in": round(row["avg_temp_in"], 1) if row["avg_temp_in"] is not None else None,
        "min_hum_in": round(row["min_hum_in"]) if row["min_hum_in"] is not None else None,
        "max_hum_in": round(row["max_hum_in"]) if row["max_hum_in"] is not None else None,
        "avg_hum_in": round(row["avg_hum_in"]) if row["avg_hum_in"] is not None else None,
        "max_wind": round(row["max_wind"], 1) if row["max_wind"] is not None else None,
        "avg_wind": round(row["avg_wind"], 1) if row["avg_wind"] is not None else None,
        "max_gust": round(row["max_gust"], 1) if row["max_gust"] is not None else None,
        "min_press": round(row["min_press"], 1) if row["min_press"] is not None else None,
        "max_press": round(row["max_press"], 1) if row["max_press"] is not None else None,
        "avg_press": round(row["avg_press"], 1) if row["avg_press"] is not None else None,
        "max_solar": round(row["max_solar"], 0) if row["max_solar"] is not None else None,
        "max_uv": round(row["max_uv"], 1) if row["max_uv"] is not None else None,
        "max_rain_rate": round(row["max_rain_rate"], 1) if row["max_rain_rate"] is not None else None,
        "total_rain": round(total_rain, 1),
        "tropical_nights": tropical_nights_count,
        "very_hot_nights": very_hot_nights_count,
        "first_ts": row["first_ts"],
        "last_ts": row["last_ts"]
    }

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
        cursor.execute("SELECT * FROM alert_logs WHERE COALESCE(is_read, 0) = 0 ORDER BY id DESC LIMIT ?", (limit,))
    else:
        cursor.execute("SELECT * FROM alert_logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_unread_alerts_count() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM alert_logs WHERE COALESCE(is_read, 0) = 0")
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
    cursor.execute("UPDATE alert_logs SET is_read = 1 WHERE COALESCE(is_read, 0) = 0")
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

def get_alerts_stats() -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Conteggio totale
    cursor.execute("SELECT COUNT(*) FROM alert_logs")
    row_tot = cursor.fetchone()
    total_count = int(row_tot[0]) if row_tot else 0
    
    # 2. Conteggio non lette
    cursor.execute("SELECT COUNT(*) FROM alert_logs WHERE COALESCE(is_read, 0) = 0")
    row_unread = cursor.fetchone()
    unread_count = int(row_unread[0]) if row_unread else 0
    
    # 3. Conteggio odierno
    today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cursor.execute("SELECT COUNT(*) FROM alert_logs WHERE timestamp LIKE ?", (f"{today_prefix}%",))
    row_today = cursor.fetchone()
    today_count = int(row_today[0]) if row_today else 0
    
    # 4. Tipo di notifica più frequente
    cursor.execute("""
        SELECT alert_type, COUNT(*) as c 
        FROM alert_logs 
        GROUP BY alert_type 
        ORDER BY c DESC 
        LIMIT 1
    """)
    top_row = cursor.fetchone()
    top_type = top_row[0] if top_row else None
    top_type_count = int(top_row[1]) if top_row else 0
    
    # 5. Ultimo allarme registrato
    cursor.execute("SELECT timestamp, alert_type, title FROM alert_logs ORDER BY id DESC LIMIT 1")
    latest_row = cursor.fetchone()
    latest_alert = dict(latest_row) if latest_row else None
    
    conn.close()
    return {
        "total_count": total_count,
        "unread_count": unread_count,
        "today_count": today_count,
        "top_type": top_type,
        "top_type_count": top_type_count,
        "latest_alert": latest_alert
    }

def get_latest_alerts_by_type() -> Dict[str, Dict[str, Any]]:
    """
    Recupera l'ultima occorrenza registrata nel DB per ogni alert_type.
    Utile per ricostruire i cooldown e prevenire duplicati al riavvio del server.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT alert_type, timestamp, title, message, data_json
        FROM alert_logs
        WHERE id IN (
            SELECT MAX(id) FROM alert_logs GROUP BY alert_type
        )
    """)
    rows = cursor.fetchall()
    conn.close()
    
    res = {}
    for r in rows:
        try:
            data = json.loads(r["data_json"]) if r["data_json"] else {}
        except Exception:
            data = {}
        res[r["alert_type"]] = {
            "timestamp": r["timestamp"],
            "title": r["title"],
            "message": r["message"],
            "data": data
        }
    return res

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

def get_climate_comparisons() -> Dict[str, Any]:
    """
    Calcola statistiche climatiche e scostamenti storici (Climatologia Locale):
    - Confronto temperatura odierna rispetto alla media degli ultimi 30 giorni.
    - Numero di giorni caldi (Tmax >= 30°C e >= 35°C) nel mese corrente.
    - Giorni piovosi nel mese e accumulo rispetto al periodo.
    """
    tz = settings.get_tz()
    now = settings.now_local()
    
    today_start_local = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=tz)
    today_start_utc = today_start_local.astimezone(timezone.utc).isoformat()
    
    month_start_local = datetime(now.year, now.month, 1, 0, 0, 0, tzinfo=tz)
    month_start_utc = month_start_local.astimezone(timezone.utc).isoformat()
    
    last_30d_utc = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Media temperatura di oggi
    cursor.execute("""
        SELECT AVG(temp_c) as avg_temp, MAX(temp_c) as max_temp, MIN(temp_c) as min_temp
        FROM weather_records
        WHERE timestamp >= ? AND temp_c IS NOT NULL
    """, (today_start_utc,))
    today_row = cursor.fetchone()
    today_avg = round(float(today_row["avg_temp"]), 1) if today_row and today_row["avg_temp"] is not None else None
    
    # 2. Media temperatura ultimi 30 giorni
    cursor.execute("""
        SELECT AVG(temp_c) as avg_temp
        FROM weather_records
        WHERE timestamp >= ? AND temp_c IS NOT NULL
    """, (last_30d_utc,))
    last_30d_row = cursor.fetchone()
    last_30d_avg = round(float(last_30d_row["avg_temp"]), 1) if last_30d_row and last_30d_row["avg_temp"] is not None else None
    
    diff_30d = None
    diff_30d_str = "Dati storici in accumulo"
    if today_avg is not None and last_30d_avg is not None:
        diff_30d = round(today_avg - last_30d_avg, 1)
        sign = "+" if diff_30d > 0 else ""
        if abs(diff_30d) < 0.4:
            diff_30d_str = f"In linea con la media degli ultimi 30 giorni ({today_avg}°C vs {last_30d_avg}°C)"
        elif diff_30d > 0:
            diff_30d_str = f"Oggi {sign}{diff_30d}°C più caldo della media degli ultimi 30 giorni ({today_avg}°C vs {last_30d_avg}°C)"
        else:
            diff_30d_str = f"Oggi {diff_30d}°C più fresco della media degli ultimi 30 giorni ({today_avg}°C vs {last_30d_avg}°C)"

    # 3. Statistiche termiche del mese corrente (giorni > 30°C, > 35°C, giorni di pioggia)
    cursor.execute("""
        SELECT date(timestamp) as day, MAX(temp_c) as max_t, MIN(temp_c) as min_t, MAX(daily_rain_mm) as max_r
        FROM weather_records
        WHERE timestamp >= ? AND temp_c IS NOT NULL
        GROUP BY date(timestamp)
    """, (month_start_utc,))
    month_days = cursor.fetchall()
    
    days_above_30 = 0
    days_above_35 = 0
    days_rain = 0
    month_temp_sums = []
    
    for row in month_days:
        mt = float(row["max_t"]) if row["max_t"] is not None else None
        mr = float(row["max_r"]) if row["max_r"] is not None else 0.0
        if mt is not None:
            month_temp_sums.append(mt)
            if mt >= 35.0:
                days_above_35 += 1
            if mt >= 30.0:
                days_above_30 += 1
        if mr >= 1.0:
            days_rain += 1

    month_name = ITALIAN_MONTHS.get(now.month, f"Mese {now.month}")
    
    conn.close()
    
    return {
        "today_avg_temp": today_avg,
        "last_30d_avg_temp": last_30d_avg,
        "diff_30d": diff_30d,
        "diff_30d_str": diff_30d_str,
        "month_name": month_name,
        "month_days_count": len(month_days),
        "days_above_30": days_above_30,
        "days_above_35": days_above_35,
        "days_rain": days_rain
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

# ----------------- GESTIONE DISPOSITIVI TUYA / SMART LIFE -----------------

def get_tuya_device_configs() -> Dict[str, Dict[str, Any]]:
    """Restituisce le preferenze di attivazione e nomi dei dispositivi Tuya."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT device_id, enabled, custom_name, category, icon, updated_at FROM tuya_devices_config")
    rows = cursor.fetchall()
    conn.close()
    return {
        r["device_id"]: {
            "device_id": r["device_id"],
            "enabled": bool(r["enabled"]),
            "custom_name": r["custom_name"],
            "category": r["category"],
            "icon": r["icon"],
            "updated_at": r["updated_at"]
        }
        for r in rows
    }

def save_tuya_device_config(
    device_id: str,
    enabled: bool,
    custom_name: Optional[str] = None,
    category: Optional[str] = None,
    icon: Optional[str] = None
) -> None:
    """Salva o aggiorna lo stato di abilitazione e il nome personalizzato di un dispositivo Tuya."""
    conn = get_connection()
    cursor = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        INSERT INTO tuya_devices_config (device_id, enabled, custom_name, category, icon, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(device_id) DO UPDATE SET
            enabled=excluded.enabled,
            custom_name=COALESCE(excluded.custom_name, tuya_devices_config.custom_name),
            category=COALESCE(excluded.category, tuya_devices_config.category),
            icon=COALESCE(excluded.icon, tuya_devices_config.icon),
            updated_at=excluded.updated_at
    """, (device_id.strip(), 1 if enabled else 0, custom_name, category, icon, now_iso))
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

# ----------------- STATISTICHE NOTTI TROPICALI & CLIMATOLOGIA -----------------

def get_tropical_nights_stats(year: Optional[int] = None) -> Dict[str, Any]:
    """
    Calcola le statistiche climatologiche delle Notti Tropicali (Tmin >= 20°C)
    e Notti Roventi (Tmin >= 25°C) per l'anno specificato (o anno corrente).
    Include streak consecutivi, notti più calde, e distribuzione mensile.
    """
    tz = settings.get_tz()
    now = settings.now_local()
    if year is None:
        year = now.year

    conn = get_connection()
    cursor = conn.cursor()

    year_start = f"{year}-01-01T00:00:00"
    year_end = f"{year}-12-31T23:59:59"

    cursor.execute("""
        SELECT 
            date(timestamp) as day_str,
            ROUND(MIN(temp_c), 1) as min_temp,
            ROUND(MAX(temp_c), 1) as max_temp,
            ROUND(AVG(temp_c), 1) as avg_temp,
            COUNT(*) as readings_count
        FROM weather_records
        WHERE timestamp >= ? AND timestamp <= ? AND temp_c IS NOT NULL
        GROUP BY date(timestamp)
        HAVING readings_count >= 1
        ORDER BY day_str ASC
    """, (year_start, year_end))
    days = cursor.fetchall()
    conn.close()

    total_tropical_nights = 0
    total_super_tropical_nights = 0
    highest_min_temp = None
    highest_min_day = None
    
    monthly_counts = {
        "05": 0, "06": 0, "07": 0, "08": 0, "09": 0, "10": 0
    }
    
    max_streak = 0
    temp_streak = 0
    recent_tropical_days = []

    today_str = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    today_is_tropical = False
    yesterday_was_tropical = False

    for d in days:
        d_str = d["day_str"]
        min_t = d["min_temp"]
        if min_t is None:
            continue
        
        is_trop = (min_t >= settings.TROPICAL_NIGHT_TEMP_THRESHOLD_C)
        is_super = (min_t >= settings.SUPER_TROPICAL_NIGHT_TEMP_THRESHOLD_C)

        if d_str == today_str and is_trop:
            today_is_tropical = True
        if d_str == yesterday_str and is_trop:
            yesterday_was_tropical = True

        if is_trop:
            total_tropical_nights += 1
            temp_streak += 1
            if temp_streak > max_streak:
                max_streak = temp_streak
            
            m = d_str[5:7]
            if m in monthly_counts:
                monthly_counts[m] += 1
                
            if is_super:
                total_super_tropical_nights += 1
                
            if highest_min_temp is None or min_t > highest_min_temp:
                highest_min_temp = min_t
                highest_min_day = d_str

            recent_tropical_days.append({
                "date": d_str,
                "min_temp": min_t,
                "is_super": is_super
            })
        else:
            temp_streak = 0

    # Calcolo streak corrente a ritroso
    streak_count = 0
    days_dict = {d["day_str"]: d["min_temp"] for d in days if d["min_temp"] is not None}
    check_dt = now.date()
    if today_str not in days_dict or days_dict[today_str] < settings.TROPICAL_NIGHT_TEMP_THRESHOLD_C:
        check_dt = check_dt - timedelta(days=1)
    
    while True:
        c_str = check_dt.strftime("%Y-%m-%d")
        if c_str in days_dict and days_dict[c_str] >= settings.TROPICAL_NIGHT_TEMP_THRESHOLD_C:
            streak_count += 1
            check_dt = check_dt - timedelta(days=1)
        else:
            break

    # Mappa nomi mesi italiani per UI
    month_names_it = {
        "05": "Maggio",
        "06": "Giugno",
        "07": "Luglio",
        "08": "Agosto",
        "09": "Settembre",
        "10": "Ottobre"
    }
    monthly_stats = [
        {"month_key": k, "name": month_names_it[k], "count": v}
        for k, v in monthly_counts.items()
    ]

    return {
        "year": year,
        "threshold_c": settings.TROPICAL_NIGHT_TEMP_THRESHOLD_C,
        "super_threshold_c": settings.SUPER_TROPICAL_NIGHT_TEMP_THRESHOLD_C,
        "total_tropical_nights": total_tropical_nights,
        "total_super_tropical_nights": total_super_tropical_nights,
        "highest_min_temp": highest_min_temp,
        "highest_min_day": highest_min_day,
        "current_streak": streak_count,
        "max_streak": max_streak,
        "today_is_tropical": today_is_tropical,
        "yesterday_was_tropical": yesterday_was_tropical,
        "monthly_counts": monthly_counts,
        "monthly_stats": monthly_stats,
        "recent_tropical_days": recent_tropical_days[-10:]
    }

# ----------------- STATO & TREND UMIDITÀ TERRENO -----------------

def get_soil_moisture_summary() -> Dict[str, Any]:
    """
    Calcola lo stato in tempo reale, il trend 24h e il livello di salute per i sensori di umidità WH51.
    """
    latest = get_latest_reading() or {}
    soil = latest.get("soil_moisture", {})
    aliases = get_sensor_aliases()

    if not soil:
        return {
            "has_sensors": False,
            "channels": {},
            "avg_moisture": None,
            "status": "none",
            "status_text": "Nessun sensore WH51 configurato"
        }

    conn = get_connection()
    cursor = conn.cursor()

    now = datetime.now(timezone.utc)
    t_24h = (now - timedelta(hours=24)).isoformat()

    cursor.execute("""
        SELECT soil_moisture_json FROM weather_records
        WHERE timestamp <= ? AND soil_moisture_json IS NOT NULL
        ORDER BY timestamp DESC LIMIT 1
    """, (t_24h,))
    row_24h = cursor.fetchone()
    conn.close()

    soil_24h = json.loads(row_24h["soil_moisture_json"]) if row_24h and row_24h["soil_moisture_json"] else {}

    channels_data = {}
    values_list = []

    for ch, val in soil.items():
        if val is None:
            continue
        v = float(val)
        values_list.append(v)

        alias = aliases.get(f"soil_{ch}") or aliases.get(ch) or f"Sensore {ch.upper()}"
        v_24h = float(soil_24h.get(ch)) if soil_24h.get(ch) is not None else None
        diff_24h = round(v - v_24h, 1) if v_24h is not None else 0.0

        if v < 15.0:
            status_code = "critical"
            status_label = "Critico / Arido"
            badge_class = "badge-danger"
        elif v < settings.SOIL_MOISTURE_LOW_THRESHOLD:
            status_code = "dry"
            status_label = "Terreno Secco"
            badge_class = "badge-warning"
        elif v <= 60.0:
            status_code = "optimal"
            status_label = "Umidità Ottimale"
            badge_class = "badge-success"
        else:
            status_code = "wet"
            status_label = "Molto Umido"
            badge_class = "badge-info"

        if diff_24h > 5.0:
            trend_icon = "↗"
            trend_text = f"+{diff_24h}% (Irrigato)"
        elif diff_24h < -5.0:
            trend_icon = "↘"
            trend_text = f"{diff_24h}% (Asciugatura)"
        else:
            trend_icon = "→"
            trend_text = "Stabile"

        channels_data[ch] = {
            "channel": ch,
            "name": alias,
            "value": v,
            "diff_24h": diff_24h,
            "trend_icon": trend_icon,
            "trend_text": trend_text,
            "status": status_code,
            "status_label": status_label,
            "badge_class": badge_class
        }

    avg_moisture = round(sum(values_list) / len(values_list), 1) if values_list else None

    return {
        "has_sensors": len(channels_data) > 0,
        "channels": channels_data,
        "avg_moisture": avg_moisture,
        "status": "optimal" if avg_moisture and avg_moisture >= settings.SOIL_MOISTURE_LOW_THRESHOLD else ("dry" if avg_moisture else "none"),
        "status_text": "Umidità Ottimale" if avg_moisture and avg_moisture >= settings.SOIL_MOISTURE_LOW_THRESHOLD else ("Terreno Secco" if avg_moisture else "In attesa dati")
    }


# ----------------- GESTIONE AUTOMAZIONI CLIMATIZZATORI (LG THINQ) -----------------

DEFAULT_CLIMATE_AUTOMATIONS_CONFIG: Dict[str, Any] = {
    "master_enabled": True,
    # 1. Uscita di casa: 'off' (spegnimento automatico), 'notify' (solo notifica per presenza altri), 'disabled'
    "away_action": "notify",
    "away_delay_min": 10,
    # 2. Max Runtime / Dimenticanza: 'off', 'notify', 'disabled'
    "max_runtime_action": "notify",
    "max_runtime_hours": 5,
    # 3. Free cooling notturno: 'off', 'notify', 'disabled'
    "night_cooling_action": "notify",
    "night_start_hour": 23,
    "night_end_hour": 7,
    "night_temp_diff": 1.5,
    # 4. Pre-cooling solare Aton: 'on', 'notify', 'disabled'
    "solar_preconditioning_action": "notify",
    "solar_surplus_w": 1800,
    "solar_min_soc": 80,
    "solar_target_temp": 25.0,
    # 5. Protezione batteria scarica / rete: 'off', 'notify', 'disabled'
    "battery_guard_action": "notify",
    "battery_min_soc": 20
}

def get_climate_automations_config() -> Dict[str, Any]:
    """Restituisce le preferenze salvate per le automazioni dei climatizzatori."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value_json FROM climate_automations_config WHERE key = 'main'")
    row = cursor.fetchone()
    conn.close()

    cfg = DEFAULT_CLIMATE_AUTOMATIONS_CONFIG.copy()
    if row and row["value_json"]:
        try:
            saved = json.loads(row["value_json"])
            cfg.update(saved)
        except Exception:
            pass
    return cfg

def save_climate_automations_config(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Salva le preferenze delle automazioni climatizzatori su SQLite con validazione e sanitizzazione."""
    current = get_climate_automations_config()
    
    if isinstance(config_dict, dict):
        if "master_enabled" in config_dict:
            current["master_enabled"] = bool(config_dict["master_enabled"])
        if "away_action" in config_dict and config_dict["away_action"] in ("off", "notify", "disabled"):
            current["away_action"] = str(config_dict["away_action"])
        if "away_delay_min" in config_dict:
            try:
                current["away_delay_min"] = max(1, min(120, int(config_dict["away_delay_min"])))
            except (ValueError, TypeError):
                pass
        if "max_runtime_action" in config_dict and config_dict["max_runtime_action"] in ("off", "notify", "disabled"):
            current["max_runtime_action"] = str(config_dict["max_runtime_action"])
        if "max_runtime_hours" in config_dict:
            try:
                current["max_runtime_hours"] = max(1.0, min(24.0, float(config_dict["max_runtime_hours"])))
            except (ValueError, TypeError):
                pass
        if "night_cooling_action" in config_dict and config_dict["night_cooling_action"] in ("off", "notify", "disabled"):
            current["night_cooling_action"] = str(config_dict["night_cooling_action"])
        if "solar_preconditioning_action" in config_dict and config_dict["solar_preconditioning_action"] in ("on", "notify", "disabled"):
            current["solar_preconditioning_action"] = str(config_dict["solar_preconditioning_action"])
        if "battery_guard_action" in config_dict and config_dict["battery_guard_action"] in ("off", "notify", "disabled"):
            current["battery_guard_action"] = str(config_dict["battery_guard_action"])

    now_iso = datetime.now(timezone.utc).isoformat()
    json_str = json.dumps(current, ensure_ascii=False)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO climate_automations_config (key, value_json, updated_at)
        VALUES ('main', ?, ?)
        ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
    """, (json_str, now_iso))
    conn.commit()
    conn.close()
    return current
