import os
import time
import json
import math
import sqlite3
import logging
import requests
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ----------------- CONFIGURATION -----------------
HOST = "0.0.0.0"
PORT = 8080
DATA_DIR = os.getenv("DATA_DIR", "/data")
os.makedirs(DATA_DIR, exist_ok=True)

SOIL_MOISTURE_LOW_THRESHOLD = float(os.getenv("SOIL_MOISTURE_LOW_THRESHOLD", "25.0"))
LIGHTNING_MAX_DISTANCE_KM = float(os.getenv("LIGHTNING_MAX_DISTANCE_KM", "30.0"))
TEMP_FREEZE_THRESHOLD_C = float(os.getenv("TEMP_FREEZE_THRESHOLD_C", "1.0"))
TEMP_HEAT_THRESHOLD_C = float(os.getenv("TEMP_HEAT_THRESHOLD_C", "38.0"))
RAIN_RATE_ALERT_MM_HR = float(os.getenv("RAIN_RATE_ALERT_MM_HR", "5.0"))

LIGHTNING_COOLDOWN_MIN = int(os.getenv("LIGHTNING_COOLDOWN_MIN", "5"))
SOIL_MOISTURE_COOLDOWN_MIN = int(os.getenv("SOIL_MOISTURE_COOLDOWN_MIN", "180"))
TEMP_ALERT_COOLDOWN_MIN = int(os.getenv("TEMP_ALERT_COOLDOWN_MIN", "120"))
RAIN_ALERT_COOLDOWN_MIN = int(os.getenv("RAIN_ALERT_COOLDOWN_MIN", "30"))

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "ecowitt_weather_alerts_curia")
ENABLE_NTFY = True

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ecowitt_hub")

# ----------------- DATABASE -----------------
DB_PATH = os.path.join(DATA_DIR, "weather_history.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alert_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            data_json TEXT
        )
    """)
    
    # Migrazione colonne opzionali se il DB esisteva già
    cursor.execute("PRAGMA table_info(weather_records)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    cols_to_add = {
        "dew_point_c": "REAL",
        "temp_in_c": "REAL",
        "humidity_in": "REAL",
        "pressure_abs_hpa": "REAL",
        "wind_dir_deg": "INTEGER",
        "max_daily_gust_kmh": "REAL",
        "event_rain_mm": "REAL",
        "yearly_rain_mm": "REAL",
        "vpd": "REAL"
    }
    for col, ctype in cols_to_add.items():
        if col not in existing_cols:
            try:
                cursor.execute(f"ALTER TABLE weather_records ADD COLUMN {col} {ctype}")
            except Exception:
                pass

    conn.commit()
    conn.close()

init_db()

def save_reading(data: Dict[str, Any]):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    lightning = data.get("lightning", {})
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
        data.get("temp_c"),
        data.get("humidity"),
        data.get("dew_point_c"),
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
        json.dumps(data.get("raw_payload", {}))
    ))
    conn.commit()
    conn.close()

def get_latest_reading() -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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
    return d

def get_history_readings(hours: int = 24, limit: int = 500) -> List[Dict[str, Any]]:
    since_time = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM weather_records WHERE timestamp >= ? ORDER BY timestamp ASC LIMIT ?", (since_time, limit))
    rows = cursor.fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        if d.get("soil_moisture_json"):
            try:
                d["soil_moisture"] = json.loads(d["soil_moisture_json"])
            except Exception:
                d["soil_moisture"] = {}
        result.append(d)
    return result

def log_alert_db(alert_type: str, title: str, message: str, data: Optional[Dict[str, Any]] = None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO alert_logs (timestamp, alert_type, title, message, data_json)
        VALUES (?, ?, ?, ?, ?)
    """, (datetime.now(timezone.utc).isoformat(), alert_type, title, message, json.dumps(data or {})))
    conn.commit()
    conn.close()

def get_alert_logs(limit: int = 20) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM alert_logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ----------------- NOTIFIER -----------------
def send_push_notification(alert_type: str, title: str, message: str, priority: str = "high", extra_data: Optional[Dict[str, str]] = None):
    logger.info(f"[NOTIFICA] [{alert_type}] {title}: {message}")
    log_alert_db(alert_type, title, message, extra_data)

    if ENABLE_NTFY and NTFY_TOPIC:
        try:
            tag_map = {
                "lightning": "warning,zap",
                "soil_dry": "herb,droplet",
                "freeze": "snowflake,cold_face",
                "heatwave": "hot_face,sunny",
                "rain": "cloud_with_rain"
            }
            headers = {
                "Title": title.encode("utf-8"),
                "Priority": "5" if priority == "high" else "3",
                "Tags": tag_map.get(alert_type, "loudspeaker")
            }
            requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=message.encode("utf-8"), headers=headers, timeout=5)
        except Exception as e:
            logger.error(f"Errore invio ntfy: {e}")

