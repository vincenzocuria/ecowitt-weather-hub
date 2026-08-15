from typing import Dict, Any, Optional
from datetime import datetime, timezone

def f_to_c(f: Optional[float]) -> Optional[float]:
    if f is None:
        return None
    return round((f - 32.0) * 5.0 / 9.0, 1)

def inhg_to_hpa(inhg: Optional[float]) -> Optional[float]:
    if inhg is None:
        return None
    return round(inhg * 33.8639, 1)

def mph_to_kmh(mph: Optional[float]) -> Optional[float]:
    if mph is None:
        return None
    return round(mph * 1.60934, 1)

def inch_to_mm(inch: Optional[float]) -> Optional[float]:
    if inch is None:
        return None
    return round(inch * 25.4, 1)

def safe_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None

def safe_int(val: Any) -> Optional[int]:
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None

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

    batteries = {
        "wh65": wh65_batt,
        "wh57": wh57_batt,
        "soil": soil_batt,
        "temp_channels": temp_batt
    }

    # Solar & UV & VPD
    solar_radiation = safe_float(raw_data.get("solarradiation"))  # W/m^2
    uv_index = safe_int(raw_data.get("uv"))
    vpd = safe_float(raw_data.get("vpd"))
    if vpd is None and temp_c is not None and humidity is not None:
        from backend.analytics import calc_vpd
        vpd = calc_vpd(temp_c, humidity)

    # Lightning Sensor (WH57)
    lightning_count = safe_int(raw_data.get("lightning_num"))
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
        "batteries": batteries,
        "raw_payload": raw_data
    }
