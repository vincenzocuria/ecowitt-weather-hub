import os
import sys
import unittest
import tempfile
from datetime import datetime, timezone

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.config import settings
from backend.ecowitt_parser import parse_ecowitt_payload, f_to_c, inch_to_mm, mph_to_kmh, inhg_to_hpa
from backend.analytics import (
    calc_zambretti_forecast, evaluate_window_ventilation, evaluate_laundry_index,
    calc_humidex, evaluate_outdoor_activity, calc_sun_ephemeris, calc_moon_phase,
    calc_vpd, calc_beaufort_scale
)
from backend.database import (
    calc_dew_point, calc_apparent_temp, deg_to_compass, save_reading,
    get_latest_reading, check_and_update_records, get_all_records, get_records_history,
    get_timeseries, search_history, get_today_extremes, get_station_status
)
from backend.forecast_service import forecast_service
from backend.alert_engine import engine


class TestEcowittHub(unittest.TestCase):

    def test_unit_conversions(self):
        self.assertEqual(f_to_c(32.0), 0.0)
        self.assertEqual(f_to_c(212.0), 100.0)
        self.assertEqual(f_to_c(68.0), 20.0)
        self.assertIsNone(f_to_c(None))

        self.assertEqual(inch_to_mm(1.0), 25.4)
        self.assertEqual(mph_to_kmh(10.0), 16.1)
        self.assertEqual(inhg_to_hpa(29.92), 1013.2)

    def test_parser_complete_payload(self):
        raw = {
            "PASSKEY": "AA:BB:CC:DD:EE:FF",
            "stationtype": "GW1100A_V2.2.3",
            "dateutc": "2026-08-15 12:00:00",
            "tempf": "77.0",       # 25.0 °C
            "humidity": "50",
            "tempinf": "71.6",     # 22.0 °C
            "humidityin": "45",
            "baromrelin": "29.92", # 1013.2 hPa
            "baromabsin": "29.62", # 1003.0 hPa
            "winddir": "180",
            "windspeedmph": "5.0", # 8.0 km/h
            "windgustmph": "12.0", # 19.3 km/h
            "maxdailygust": "15.0",# 24.1 km/h
            "rainratein": "0.1",   # 2.5 mm/h
            "eventrainin": "0.5",  # 12.7 mm
            "hourlyrainin": "0.2", # 5.1 mm
            "dailyrainin": "0.8",  # 20.3 mm
            "weeklyrainin": "1.5", # 38.1 mm
            "monthlyrainin": "2.0",# 50.8 mm
            "yearlyrainin": "15.0",# 381.0 mm
            "solarradiation": "650.0",
            "uv": "6",
            "wh65batt": "0",
            "wh57batt": "0",
            "soilmoisture1": "45",
            "wh51batt1": "0"
        }
        parsed = parse_ecowitt_payload(raw)

        self.assertEqual(parsed["temp_c"], 25.0)
        self.assertEqual(parsed["humidity"], 50.0)
        self.assertEqual(parsed["temp_in_c"], 22.0)
        self.assertEqual(parsed["pressure_rel_hpa"], 1013.2)
        self.assertEqual(parsed["rain_rate_mm_hr"], 2.5)
        self.assertEqual(parsed["hourly_rain_mm"], 5.1)
        self.assertEqual(parsed["daily_rain_mm"], 20.3)
        self.assertEqual(parsed["weekly_rain_mm"], 38.1)
        self.assertEqual(parsed["monthly_rain_mm"], 50.8)
        self.assertEqual(parsed["yearly_rain_mm"], 381.0)
        self.assertEqual(parsed["soil_moisture"].get("ch1"), 45.0)
        self.assertEqual(parsed["batteries"]["wh65"], "0")
        self.assertEqual(parsed["batteries"]["soil"]["ch1"], "0")

    def test_meteorological_calculations(self):
        # Dew point
        dp = calc_dew_point(25.0, 50.0)
        self.assertAlmostEqual(dp, 13.9, delta=0.5)

        # Apparent temp (heat index / wind chill)
        app_t = calc_apparent_temp(32.0, 70.0, 5.0)
        self.assertGreater(app_t, 32.0)  # Heat index increases perceived temp

        # Compass direction
        self.assertIn("N", deg_to_compass(0))
        self.assertIn("S", deg_to_compass(180))
        self.assertIn("W", deg_to_compass(270))
        self.assertIn("E", deg_to_compass(90))

        # VPD
        vpd = calc_vpd(25.0, 50.0)
        self.assertGreater(vpd, 0.5)

        # Beaufort scale
        b0 = calc_beaufort_scale(0.5)
        self.assertEqual(b0["grade"], 0)
        self.assertEqual(b0["label"], "Calma")

        b5 = calc_beaufort_scale(35.0)
        self.assertEqual(b5["grade"], 5)
        self.assertEqual(b5["label"], "Vento teso")

        b8 = calc_beaufort_scale(65.0)
        self.assertEqual(b8["grade"], 8)
        self.assertEqual(b8["label"], "Burrasca")

    def test_zambretti_and_comfort(self):
        # Rising pressure
        z_rise = calc_zambretti_forecast(1020.0, 1.5, 0)
        self.assertIn(z_rise["letter"], ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"])

        # Falling pressure
        z_fall = calc_zambretti_forecast(995.0, -2.5, 180)
        self.assertIn(z_fall["letter"], ["R", "S", "T", "U", "V", "W", "X", "Y", "Z"])

        # Window advice
        w_adv = evaluate_window_ventilation(temp_out=20.0, hum_out=50.0, temp_in=25.0, hum_in=50.0)
        self.assertEqual(w_adv["status"], "open_cool")

        # Laundry advice
        l_adv = evaluate_laundry_index(temp_out=28.0, hum_out=40.0, wind_speed=15.0, solar_rad=700.0)
        self.assertEqual(l_adv["status"], "excellent")

    def test_sun_and_moon_ephemeris(self):
        sun = calc_sun_ephemeris(lat=41.9028, lon=12.4964)
        self.assertIn("sunrise", sun)
        self.assertIn("sunset", sun)
        self.assertIn("daylight_duration", sun)

        moon = calc_moon_phase()
        self.assertIn("phase_name", moon)
        self.assertIn("illumination_pct", moon)

    def test_forecast_cross_check_no_hardcoded_city(self):
        summary = forecast_service.build_cross_check_summary({"temp_c": 35.0, "rain_rate_mm_hr": 0.0})
        if summary.get("available"):
            if not settings.LOCATION_NAME:
                self.assertNotIn("Corigliano", summary.get("text", ""))

    def test_aton_battery_direction(self):
        from backend.aton_service import AtonService
        svc = AtonService()
        # pBatteria > 0 means discharging (+W to house)
        parsed_discharging = svc._parse_telemetry({"pSolare": 782, "pUtenze": 888, "pBatteria": 105, "pRete": 0, "soc": 80})
        self.assertTrue(parsed_discharging["battery_discharging"])
        self.assertFalse(parsed_discharging["battery_charging"])
        self.assertEqual(parsed_discharging["battery_status"], "discharging")

        # pBatteria < 0 means charging (-W into battery)
        parsed_charging = svc._parse_telemetry({"pSolare": 1500, "pUtenze": 500, "pBatteria": -950, "pRete": 0, "soc": 40})
        self.assertTrue(parsed_charging["battery_charging"])
        self.assertFalse(parsed_charging["battery_discharging"])
        self.assertEqual(parsed_charging["battery_status"], "charging")

    def test_zambretti_steady_1013(self):
        # 1013.7 hPa with steady pressure should NOT be a thunderstorm
        z = calc_zambretti_forecast(1013.7, 0.0, 180)
        self.assertIn(z["letter"], ["K", "L", "M", "N", "O"])
        self.assertNotIn("temporali", z["text"].lower())
        self.assertNotIn("maltempo", z["text"].lower())

    def test_humidex_canadian_scale(self):
        # T=32.6, DP=16.0 -> Humidex approx 37.5 (Disagio moderato)
        h = calc_humidex(32.6, 16.0)
        self.assertEqual(h["level"], "moderate_discomfort")
        self.assertEqual(h["text"], "Disagio moderato")

        # High heat and humidex outdoor activity should be warned, not green
        outdoor = evaluate_outdoor_activity(temp_c=32.6, wind_gust_kmh=4.0, rain_rate=0.0, uv_index=7, humidex_val=h["value"])
        self.assertEqual(outdoor["level"], "warning")
        self.assertIn("Caldo", outdoor["title"])

    def test_thinq_service_state_management(self):
        from backend.thinq_service import LGThinQService
        svc = LGThinQService()
        # Mock device cache
        svc.devices_cache["test-ac-1"] = {
            "device_id": "test-ac-1",
            "alias": "Camera da letto",
            "model_name": "RAC_056905_WW",
            "device_type": "DEVICE_AIR_CONDITIONER",
            "power": "POWER_ON",
            "is_on": True,
            "current_temp": 28.5,
            "target_temp": 26.0,
            "mode": "COOL",
            "fan_speed": "LOW"
        }
        dev = svc.get_cached_device("test-ac-1")
        self.assertIsNotNone(dev)
        self.assertEqual(dev["alias"], "Camera da letto")
        self.assertTrue(dev["is_on"])
        self.assertEqual(dev["target_temp"], 26.0)

        all_devs = svc.get_cached_devices()
        self.assertEqual(len(all_devs), 1)


if __name__ == "__main__":
    unittest.main()

