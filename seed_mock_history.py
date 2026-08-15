import math
import sys
import random
from datetime import datetime, timezone, timedelta

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from backend.database import save_reading, check_and_update_records, init_db

def seed(days: int = 14):
    init_db()
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(days=days)
    
    print(f"🌱 Generazione di {days} giorni di dati meteo realistici...")
    
    total_steps = days * 24 * 6  # ogni 10 minuti
    current_time = start_time
    
    yearly_rain = 2500.0
    daily_rain = 0.0
    last_day = current_time.day
    
    count = 0
    for i in range(total_steps):
        # Reset pioggia giornaliera a mezzanotte
        if current_time.day != last_day:
            daily_rain = 0.0
            last_day = current_time.day
            
        hour = current_time.hour + current_time.minute / 60.0
        
        # Ciclo temperatura giorno/notte (minima alle 6:00, massima alle 15:00)
        temp_base = 26.0 + 8.0 * math.sin((hour - 9.0) * math.pi / 12.0)
        temp_noise = random.uniform(-1.5, 1.5)
        temp_c = round(temp_base + temp_noise, 1)
        
        # Umidità inversa alla temperatura
        hum_base = 65.0 - 25.0 * math.sin((hour - 9.0) * math.pi / 12.0)
        humidity = round(max(20.0, min(95.0, hum_base + random.uniform(-5.0, 5.0))), 1)
        
        # Pressione
        pressure = round(1013.0 + 4.0 * math.sin(i / 100.0) + random.uniform(-0.5, 0.5), 1)
        
        # Vento
        wind_speed = round(max(0.0, 5.0 + 10.0 * max(0.0, math.sin((hour - 12.0) * math.pi / 12.0)) + random.uniform(-2.0, 5.0)), 1)
        wind_gust = round(wind_speed + random.uniform(2.0, 15.0), 1)
        wind_dir = int((hour * 15.0 + random.uniform(-20.0, 20.0)) % 360)
        
        # Evento pioggia occasionale (es. temporale al 5° giorno)
        rain_rate = 0.0
        if days >= 5 and (days - (i // 144)) == 5 and (14 <= hour <= 16):
            rain_rate = round(random.uniform(8.0, 32.0), 1)
            daily_rain = round(daily_rain + (rain_rate * (10.0 / 60.0)), 1)
            yearly_rain = round(yearly_rain + (rain_rate * (10.0 / 60.0)), 1)
            
        # Sole e UV durante il giorno (6:00 - 20:00)
        if 6 <= hour <= 20:
            sun_factor = max(0.0, math.sin((hour - 6.0) * math.pi / 14.0))
            solar_rad = round(sun_factor * 950.0 + random.uniform(-30.0, 30.0), 1)
            uv_index = int(round(sun_factor * 9.0))
        else:
            solar_rad = 0.0
            uv_index = 0
            
        # Fulmini occasionali durante il temporale
        lightning = {}
        if rain_rate > 10.0:
            lightning = {
                "count_total": int(i // 10),
                "distance_km": round(random.uniform(4.0, 18.0), 1),
                "last_strike_epoch": int(current_time.timestamp()),
                "last_strike_time": current_time.isoformat()
            }
            
        reading = {
            "timestamp": current_time.isoformat(),
            "station_mac": "MOCK_MAC_DEV",
            "station_model": "Sainlogic WS2900 (Test)",
            "temp_c": temp_c,
            "humidity": humidity,
            "temp_in_c": round(25.5 + random.uniform(-0.5, 0.5), 1),
            "humidity_in": round(48.0 + random.uniform(-2.0, 2.0), 1),
            "pressure_rel_hpa": pressure,
            "pressure_abs_hpa": round(pressure - 10.0, 1),
            "wind_dir_deg": wind_dir,
            "wind_speed_kmh": wind_speed,
            "wind_gust_kmh": wind_gust,
            "max_daily_gust_kmh": round(wind_gust + random.uniform(0.0, 5.0), 1),
            "rain_rate_mm_hr": rain_rate,
            "daily_rain_mm": daily_rain,
            "event_rain_mm": daily_rain,
            "yearly_rain_mm": yearly_rain,
            "solar_radiation": solar_rad,
            "uv_index": uv_index,
            "vpd": round(max(0.2, (100.0 - humidity) / 60.0), 2),
            "lightning": lightning,
            "soil_moisture": {"ch1": 42.0, "ch2": 38.0},
            "raw_payload": {"model": "WS2900_V2.01.18", "wh65batt": "0"}
        }
        
        save_reading(reading)
        check_and_update_records(reading)
        count += 1
        current_time += timedelta(minutes=10)
        
    print(f"✅ Inserite {count} letture storiche e calcolati tutti i record estremi!")

if __name__ == "__main__":
    seed(14)