# ----------------- UTILS & PARSER -----------------
def f_to_c(f):
    if f is None or f == "":
        return None
    try:
        return round((float(f) - 32.0) * 5.0 / 9.0, 1)
    except Exception:
        return None

def inhg_to_hpa(i):
    if i is None or i == "":
        return None
    try:
        return round(float(i) * 33.8639, 1)
    except Exception:
        return None

def mph_to_kmh(m):
    if m is None or m == "":
        return None
    try:
        return round(float(m) * 1.60934, 1)
    except Exception:
        return None

def in_to_mm(i):
    if i is None or i == "":
        return None
    try:
        return round(float(i) * 25.4, 1)
    except Exception:
        return None

def s_float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except Exception:
        return None

def s_int(v):
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except Exception:
        return None

def calc_dew_point(temp_c, humidity):
    if temp_c is None or humidity is None:
        return None
    try:
        a = 17.27
        b = 237.7
        alpha = ((a * temp_c) / (b + temp_c)) + math.log(float(humidity) / 100.0)
        dp = (b * alpha) / (a - alpha)
        return round(dp, 1)
    except Exception:
        return None

def calc_vpd(temp_c, humidity):
    if temp_c is None or humidity is None:
        return None
    try:
        t = float(temp_c)
        rh = float(humidity)
        if rh < 0 or rh > 100:
            return None
        vp_sat = 0.61078 * math.exp((17.27 * t) / (t + 237.3))
        vpd = vp_sat * (1.0 - (rh / 100.0))
        return round(max(0.0, vpd), 2)
    except Exception:
        return None

def deg_to_compass(deg):
    if deg is None:
        return "--"
    try:
        d = float(deg)
        val = int((d / 22.5) + 0.5)
        dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        return f"{int(d)}° ({dirs[val % 16]})"
    except Exception:
        return f"{deg}°"

def parse_ecowitt(raw: Dict[str, Any]) -> Dict[str, Any]:
    date_str = raw.get("dateutc")
    try:
        ts = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).isoformat()
    except Exception:
        ts = datetime.now(timezone.utc).isoformat()

    soil = {}
    for i in range(1, 9):
        k = f"soilmoisture{i}"
        if k in raw and raw[k] != "":
            soil[f"ch{i}"] = s_float(raw[k])

    l_count = s_int(raw.get("lightning_num"))
    l_dist = s_float(raw.get("lightning_distance"))
    l_epoch = s_int(raw.get("lightning_time"))
    l_time = None
    if l_epoch and l_epoch > 0:
        try:
            l_time = datetime.fromtimestamp(l_epoch, tz=timezone.utc).isoformat()
        except Exception:
            pass

    out_temp_c = f_to_c(raw.get("tempf"))
    out_hum = s_float(raw.get("humidity"))
    dew_c = calc_dew_point(out_temp_c, out_hum)
    vpd_val = s_float(raw.get("vpd"))
    if vpd_val is None and out_temp_c is not None and out_hum is not None:
        vpd_val = calc_vpd(out_temp_c, out_hum)

    return {
        "timestamp": ts,
        "station_mac": raw.get("PASSKEY"),
        "station_model": raw.get("model", raw.get("stationtype", "Sainlogic / Ecowitt")),
        "temp_c": out_temp_c,
        "humidity": out_hum,
        "dew_point_c": dew_c,
        "temp_in_c": f_to_c(raw.get("tempinf")),
        "humidity_in": s_float(raw.get("humidityin")),
        "pressure_rel_hpa": inhg_to_hpa(raw.get("baromrelin")),
        "pressure_abs_hpa": inhg_to_hpa(raw.get("baromabsin")),
        "wind_speed_kmh": mph_to_kmh(raw.get("windspeedmph")),
        "wind_gust_kmh": mph_to_kmh(raw.get("windgustmph")),
        "wind_dir_deg": s_int(raw.get("winddir")),
        "max_daily_gust_kmh": mph_to_kmh(raw.get("maxdailygust")),
        "rain_rate_mm_hr": in_to_mm(raw.get("rainratein")),
        "daily_rain_mm": in_to_mm(raw.get("dailyrainin")),
        "event_rain_mm": in_to_mm(raw.get("eventrainin")),
        "yearly_rain_mm": in_to_mm(raw.get("yearlyrainin")),
        "solar_radiation": s_float(raw.get("solarradiation")),
        "uv_index": s_int(raw.get("uv")),
        "vpd": vpd_val,
        "sensor_battery_wh65": raw.get("wh65batt"),
        "freq": raw.get("freq"),
        "lightning": {
            "count_total": l_count,
            "distance_km": l_dist,
            "last_strike_epoch": l_epoch,
            "last_strike_time": l_time
        },
        "soil_moisture": soil,
        "raw_payload": raw
    }

