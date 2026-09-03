from typing import Dict, Any, Optional
from datetime import datetime, timezone

from backend.helpers import (
    safe_float,
    safe_int,
    f_to_c,
    inch_to_mm,
    mph_to_kmh,
    inhg_to_hpa,
)

def parse_ecowitt_payload(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parses Ecowitt raw data format, converts imperial units to standard metric (SI/EU),
    and structures soil moisture and lightning sensor data cleanly.
    """
    # Timestamp
    dateutc_str = raw_data.get("dateutc")
    if dateutc_str:
        try:
            timestamp = datetime.strptime(dateutc_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).isoformat()
        except Exception:
            timestamp = datetime.now(timezone.utc).isoformat()
    else:
        timestamp = datetime.now(timezone.utc).isoformat()

    # Temperature & Humidity (Outdoor)
    temp_f = safe_float(raw_data.get("tempf"))
    temp_c = f_to_c(temp_f)
    humidity = safe_float(raw_data.get("humidity"))

    # Temperature & Humidity (Indoor)
    temp_in_f = safe_float(raw_data.get("tempinf"))
    temp_in_c = f_to_c(temp_in_f)
    humidity_in = safe_float(raw_data.get("humidityin"))

    # Pressure
    barom_rel_inhg = safe_float(raw_data.get("baromrelin"))
    barom_rel_hpa = inhg_to_hpa(barom_rel_inhg)
    barom_abs_inhg = safe_float(raw_data.get("baromabsin"))
    barom_abs_hpa = inhg_to_hpa(barom_abs_inhg)

    # Wind
    wind_dir = safe_int(raw_data.get("winddir"))
    wind_speed_mph = safe_float(raw_data.get("windspeedmph"))
    wind_speed_kmh = mph_to_kmh(wind_speed_mph)
    wind_gust_mph = safe_float(raw_data.get("windgustmph"))
    wind_gust_kmh = mph_to_kmh(wind_gust_mph)
    max_daily_gust_mph = safe_float(raw_data.get("maxdailygust"))
    max_daily_gust_kmh = mph_to_kmh(max_daily_gust_mph)

    # Rain (Rate & Accumulations)
    rain_rate_in = safe_float(raw_data.get("rainratein"))
    rain_rate_mm = inch_to_mm(rain_rate_in)
    event_rain_in = safe_float(raw_data.get("eventrainin"))
    event_rain_mm = inch_to_mm(event_rain_in)
    hourly_rain_in = safe_float(raw_data.get("hourlyrainin"))
    hourly_rain_mm = inch_to_mm(hourly_rain_in)
    daily_rain_in = safe_float(raw_data.get("dailyrainin"))
    daily_rain_mm = inch_to_mm(daily_rain_in)
    weekly_rain_in = safe_float(raw_data.get("weeklyrainin"))
    weekly_rain_mm = inch_to_mm(weekly_rain_in)
    monthly_rain_in = safe_float(raw_data.get("monthlyrainin"))
    monthly_rain_mm = inch_to_mm(monthly_rain_in)
    yearly_rain_in = safe_float(raw_data.get("yearlyrainin") if "yearlyrainin" in raw_data else raw_data.get("totalrainin"))
    yearly_rain_mm = inch_to_mm(yearly_rain_in)

    # Batteries Status (0 = OK, 1 = Low)
    wh65_batt = raw_data.get("wh65batt")
    wh57_batt = raw_data.get("wh57batt")
    soil_batt = {f"ch{i}": raw_data.get(f"wh51batt{i}") for i in range(1, 9) if f"wh51batt{i}" in raw_data}
    temp_batt = {f"ch{i}": raw_data.get(f"wh31batt{i}") or raw_data.get(f"batt{i}") for i in range(1, 9) if (f"wh31batt{i}" in raw_data or f"batt{i}" in raw_data)}
    leak_batt = {f"ch{i}": raw_data.get(f"leakbatt{i}") for i in range(1, 5) if f"leakbatt{i}" in raw_data}
    pm25_batt = {f"ch{i}": raw_data.get(f"pm25batt{i}") for i in range(1, 5) if f"pm25batt{i}" in raw_data}
    pm10_batt = {f"ch{i}": raw_data.get(f"pm10batt{i}") for i in range(1, 5) if f"pm10batt{i}" in raw_data}
    co2_batt = raw_data.get("co2_batt")
    wn34_batt = {f"ch{i}": raw_data.get(f"tf_batt{i}") for i in range(1, 9) if f"tf_batt{i}" in raw_data}

    batteries = {
        "wh65": wh65_batt,
        "wh57": wh57_batt,
        "soil": soil_batt,
        "temp_channels": temp_batt,
        "leak": leak_batt,
        "pm25": pm25_batt,
        "pm10": pm10_batt,
        "co2": co2_batt,
        "wn34": wn34_batt
    }

    # Solar & UV & VPD
    solar_radiation = safe_float(raw_data.get("solarradiation"))  # W/m^2
    uv_index = safe_int(raw_data.get("uv"))
    vpd = safe_float(raw_data.get("vpd"))
    if vpd is None and temp_c is not None and humidity is not None:
        from backend.analytics import calc_vpd
        vpd = calc_vpd(temp_c, humidity)

    # Lightning Sensor (WH57)
    lightning_count = safe_int(raw_data.get("lightning_num") if ("lightning_num" in raw_data and raw_data["lightning_num"] != "") else raw_data.get("lightning"))
    lightning_distance_km = safe_float(raw_data.get("lightning_distance"))
    lightning_time_epoch = safe_int(raw_data.get("lightning_time"))
    
    lightning_time_iso = None
    if lightning_time_epoch and lightning_time_epoch > 0:
        try:
            lightning_time_iso = datetime.fromtimestamp(lightning_time_epoch, tz=timezone.utc).isoformat()
        except Exception:
            pass

    # Soil Moisture Sensors (WH51, supports up to 8 channels)
    soil_moistures = {}
    for i in range(1, 9):
        key = f"soilmoisture{i}"
        if key in raw_data and raw_data[key] != "":
            soil_moistures[f"ch{i}"] = safe_float(raw_data[key])

    # Extra multi-channel temp/humidity (WH31, ch1..ch8)
    extra_channels = {}
    for i in range(1, 9):
        t_key = f"temp{i}f"
        h_key = f"humidity{i}"
        if t_key in raw_data:
            extra_channels[f"ch{i}"] = {
                "temp_c": f_to_c(safe_float(raw_data[t_key])),
                "humidity": safe_float(raw_data.get(h_key))
            }

    # Water / Probe Temperature Sensors (WN34, tf_ch1..tf_ch8)
    water_probes = {}
    for i in range(1, 9):
        tf_key = f"tf_ch{i}"
        if tf_key in raw_data and raw_data[tf_key] != "":
            water_probes[f"ch{i}"] = {
                "temp_c": f_to_c(safe_float(raw_data[tf_key]))
            }

    # Water Leak Detectors (WH55, leak_ch1..leak_ch4: 0 = No leak, 1 = Leak alert)
    leak_sensors = {}
    for i in range(1, 5):
        leak_key = f"leak_ch{i}"
        if leak_key in raw_data and raw_data[leak_key] != "":
            leak_sensors[f"ch{i}"] = safe_int(raw_data[leak_key])

    # Air Quality Sensors (WH41/WH43 PM2.5, WH45 PM10 & CO2)
    air_quality = {}
    # PM2.5 (ug/m3)
    pm25_data = {}
    for i in range(1, 5):
        k = f"pm25_ch{i}"
        k_24 = f"pm25_avg_24h_ch{i}"
        if k in raw_data and raw_data[k] != "":
            pm25_data[f"ch{i}"] = {
                "current": safe_float(raw_data[k]),
                "avg_24h": safe_float(raw_data.get(k_24))
            }
    if pm25_data:
        air_quality["pm25"] = pm25_data

    # PM10 (ug/m3)
    pm10_data = {}
    for i in range(1, 5):
        k = f"pm10_ch{i}"
        k_24 = f"pm10_avg_24h_ch{i}"
        if k in raw_data and raw_data[k] != "":
            pm10_data[f"ch{i}"] = {
                "current": safe_float(raw_data[k]),
                "avg_24h": safe_float(raw_data.get(k_24))
            }
    if pm10_data:
        air_quality["pm10"] = pm10_data

    # CO2 (ppm)
    if "co2" in raw_data and raw_data["co2"] != "":
        air_quality["co2"] = {
            "current_ppm": safe_int(raw_data["co2"]),
            "avg_24h_ppm": safe_int(raw_data.get("co2_24h"))
        }

    return {
        "timestamp": timestamp,
        "station_mac": raw_data.get("PASSKEY"),
        "station_model": raw_data.get("stationtype", "Ecowitt GW"),
        "temp_c": temp_c,
        "humidity": humidity,
        "temp_in_c": temp_in_c,
        "humidity_in": humidity_in,
        "pressure_rel_hpa": barom_rel_hpa,
        "pressure_abs_hpa": barom_abs_hpa,
        "wind_dir_deg": wind_dir,
        "wind_speed_kmh": wind_speed_kmh,
        "wind_gust_kmh": wind_gust_kmh,
        "max_daily_gust_kmh": max_daily_gust_kmh,
        "rain_rate_mm_hr": rain_rate_mm,
        "event_rain_mm": event_rain_mm,
        "hourly_rain_mm": hourly_rain_mm,
        "daily_rain_mm": daily_rain_mm,
        "weekly_rain_mm": weekly_rain_mm,
        "monthly_rain_mm": monthly_rain_mm,
        "yearly_rain_mm": yearly_rain_mm,
        "solar_radiation": solar_radiation,
        "uv_index": uv_index,
        "vpd": vpd,
        "lightning": {
            "count_total": lightning_count,
            "distance_km": lightning_distance_km,
            "last_strike_epoch": lightning_time_epoch,
            "last_strike_time": lightning_time_iso
        },
        "soil_moisture": soil_moistures,
        "extra_channels": extra_channels,
        "water_probes": water_probes,
        "leak_sensors": leak_sensors,
        "air_quality": air_quality,
        "batteries": batteries,
        "raw_payload": raw_data
    }