# ----------------- ALERT ENGINE -----------------
class AlertEngine:
    def __init__(self):
        self.last_lightning_epoch = None
        self.last_lightning_count = 0
        self.last_lightning_alert = 0.0
        self.last_soil_alert = {}
        self.last_freeze_alert = 0.0
        self.last_heat_alert = 0.0
        self.last_rain_alert = 0.0

    def evaluate(self, data: Dict[str, Any]):
        now = time.time()
        
        # 1. Fulmini (WH57)
        lightning = data.get("lightning", {})
        strike_epoch = lightning.get("last_strike_epoch")
        count = lightning.get("count_total") or 0
        dist_km = lightning.get("distance_km")

        if self.last_lightning_epoch is None:
            self.last_lightning_epoch = strike_epoch
            self.last_lightning_count = count
        else:
            is_new = (strike_epoch and strike_epoch != self.last_lightning_epoch) or (count > self.last_lightning_count)
            if strike_epoch: self.last_lightning_epoch = strike_epoch
            self.last_lightning_count = count

            if is_new and dist_km is not None and dist_km <= LIGHTNING_MAX_DISTANCE_KM:
                if (now - self.last_lightning_alert) >= (LIGHTNING_COOLDOWN_MIN * 60):
                    self.last_lightning_alert = now
                    send_push_notification("lightning", "⚡ Temporale in arrivo!", f"Fulmine rilevato a {dist_km} km dalla tua stazione meteo!", "high", {"distance_km": str(dist_km)})

        # 2. Umidità Terreno (WH51)
        for ch, val in data.get("soil_moisture", {}).items():
            if val is not None and val <= SOIL_MOISTURE_LOW_THRESHOLD:
                if (now - self.last_soil_alert.get(ch, 0)) >= (SOIL_MOISTURE_COOLDOWN_MIN * 60):
                    self.last_soil_alert[ch] = now
                    send_push_notification("soil_dry", "🌱 Annaffia le piante", f"Umidità terreno ({ch}) scesa al {val}% (soglia: {SOIL_MOISTURE_LOW_THRESHOLD}%).", "normal", {"channel": ch, "moisture": str(val)})

        # 3. Temperature
        temp = data.get("temp_c")
        if temp is not None:
            if temp <= TEMP_FREEZE_THRESHOLD_C and (now - self.last_freeze_alert) >= (TEMP_ALERT_COOLDOWN_MIN * 60):
                self.last_freeze_alert = now
                send_push_notification("freeze", "❄️ Allerta Gelo", f"Temperatura scesa a {temp}°C! Rischio gelata per piante e tubi.", "high", {"temp_c": str(temp)})
            elif temp >= TEMP_HEAT_THRESHOLD_C and (now - self.last_heat_alert) >= (TEMP_ALERT_COOLDOWN_MIN * 60):
                self.last_heat_alert = now
                send_push_notification("heatwave", "🔥 Caldo Estremo", f"Temperatura salita a {temp}°C!", "normal", {"temp_c": str(temp)})

        # 4. Pioggia intensa
        rain = data.get("rain_rate_mm_hr")
        if rain is not None and rain >= RAIN_RATE_ALERT_MM_HR and (now - self.last_rain_alert) >= (RAIN_ALERT_COOLDOWN_MIN * 60):
            self.last_rain_alert = now
            send_push_notification("rain", "🌧️ Pioggia Intensa", f"Rilevato forte rovescio di pioggia: intensità {rain} mm/h.", "normal", {"rain_rate_mm_hr": str(rain)})

engine = AlertEngine()

# ----------------- FASTAPI SERVER -----------------
app = FastAPI(title="Ecowitt Weather Station Hub")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def process_background(raw_data: dict):
    try:
        parsed = parse_ecowitt(raw_data)
        save_reading(parsed)
        engine.evaluate(parsed)
    except Exception as e:
        logger.error(f"Errore processing: {e}")

@app.post("/api/ecowitt")
@app.get("/api/ecowitt")
async def ingest_ecowitt(request: Request, bg: BackgroundTasks):
    form = await request.form()
    data = dict(form) or dict(request.query_params)
    logger.info(f"Ricevuti dati da Stazione Meteo (Model: {data.get('model', data.get('stationtype', 'N/D'))})")
    bg.add_task(process_background, data)
    return {"status": "success"}

@app.get("/api/live")
async def live():
    latest = get_latest_reading()
    if not latest:
        return {"message": "In attesa dei primi dati dalla stazione"}
    return latest

@app.get("/api/history")
async def history(hours: int = 24):
    return {"history": get_history_readings(hours=hours)}

@app.get("/api/alerts")
async def alerts():
    return {"alerts": get_alert_logs()}

@app.post("/api/test-alert")
@app.get("/api/test-alert")
async def test_alert(alert_type: str = "lightning"):
    send_push_notification(alert_type, "⚡ Test Notifica Stazione Meteo", "Questo è un test di allerta dal tuo server meteo QNAP!", "high")
    return {"status": "sent", "topic": NTFY_TOPIC}

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    latest = get_latest_reading() or {}
    raw = {}
    if latest.get("raw_data_json"):
        try:
            raw = json.loads(latest["raw_data_json"])
        except Exception:
            raw = {}
            
    ts_val = latest.get("timestamp", "In attesa...")
    temp_val = latest.get("temp_c", "--")
    hum_val = latest.get("humidity", "--")
    dew_val = latest.get("dew_point_c") or calc_dew_point(latest.get("temp_c"), latest.get("humidity")) or "--"
    
    press_rel = latest.get("pressure_rel_hpa", "--")
    press_abs = latest.get("pressure_abs_hpa") or inhg_to_hpa(raw.get("baromabsin")) or "--"
    
    wind_spd = latest.get("wind_speed_kmh", "--")
    wind_gst = latest.get("wind_gust_kmh", "--")
    wind_deg = latest.get("wind_dir_deg") if latest.get("wind_dir_deg") is not None else s_int(raw.get("winddir"))
    wind_dir_txt = deg_to_compass(wind_deg)
    max_gust = latest.get("max_daily_gust_kmh") or mph_to_kmh(raw.get("maxdailygust")) or "--"
    
    rain_rate = latest.get("rain_rate_mm_hr", 0.0)
    rain_day = latest.get("daily_rain_mm", 0.0)
    rain_year = latest.get("yearly_rain_mm") or in_to_mm(raw.get("yearlyrainin")) or "--"
    
    solar = latest.get("solar_radiation", 0.0)
    uv = latest.get("uv_index", 0)
    vpd_val = latest.get("vpd") or raw.get("vpd") or "--"
    
    temp_in = latest.get("temp_in_c") or f_to_c(raw.get("tempinf")) or "--"
    hum_in = latest.get("humidity_in") or s_float(raw.get("humidityin")) or "--"
    
    model_name = raw.get("model", raw.get("stationtype", "Sainlogic / Ecowitt"))
    batt_wh65 = "🟢 Ottima / OK" if raw.get("wh65batt") == "0" else ("🔴 Bassa" if raw.get("wh65batt") else "N/D")
    
    light_km = latest.get("lightning_distance_km")
    light_str = f"⚡ {light_km} km" if light_km is not None else "In attesa di gateway GW3000 / sensore WH57"
    
    soil_data = latest.get("soil_moisture", {})
    soil_html = ""
    if soil_data:
        for ch, v in soil_data.items():
            soil_html += f'<div class="item"><span>Umidità {ch}:</span><strong>{v}%</strong></div>'
    else:
        soil_html = '<div class="item text-muted"><span>Sensori WH51:</span><em>In attesa di GW3000 / sensori</em></div>'

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sainlogic & Ecowitt Weather Hub</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: #0b0f19;
            --card-bg: #131b2e;
            --card-border: #1e293b;
            --accent: #38bdf8;
            --accent-glow: rgba(56, 189, 248, 0.15);
            --text: #f1f5f9;
            --text-dim: #94a3b8;
            --success: #10b981;
            --warning: #f59e0b;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: 'Plus Jakarta Sans', system-ui, sans-serif;
            background-color: var(--bg);
            color: var(--text);
            padding: 1.5rem;
            min-height: 100vh;
            display: flex;
            justify-content: center;
        }}
        .container {{
            width: 100%;
            max-width: 960px;
            display: flex;
            flex-direction: column;
            gap: 1.5rem;
        }}
        .header {{
            background: linear-gradient(135deg, #1e293b, #0f172a);
            border: 1px solid var(--card-border);
            border-radius: 20px;
            padding: 1.5rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 1rem;
        }}
        .title-group h1 {{
            font-size: 1.6rem;
            font-weight: 800;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .title-group p {{
            color: var(--text-dim);
            font-size: 0.88rem;
            margin-top: 4px;
        }}
        .badge-live {{
            display: flex;
            align-items: center;
            gap: 8px;
            background: rgba(16, 185, 129, 0.15);
            color: var(--success);
            border: 1px solid rgba(16, 185, 129, 0.3);
            padding: 6px 14px;
            border-radius: 30px;
            font-size: 0.85rem;
            font-weight: 700;
        }}
        .badge-live::before {{
            content: "";
            width: 8px;
            height: 8px;
            background: var(--success);
            border-radius: 50%;
            animation: pulse 2s infinite;
        }}
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; transform: scale(1); }}
            50% {{ opacity: 0.4; transform: scale(1.2); }}
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 1.25rem;
        }}
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 18px;
            padding: 1.4rem;
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }}
        .card-header {{
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 1.1rem;
            font-weight: 700;
            color: var(--accent);
            border-bottom: 1px solid rgba(255,255,255,0.06);
            padding-bottom: 0.75rem;
        }}
        .main-stat {{
            display: flex;
            align-items: baseline;
            gap: 6px;
        }}
        .main-stat .val {{
            font-size: 2.5rem;
            font-weight: 800;
            color: #fff;
            line-height: 1;
        }}
        .main-stat .unit {{
            font-size: 1.2rem;
            color: var(--text-dim);
            font-weight: 600;
        }}
        .item-list {{
            display: flex;
            flex-direction: column;
            gap: 0.6rem;
        }}
        .item {{
            display: flex;
            justify-content: space-between;
            font-size: 0.92rem;
            color: var(--text-dim);
        }}
        .item strong {{
            color: var(--text);
            font-weight: 600;
        }}
        .text-muted {{
            color: #64748b;
        }}
        .btn {{
            background: linear-gradient(135deg, #0284c7, #0369a1);
            color: white;
            padding: 0.9rem 1.5rem;
            border-radius: 12px;
            border: none;
            font-weight: 700;
            cursor: pointer;
            text-align: center;
            text-decoration: none;
            display: inline-block;
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }}
        .btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(2, 132, 199, 0.4);
        }}
        .footer {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 1rem;
            padding: 0.5rem;
            font-size: 0.85rem;
            color: var(--text-dim);
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- HEADER -->
        <div class="header">
            <div class="title-group">
                <h1>🌤️ Stazione Meteo Hub</h1>
                <p>Dispositivo: <strong>{model_name}</strong> • Ultimo pacchetto: <span id="ts">{ts_val}</span></p>
            </div>
            <div class="badge-live">LIVE RICEZIONE ATTIVA</div>
        </div>

        <!-- GRID CARDS -->
        <div class="grid">
            <!-- 1. TEMPERATURA & UMIDITA ESTERNA -->
            <div class="card">
                <div class="card-header">🌡️ Esterno (7 in 1)</div>
                <div class="main-stat">
                    <span class="val" id="temp_c">{temp_val}</span>
                    <span class="unit">°C</span>
                </div>
                <div class="item-list">
                    <div class="item"><span>Umidità:</span> <strong id="humidity">{hum_val} %</strong></div>
                    <div class="item"><span>Punto di Rugiada:</span> <strong id="dew_point">{dew_val} °C</strong></div>
                    <div class="item"><span>Pressione Relativa:</span> <strong id="press_rel">{press_rel} hPa</strong></div>
                    <div class="item"><span>Pressione Assoluta:</span> <strong id="press_abs">{press_abs} hPa</strong></div>
                </div>
            </div>

            <!-- 2. VENTO -->
            <div class="card">
                <div class="card-header">💨 Vento</div>
                <div class="main-stat">
                    <span class="val" id="wind_spd">{wind_spd}</span>
                    <span class="unit">km/h</span>
                </div>
                <div class="item-list">
                    <div class="item"><span>Raffica attuale:</span> <strong id="wind_gst">{wind_gst} km/h</strong></div>
                    <div class="item"><span>Raffica max oggi:</span> <strong id="max_gust">{max_gust} km/h</strong></div>
                    <div class="item"><span>Direzione:</span> <strong id="wind_dir">{wind_dir_txt}</strong></div>
                </div>
            </div>

            <!-- 3. PIOGGIA -->
            <div class="card">
                <div class="card-header">🌧️ Pioggia</div>
                <div class="main-stat">
                    <span class="val" id="rain_rate">{rain_rate}</span>
                    <span class="unit">mm/h</span>
                </div>
                <div class="item-list">
                    <div class="item"><span>Pioggia di oggi:</span> <strong id="rain_day">{rain_day} mm</strong></div>
                    <div class="item"><span>Pioggia totale anno:</span> <strong id="rain_year">{rain_year} mm</strong></div>
                </div>
            </div>

            <!-- 4. SOLE & UV & INTERNO -->
            <div class="card">
                <div class="card-header">☀️ Sole, UV & Console</div>
                <div class="item-list" style="margin-top: 0.5rem;">
                    <div class="item"><span>Radiazione Solare:</span> <strong id="solar">{solar} W/m²</strong></div>
                    <div class="item"><span>Indice UV:</span> <strong id="uv">{uv}</strong></div>
                    <div class="item"><span>VPD (Deficit Pressione):</span> <strong id="vpd">{vpd_val} kPa</strong></div>
                    <div style="height: 1px; background: rgba(255,255,255,0.06); margin: 4px 0;"></div>
                    <div class="item"><span>Temperatura Interna:</span> <strong id="temp_in">{temp_in} °C</strong></div>
                    <div class="item"><span>Umidità Interna:</span> <strong id="hum_in">{hum_in} %</strong></div>
                </div>
            </div>

            <!-- 5. FULMINI & TERRENO (GW3000) -->
            <div class="card">
                <div class="card-header">⚡ Fulmini & Terreno</div>
                <div class="item-list">
                    <div class="item"><span>Sensore WH57 (Fulmini):</span> <strong id="lightning">{light_str}</strong></div>
                    {soil_html}
                </div>
            </div>

            <!-- 6. STATO & NOTIFICHE -->
            <div class="card">
                <div class="card-header">🔔 Allarmi & Diagnostica</div>
                <div class="item-list">
                    <div class="item"><span>Batteria Sensore 7-in-1:</span> <strong>{batt_wh65}</strong></div>
                    <div class="item"><span>Canale Push (ntfy):</span> <strong>{NTFY_TOPIC}</strong></div>
                </div>
                <a href="/api/test-alert" class="btn" style="margin-top: 0.5rem;">🚀 Invia Notifica di Test</a>
            </div>
        </div>

        <div class="footer">
            <span>QNAP Weather Hub • Auto-refresh live ogni 10s</span>
            <span>API: <a href="/api/live" style="color: var(--accent); text-decoration: none;">/api/live</a> | <a href="/api/history" style="color: var(--accent); text-decoration: none;">/api/history</a></span>
        </div>
    </div>

    <script>
        function refresh() {{
            fetch('/api/live')
                .then(r => r.json())
                .then(d => {{
                    if (!d || d.message) return;
                    if (d.timestamp) document.getElementById('ts').innerText = d.timestamp;
                    if (d.temp_c !== undefined) document.getElementById('temp_c').innerText = d.temp_c;
                    if (d.humidity !== undefined) document.getElementById('humidity').innerText = d.humidity + ' %';
                    if (d.dew_point_c !== undefined) document.getElementById('dew_point').innerText = d.dew_point_c + ' °C';
                    if (d.pressure_rel_hpa !== undefined) document.getElementById('press_rel').innerText = d.pressure_rel_hpa + ' hPa';
                    if (d.wind_speed_kmh !== undefined) document.getElementById('wind_spd').innerText = d.wind_speed_kmh;
                    if (d.wind_gust_kmh !== undefined) document.getElementById('wind_gst').innerText = d.wind_gust_kmh + ' km/h';
                    if (d.rain_rate_mm_hr !== undefined) document.getElementById('rain_rate').innerText = d.rain_rate_mm_hr;
                    if (d.daily_rain_mm !== undefined) document.getElementById('rain_day').innerText = d.daily_rain_mm + ' mm';
                    if (d.solar_radiation !== undefined) document.getElementById('solar').innerText = d.solar_radiation + ' W/m²';
                    if (d.uv_index !== undefined) document.getElementById('uv').innerText = d.uv_index;
                }})
                .catch(() => {{}});
        }}
        setInterval(refresh, 10000);
    </script>
</body>
</html>"""

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
