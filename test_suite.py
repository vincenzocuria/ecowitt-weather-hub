import os
import sys
import unittest
import tempfile
import atexit
import shutil
from datetime import datetime, timezone

# Isolate test suite database in an isolated temporary directory to NEVER pollute production DB
_test_dir = tempfile.mkdtemp(prefix="ecowitt_test_")
os.environ["DATA_DIR"] = _test_dir
atexit.register(lambda: shutil.rmtree(_test_dir, ignore_errors=True))

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
from backend.notifier import notifier
from unittest.mock import MagicMock

# Disabilita completamente l'invio di notifiche reali su smartphone durante i test unitari
notifier.send_alert = MagicMock(return_value={"success": True})
notifier.send_push = MagicMock(return_value=True)
notifier.send_ntfy = MagicMock(return_value=True)


class TestEcowittHub(unittest.TestCase):

    @classmethod
    def tearDownClass(cls):
        import asyncio
        from backend.homeassistant_service import homeassistant_service
        from backend.thinq_service import thinq_service
        try:
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            if loop.is_running():
                asyncio.create_task(homeassistant_service.close())
                if hasattr(thinq_service, "close"):
                    asyncio.create_task(thinq_service.close())
            else:
                loop.run_until_complete(homeassistant_service.close())
                if hasattr(thinq_service, "close"):
                    loop.run_until_complete(thinq_service.close())
        except Exception:
            pass

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
        # Hermetic mock device cache
        svc.devices_cache = {
            "test-ac-1": {
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
            },
            "test-fridge-1": {
                "device_id": "test-fridge-1",
                "alias": "FRIGORIFERO",
                "model_name": "2GLRETRECF__F",
                "device_type": "DEVICE_REFRIGERATOR",
                "target_temp": 4,
                "express_mode": False,
                "door_open": False
            }
        }
        dev = svc.get_cached_device("test-ac-1")
        self.assertIsNotNone(dev)
        self.assertEqual(dev["alias"], "Camera da letto")
        self.assertTrue(dev["is_on"])
        self.assertEqual(dev["target_temp"], 26.0)

        fridge = svc.get_cached_device("test-fridge-1")
        self.assertIsNotNone(fridge)
        self.assertEqual(fridge["target_temp"], 4)
        self.assertFalse(fridge["door_open"])

        all_devs = svc.get_cached_devices()
        self.assertEqual(len(all_devs), 2)

    def test_smartthings_service_parsing_and_synergy(self):
        from backend.smartthings_service import SmartThingsService
        st = SmartThingsService()

        # Mock washer status
        dev_info = {"deviceId": "test-w1", "label": "Lavatrice Samsung AI"}
        mock_status = {
            "components": {
                "main": {
                    "switch": {"switch": {"value": "on"}},
                    "washerOperatingState": {"washerJobState": {"value": "wash"}, "machineState": {"value": "run"}},
                    "custom.washerWaterTemperature": {"washerWaterTemperature": {"value": "60"}},
                    "custom.washerSpinSpeed": {"washerSpinSpeed": {"value": "1400"}},
                    "samsungce.washerDelayEnd": {"remainingTime": {"value": 45}}
                }
            }
        }
        parsed_w = st.parse_washer_data(mock_status, dev_info)
        self.assertTrue(parsed_w["is_on"])
        self.assertTrue(parsed_w["is_running"])
        self.assertEqual(parsed_w["water_temp"], "60°C")
        self.assertEqual(parsed_w["spin_speed"], "1400 rpm")
        self.assertEqual(parsed_w["remaining_min"], 45)

        # Mock presence S26 Ultra & S25 Ultra
        p_info_s25 = {"deviceId": "test-p1", "label": "S25 Ultra di Vincenzo"}
        p_info_s26 = {"deviceId": "test-p2", "label": "S26 Ultra di Vincenzo"}
        p_status = {
            "components": {
                "main": {
                    "presenceSensor": {"presence": {"value": "present"}}
                }
            }
        }
        parsed_p = st.parse_presence_data(p_status, p_info_s26)
        self.assertTrue(parsed_p["is_present"])
        self.assertEqual(parsed_p["device_name"], "S26 Ultra")
        self.assertIn("A Casa", parsed_p["presence_label"])

        # Test Solar Synergy calculation with S26 prioritized over S25
        st.devices = [dev_info, p_info_s25, p_info_s26]
        st.device_statuses["test-w1"] = mock_status
        st.device_statuses["test-p1"] = p_status
        st.device_statuses["test-p2"] = p_status

        summary = st.get_summary(
            energy_latest={"p_solare": 2500.0, "soc": 85.0, "p_batteria": 200.0},
            drying_index={"score": 85, "status": "good", "desc": "Ottimo: sole e vento favorevoli"}
        )
        self.assertEqual(summary["presence"]["device_name"], "S26 Ultra")

        self.assertTrue(summary["solar_synergy"]["solar_optimal"])
        self.assertIn("Surplus Solare", summary["solar_synergy"]["solar_message"])
        self.assertIsNotNone(summary["laundry_drying_synergy"])
        self.assertTrue(summary["laundry_drying_synergy"]["optimal"])

    def test_smartthings_dishwasher_parsing(self):
        from backend.smartthings_service import SmartThingsService
        st = SmartThingsService()

        # 1. Caso reale Samsung: Nessun switch "on", ma machineState "run" e jobState "wash"
        dw_info = {"deviceId": "test-dw1", "label": "Lavastoviglie Samsung Series 7"}
        mock_dw_status_running = {
            "components": {
                "main": {
                    "switch": {"switch": {"value": "off"}},  # switch spento o non gestito
                    "dishwasherOperatingState": {
                        "dishwasherJobState": {"value": "wash"},
                        "machineState": {"value": "run"},
                        "remainingTime": {"value": 65}
                    },
                    "samsungce.dishwasherCycle": {
                        "dishwasherCycle": {"value": "eco"}
                    }
                }
            }
        }
        parsed = st.parse_dishwasher_data(mock_dw_status_running, dw_info)
        self.assertTrue(parsed["is_on"], "La lavastoviglie deve risultare accesa se in stato run/wash")
        self.assertTrue(parsed["is_running"], "La lavastoviglie deve risultare in esecuzione")
        self.assertEqual(parsed["job_state_label"], "Lavaggio in Corso 🍽️")
        self.assertEqual(parsed["cycle_name"], "Eco")
        self.assertEqual(parsed["remaining_min"], 65)
        self.assertIsNotNone(parsed["finish_estimate"])

        # 2. Caso con remainingTime espresso in secondi (es. 4800 s = 80 min)
        mock_dw_seconds = {
            "components": {
                "main": {
                    "dishwasherOperatingState": {
                        "dishwasherJobState": {"value": "rinse"},
                        "machineState": {"value": "run"},
                        "remainingTime": {"value": 4800}
                    },
                    "samsungce.dishwasherCycle": {
                        "dishwasherCycle": {"value": "intensive"}
                    }
                }
            }
        }
        parsed_sec = st.parse_dishwasher_data(mock_dw_seconds, dw_info)
        self.assertTrue(parsed_sec["is_running"])
        self.assertEqual(parsed_sec["job_state_label"], "Risciacquo 💧")
        self.assertEqual(parsed_sec["cycle_name"], "Intensivo / Pentole")
        self.assertEqual(parsed_sec["remaining_min"], 80)

        # 3. Caso con completionTime ISO timestamp
        from datetime import datetime, timedelta, timezone
        target_time = datetime.now(timezone.utc) + timedelta(minutes=40)
        target_iso = target_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        mock_dw_iso = {
            "components": {
                "main": {
                    "dishwasherOperatingState": {
                        "dishwasherJobState": {"value": "dry"},
                        "machineState": {"value": "run"},
                        "completionTime": {"value": target_iso}
                    },
                    "samsungce.dishwasherCycle": {
                        "dishwasherCycle": {"value": "auto"}
                    }
                }
            }
        }
        parsed_iso = st.parse_dishwasher_data(mock_dw_iso, dw_info)
        self.assertTrue(parsed_iso["is_running"])
        self.assertEqual(parsed_iso["job_state_label"], "Asciugatura Piatti ♨️")
        self.assertEqual(parsed_iso["cycle_name"], "Auto")
        self.assertAlmostEqual(parsed_iso["remaining_min"], 40, delta=1)

        # 4. Caso in standby / spenta
        mock_dw_standby = {
            "components": {
                "main": {
                    "switch": {"switch": {"value": "off"}},
                    "dishwasherOperatingState": {
                        "dishwasherJobState": {"value": "none"},
                        "machineState": {"value": "stop"}
                    }
                }
            }
        }
        parsed_standby = st.parse_dishwasher_data(mock_dw_standby, dw_info)
        self.assertFalse(parsed_standby["is_running"])
        self.assertEqual(parsed_standby["job_state_label"], "In Standby / Pronto")

        # 5. Caso con sanitize (Igienizzazione ad alta temperatura)
        mock_dw_sanitize = {
            "components": {
                "main": {
                    "dishwasherOperatingState": {
                        "dishwasherJobState": {"value": "sanitize"},
                        "machineState": {"value": "run"},
                        "remainingTime": {"value": 25}
                    },
                    "samsungce.dishwasherCycle": {
                        "dishwasherCycle": {"value": "sanitize"}
                    }
                }
            }
        }
        parsed_san = st.parse_dishwasher_data(mock_dw_sanitize, dw_info)
        self.assertTrue(parsed_san["is_running"])
        self.assertIn("Sanitize", parsed_san["job_state_label"])
        self.assertIn("Igienizzante", parsed_san["cycle_name"])

        # 5. Riconoscimento automatico in get_summary tramite capability anche con nome generico
        generic_dev = {"deviceId": "test-generic-dw", "label": "Cucina Samsung Smart"}
        st.devices = [generic_dev]
        st.device_statuses["test-generic-dw"] = mock_dw_status_running
        summary = st.get_summary()
        self.assertIsNotNone(summary["dishwasher"], "Deve identificare la lavastoviglie tramite capability dishwasherOperatingState")
        self.assertTrue(summary["dishwasher"]["is_running"])
        from backend.main import templates, app
        from fastapi.testclient import TestClient

        # Test filter formatting
        dt_str = "2026-08-15T14:32:00Z"
        formatted_short = templates.env.filters["local_dt_short"](dt_str)
        self.assertIn("15/08/2026", formatted_short)
        self.assertIn(":", formatted_short)

        formatted_date = templates.env.filters["local_date"](dt_str)
        self.assertEqual(formatted_date, "15/08/2026")

        client = TestClient(app, cookies={settings.AUTH_COOKIE_NAME: settings.AUTH_TOKEN} if settings.AUTH_TOKEN else {})
        res = client.get("/alerts-page")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Centro Notifiche", res.text)
        self.assertIn("Segna tutte come lette", res.text)

        res_rec = client.get("/records")
        self.assertEqual(res_rec.status_code, 200)
        self.assertIn("Albo dei Record", res_rec.text)

        res_idx = client.get("/")
        self.assertEqual(res_idx.status_code, 200)
        self.assertIn("dashboard-tabs-nav", res_idx.text)
        self.assertIn("pane_weather", res_idx.text)
        self.assertIn("pane_energy_home", res_idx.text)
        self.assertIn("pane_astro_comfort", res_idx.text)

        res_set = client.get("/settings")
        self.assertEqual(res_set.status_code, 200)
        self.assertIn("Impostazioni & Centro di Controllo", res_set.text)
        self.assertIn("Database SQLite", res_set.text)
        self.assertIn("Personalizzazione Nomi Sensori", res_set.text)
        self.assertIn("Notifiche Push", res_set.text)
        self.assertIn("Clima Smart", res_set.text)

    def test_sqlite_wal_mode_and_stats(self):
        from backend.database import get_connection, get_database_stats
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode;")
        row = cursor.fetchone()
        journal_mode = row[0].lower()
        self.assertEqual(journal_mode, "wal")
        conn.close()

        stats = get_database_stats()
        self.assertTrue(stats["wal_mode_enabled"])
        self.assertIn("weather_records_count", stats)
        self.assertIn("db_size_mb", stats)

    def test_extended_sensors_parser(self):
        raw = {
            "PASSKEY": "EXTENDED_TEST",
            "stationtype": "GW2000A_V3.0.0",
            "dateutc": "2026-08-15 15:00:00",
            "tempf": "86.0",
            "humidity": "40",
            "pm25_ch1": "12.5",
            "pm25_avg_24h_ch1": "10.2",
            "pm25batt1": "0",
            "pm10_ch1": "25.0",
            "pm10_avg_24h_ch1": "22.1",
            "pm10batt1": "0",
            "co2": "650",
            "co2_24h": "580",
            "co2_batt": "0",
            "leak_ch1": "0",
            "leak_ch2": "1", # Allarme perdita
            "leakbatt1": "0",
            "tf_ch1": "75.2", # WN34 sonda
            "tf_batt1": "0"
        }
        parsed = parse_ecowitt_payload(raw)
        self.assertIn("air_quality", parsed)
        self.assertEqual(parsed["air_quality"]["pm25"]["ch1"]["current"], 12.5)
        self.assertEqual(parsed["air_quality"]["pm10"]["ch1"]["current"], 25.0)
        self.assertEqual(parsed["air_quality"]["co2"]["current_ppm"], 650)
        self.assertEqual(parsed["leak_sensors"]["ch1"], 0)
        self.assertEqual(parsed["leak_sensors"]["ch2"], 1)
        self.assertAlmostEqual(parsed["water_probes"]["ch1"]["temp_c"], 24.0, delta=0.5)
        self.assertEqual(parsed["batteries"]["leak"]["ch1"], "0")
        self.assertEqual(parsed["batteries"]["wn34"]["ch1"], "0")

    def test_sensor_aliases_and_maintenance(self):
        from backend.database import save_sensor_alias, get_sensor_aliases, perform_database_maintenance, get_connection
        from datetime import timedelta

        # 1. Test Sensor Alias
        save_sensor_alias("soil_ch1", "Prato Giardino")
        save_sensor_alias("temp_ch1", "Soggiorno")
        aliases = get_sensor_aliases()
        self.assertEqual(aliases.get("soil_ch1"), "Prato Giardino")
        self.assertEqual(aliases.get("temp_ch1"), "Soggiorno")

        # 2. Test Downsampling Maintenance
        conn = get_connection()
        cursor = conn.cursor()
        old_ts_1 = "2025-01-01 10:05:00"
        old_ts_2 = "2025-01-01 10:20:00"
        old_ts_3 = "2025-01-01 10:40:00"
        for ts, t_c in [(old_ts_1, 10.0), (old_ts_2, 12.0), (old_ts_3, 14.0)]:
            cursor.execute("""
                INSERT INTO weather_records (timestamp, temp_c, humidity, pressure_rel_hpa, rain_rate_mm_hr)
                VALUES (?, ?, ?, ?, ?)
            """, (ts, t_c, 50, 1015.0, 0.0))
        conn.commit()
        conn.close()

        res = perform_database_maintenance(retention_days=60)
        self.assertEqual(res["status"], "success")

        # Check that the hour 2025-01-01 10:00:00 now has 1 consolidated record with average temp 12.0
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM weather_records WHERE timestamp = '2025-01-01 10:00:00'")
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["temp_c"], 12.0)
        conn.close()

    def test_system_api_endpoints(self):
        from backend.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app, cookies={settings.AUTH_COOKIE_NAME: settings.AUTH_TOKEN} if settings.AUTH_TOKEN else {})

        # DB Stats
        stats_resp = client.get("/api/system/db-stats")
        self.assertEqual(stats_resp.status_code, 200)
        data = stats_resp.json()
        self.assertTrue(data["wal_mode_enabled"])

        # Backup DB
        backup_resp = client.get("/api/system/backup")
        self.assertEqual(backup_resp.status_code, 200)
        self.assertGreater(len(backup_resp.content), 100)

        # Aliases API
        alias_resp = client.post("/api/sensors/aliases", json={"sensor_id": "soil_ch2", "alias": "Piante Balcone"})
        self.assertEqual(alias_resp.status_code, 200)
        get_al = client.get("/api/sensors/aliases")
        self.assertEqual(get_al.status_code, 200)
        self.assertEqual(get_al.json()["aliases"].get("soil_ch2"), "Piante Balcone")

    def test_rain_start_and_forecast_alerts(self):
        from backend.alert_engine import AlertEngine
        import time

        test_engine = AlertEngine()
        sent_alerts = []

        # Monkeypatch notifier for testing
        def mock_send(alert_type, title, message, priority="normal", extra_data=None):
            sent_alerts.append({"type": alert_type, "title": title, "msg": message, "prio": priority})

        from backend import alert_engine
        original_send = alert_engine.notifier.send_alert
        alert_engine.notifier.send_alert = mock_send

        try:
            now = time.time()
            test_engine.is_raining = False
            test_engine.last_rain_start_alert = 0.0
            test_engine.last_rain_alert = 0.0
            test_engine.last_rain_burst_alert = 0.0

            # 1. First rain reading (rain start)
            self.assertFalse(test_engine.is_raining)
            test_engine._check_rain({"rain_rate_mm_hr": 0.8, "event_rain_mm": 0.2}, now)
            self.assertTrue(test_engine.is_raining)
            self.assertEqual(len(sent_alerts), 1)
            self.assertEqual(sent_alerts[0]["type"], "rain_start")
            self.assertIn("Ha Iniziato a Piovere", sent_alerts[0]["title"])

            # 2. Second rain reading during the same rain event (should not re-trigger rain_start)
            sent_alerts.clear()
            test_engine._check_rain({"rain_rate_mm_hr": 1.2, "event_rain_mm": 0.4}, now + 10)
            self.assertEqual(len(sent_alerts), 0)

            # 3. Heavy rain (rain rate >= 5.0 mm/h) triggers rain_heavy alert
            test_engine._check_rain({"rain_rate_mm_hr": 8.5, "event_rain_mm": 2.0}, now + 20)
            self.assertEqual(len(sent_alerts), 1)
            self.assertEqual(sent_alerts[0]["type"], "rain")
            self.assertIn("Pioggia Intensa", sent_alerts[0]["title"])

            # 4. Rain stops (after 900+ seconds of 0 rain, is_raining resets)
            test_engine._check_rain({"rain_rate_mm_hr": 0.0, "event_rain_mm": 0.0}, now + 1000)
            self.assertFalse(test_engine.is_raining)
        finally:
            alert_engine.notifier.send_alert = original_send

    def test_elevation_and_pressure_conversion(self):
        from backend.analytics import abs_to_rel_pressure, calc_zambretti_forecast
        from backend.config import settings

        self.assertEqual(settings.ELEVATION, 68.0)
        self.assertEqual(settings.LOCATION_NAME, "Corigliano-Rossano")

        # Test absolute to relative pressure conversion at 68m
        # At 1008.0 hPa abs and 68m, rel should be approx 1016.1 hPa (+8.1 hPa)
        p_rel = abs_to_rel_pressure(1008.0, elevation_m=68.0, temp_c=20.0)
        self.assertAlmostEqual(p_rel, 1016.1, delta=0.2)

        # Test Zambretti with calculated MSLP
        z_res = calc_zambretti_forecast(p_rel, pressure_diff_3h=-1.2, wind_deg=180)
        self.assertIn("letter", z_res)
        self.assertIn("text", z_res)

    def test_tuya_service_and_db_config(self):
        from backend.tuya_service import tuya_service
        from backend.database import get_tuya_device_configs, save_tuya_device_config

        # Test DB save and retrieve
        test_dev_id = "test_plug_123"
        save_tuya_device_config(test_dev_id, enabled=True, custom_name="Test Presa Forno", category="cz", icon="🔌")
        configs = get_tuya_device_configs()
        self.assertIn(test_dev_id, configs)
        self.assertTrue(configs[test_dev_id]["enabled"])
        self.assertEqual(configs[test_dev_id]["custom_name"], "Test Presa Forno")

        # Test toggle to disabled
        save_tuya_device_config(test_dev_id, enabled=False)
        configs = get_tuya_device_configs()
        self.assertFalse(configs[test_dev_id]["enabled"])

        # Test status formatting
        mock_dev_info = {
            "id": test_dev_id,
            "name": "Smart Socket Raw",
            "category": "cz",
            "product_name": "smart plug"
        }
        mock_raw_status = [
            {"code": "switch_1", "value": True},
            {"code": "cur_power", "value": 1500}, # 150.0 W
            {"code": "cur_voltage", "value": 2305}, # 230.5 V
            {"code": "cur_current", "value": 650} # 0.65 A
        ]
        formatted = tuya_service._format_device_status(mock_dev_info, mock_raw_status, configs[test_dev_id])
        self.assertEqual(formatted["name"], "Test Presa Forno")
        self.assertFalse(formatted["enabled"])
        self.assertTrue(formatted["is_on"])
        self.assertEqual(formatted["power_w"], 150.0)
        self.assertEqual(formatted["voltage_v"], 230.5)
        self.assertEqual(formatted["current_a"], 0.65)

    def test_alert_badges_and_read_status(self):
        from backend.database import log_alert_db, get_unread_alerts_count, mark_all_alerts_as_read, get_alert_logs, mark_alert_as_read
        from fastapi.testclient import TestClient
        from backend.main import app

        # Inserisci notifiche di test
        log_alert_db("lightning", "Fulmine Vicino", "Fulmine a 5km", {"distance_km": "5"})
        log_alert_db("freeze", "Allerta Gelo", "Temperatura a 0°C", {"temp_c": "0"})
        
        unread = get_unread_alerts_count()
        self.assertGreaterEqual(unread, 2)

        client = TestClient(app, cookies={settings.AUTH_COOKIE_NAME: settings.AUTH_TOKEN} if settings.AUTH_TOKEN else {})
        res = client.get("/api/alerts/unread-count")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["unread_count"], unread)

        # Segna tutte come lette
        res_mark = client.post("/api/alerts/mark-all-read")
        self.assertEqual(res_mark.status_code, 200)
        self.assertEqual(res_mark.json()["unread_count"], 0)
        self.assertEqual(get_unread_alerts_count(), 0)

        # Verifica conteggio a zero
        res_zero = client.get("/api/alerts/unread-count")
        self.assertEqual(res_zero.json()["unread_count"], 0)

    def test_history_kpis_and_page(self):
        from backend.database import get_history_kpis, get_connection
        from fastapi.testclient import TestClient
        from backend.main import app

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO weather_records (timestamp, temp_c, humidity, temp_in_c, humidity_in, pressure_rel_hpa, wind_speed_kmh, wind_gust_kmh, daily_rain_mm, rain_rate_mm_hr, solar_radiation, uv_index)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ("2026-08-18 10:00:00", 28.5, 55, 23.0, 50, 1014.2, 12.0, 22.5, 4.2, 1.5, 750, 7))
        conn.commit()
        conn.close()

        kpis = get_history_kpis()
        self.assertGreaterEqual(kpis["total_records"], 1)
        self.assertIsNotNone(kpis["max_temp"])
        self.assertIsNotNone(kpis["max_gust"])
        self.assertGreaterEqual(kpis["total_rain"], 4.2)

        client = TestClient(app, cookies={settings.AUTH_COOKIE_NAME: settings.AUTH_TOKEN} if settings.AUTH_TOKEN else {})
        res = client.get("/history")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Riepilogo Parametri del Periodo", res.text)
        self.assertIn("history-record-card", res.text)
        self.assertIn("Esporta CSV", res.text)

        # Test API search kpis
        api_res = client.get("/api/search/kpis")
        self.assertEqual(api_res.status_code, 200)
        self.assertIn("max_temp", api_res.json())

    def test_devices_page_and_apis(self):
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app, cookies={settings.AUTH_COOKIE_NAME: settings.AUTH_TOKEN} if settings.AUTH_TOKEN else {})
        res = client.get("/devices")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Dispositivi Smart", res.text)
        self.assertIn("devices-header-card", res.text)
        self.assertIn("devices-grid", res.text)

        # Test devices all API
        api_res = client.get("/api/devices/all")
        self.assertEqual(api_res.status_code, 200)
        self.assertIn("devices", api_res.json())
        self.assertIn("stats", api_res.json())

    def test_house_breakdown_api(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        from backend.aton_service import aton_service

        # Imposta dati energetici mock per Aton
        aton_service.latest_data = {
            "p_utenze": 650.0,
            "p_solare": 1200.0,
            "p_batteria": -550.0,
            "p_rete": 0.0,
            "soc": 85.0
        }

        client = TestClient(app, cookies={settings.AUTH_COOKIE_NAME: settings.AUTH_TOKEN} if settings.AUTH_TOKEN else {})
        res = client.get("/api/energy/house-breakdown")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("total_house_w", data)
        self.assertEqual(data["total_house_w"], 650.0)
        self.assertIn("monitored_power_w", data)
        self.assertIn("unmonitored_power_w", data)
        self.assertIn("monitored_pct", data)
        self.assertIn("unmonitored_pct", data)
        self.assertIn("active_consumers", data)
        self.assertIn("standby_devices", data)
        self.assertIsInstance(data["active_consumers"], list)
        self.assertIsInstance(data["standby_devices"], list)

        # Verifica che nessuna entità non elettrica (presenza, salute, bilancia) sia nei consumatori attivi
        for c in data["active_consumers"]:
            self.assertNotIn(c.get("type"), ("presence", "health", "scale", "sensor"))
            if c.get("power_w", 0) <= 0:
                self.assertIn(c.get("type"), ("climate", "thermostat", "appliance"))

    def test_homeassistant_service_parsing(self):
        from backend.homeassistant_service import HomeAssistantService
        ha = HomeAssistantService()
        ha.entities = {
            "sensor.lavanderia_lavatrice_machine_state": {"state": "run", "attributes": {"friendly_name": "Lavatrice Machine State"}},
            "sensor.lavanderia_lavatrice_job_state": {"state": "wash", "attributes": {"friendly_name": "Lavatrice Job State"}},
            "sensor.lavanderia_lavatrice_completion_time": {"state": "2026-08-24T08:30:00+00:00", "attributes": {}},
            "select.lavanderia_lavatrice_temperatura_dell_acqua": {"state": "40 °C", "attributes": {}},
            "select.lavanderia_lavatrice_spin_level": {"state": "1200 rpm", "attributes": {}},
            "sensor.cucina_lavastoviglie_machine_state": {"state": "run", "attributes": {"friendly_name": "Lavastoviglie Machine State"}},
            "sensor.cucina_lavastoviglie_job_state": {"state": "rinse", "attributes": {"friendly_name": "Lavastoviglie Job State"}},
            "sensor.cucina_lavastoviglie_completion_time": {"state": "2026-08-24T07:45:00+00:00", "attributes": {}},
            "person.vincenzo_curia": {"state": "home", "attributes": {"friendly_name": "Vincenzo Curia", "latitude": 39.62, "longitude": 16.50}},
            "sensor.galaxy_s26_ultra_battery_level": {"state": "88", "attributes": {"unit_of_measurement": "%"}},
            "valve.aiuola_valve": {"state": "closed", "attributes": {"friendly_name": "Aiuola Valvola"}},
            "switch.cisterna_presa": {"state": "on", "attributes": {"friendly_name": "Presa Cisterna"}},
            "sensor.cisterna_presa_power": {"state": "120.5", "attributes": {"unit_of_measurement": "W"}}
        }

        w = ha.parse_washer_data()
        self.assertTrue(w["is_on"])
        self.assertTrue(w["is_running"])
        self.assertEqual(w["water_temp"], "40 °C")
        self.assertEqual(w["spin_speed"], "1200 rpm")

        dw = ha.parse_dishwasher_data()
        self.assertTrue(dw["is_on"])
        self.assertTrue(dw["is_running"])

        p = ha.parse_presence_data()
        self.assertTrue(p["is_present"])
        self.assertEqual(p["battery_percent"], 88)

        summary = ha.get_summary(
            energy_latest={"p_solare": 3000.0, "soc": 90.0, "p_batteria": 100.0},
            drying_index={"score": 90, "status": "excellent", "desc": "Condizioni ideali"}
        )
        self.assertTrue(summary["solar_synergy"]["solar_optimal"])
        self.assertTrue(summary["presence"]["is_present"])
        self.assertEqual(summary["presence"]["battery_percent"], 88)

        catalog = ha.get_catalog_devices()
        self.assertGreater(len(catalog), 0)
        cat_ids = [d["id"] for d in catalog]
        self.assertIn("hass_washer", cat_ids)
        self.assertIn("hass_dishwasher", cat_ids)
        self.assertIn("hass_presence", cat_ids)
        self.assertIn("hass_valve.aiuola_valve", cat_ids)

        valve_dev = next(d for d in catalog if d["id"] == "hass_valve.aiuola_valve")
        self.assertEqual(valve_dev["category"], "irrigation")
        self.assertEqual(valve_dev["icon"], "💧")

        # Verifica che il parser di irrigazione NON generi valvole fittizie se vuoto
        empty_irr = ha.parse_irrigation_data()
        self.assertEqual(len(empty_irr["valves"]), 1) # solo la reale valve.aiuola_valve
        self.assertEqual(empty_irr["valves"][0]["id"], "valve.aiuola_valve")

    def test_homeassistant_shutters_and_irrigation_categorization(self):
        from backend.homeassistant import CatalogHelper, parse_irrigation_data
        
        entities = {
            "cover.persiana_camera": {"state": "open", "attributes": {"friendly_name": "Persiana Camera"}},
            "switch.tenda_balcone": {"state": "off", "attributes": {"friendly_name": "Tenda Balcone", "device_class": "curtain"}},
            "switch.valvola_irrigazione_orto": {"state": "off", "attributes": {"friendly_name": "Valvola Irrigazione Orto"}},
            "switch.presa_tv": {"state": "on", "attributes": {"friendly_name": "Presa TV"}}
        }

        devices = CatalogHelper.get_catalog_devices(entities)
        dev_by_id = {d["raw_id"]: d for d in devices}

        self.assertEqual(dev_by_id["cover.persiana_camera"]["category"], "shutters")
        self.assertEqual(dev_by_id["cover.persiana_camera"]["icon"], "🪟")
        self.assertEqual(dev_by_id["switch.tenda_balcone"]["category"], "shutters")
        self.assertEqual(dev_by_id["switch.valvola_irrigazione_orto"]["category"], "irrigation")
        self.assertEqual(dev_by_id["switch.valvola_irrigazione_orto"]["icon"], "💧")
        self.assertEqual(dev_by_id["switch.presa_tv"]["category"], "plugs")

        # Verifica che senza entità di irrigazione restituisca 0 valvole (nessun mock)
        no_valves_irr = parse_irrigation_data({"switch.presa_tv": {"state": "on"}})
        self.assertEqual(len(no_valves_irr["valves"]), 0)
        self.assertFalse(no_valves_irr["is_open"])

    def test_homeassistant_modular_package(self):
        from backend.homeassistant import (
            HomeAssistantClient, CatalogHelper, DeviceController, SynergiesHelper,
            parse_washer_data, parse_dishwasher_data, parse_presence_data,
            parse_climate_data, parse_irrigation_data, parse_energy_data
        )

        # 1. Test Client defaults
        client = HomeAssistantClient()
        self.assertEqual(len(client.entities), 0)

        # 2. Test Climate Parser
        mock_entities = {
            "climate.termostato_salotto": {
                "state": "heat",
                "attributes": {
                    "friendly_name": "Termostato Salotto",
                    "current_temperature": 20.5,
                    "temperature": 22.0,
                    "hvac_modes": ["off", "heat", "auto"]
                }
            },
            "sensor.pv_power": {"state": "2400.0"},
            "sensor.battery_soc": {"state": "75.0"},
            "sensor.battery_power": {"state": "-800.0"},
            "sensor.house_power": {"state": "1600.0"},
            "switch.scaldabagno": {"state": "on", "attributes": {"friendly_name": "Scaldabagno"}},
            "sensor.scaldabagno_potenza": {"state": "1200.0"}
        }

        climates = parse_climate_data(mock_entities)
        self.assertEqual(len(climates), 1)
        self.assertEqual(climates[0]["name"], "Termostato Salotto")
        self.assertEqual(climates[0]["current_temp"], 20.5)
        self.assertEqual(climates[0]["target_temp"], 22.0)
        self.assertTrue(climates[0]["is_on"])

        # 3. Test Energy Parser from HA entities
        energy = parse_energy_data(mock_entities)
        self.assertIsNotNone(energy)
        self.assertEqual(energy["p_solare"], 2400.0)
        self.assertEqual(energy["soc"], 75.0)
        self.assertEqual(energy["p_batteria"], -800.0)
        self.assertEqual(energy["p_utenze"], 1600.0)

        # 4. Test CatalogHelper Power Map
        power_map = CatalogHelper.build_power_map(mock_entities)
        self.assertEqual(power_map.get("scaldabagno"), 1200.0)

        # 5. Test DeviceController ID resolution
        controller = DeviceController(client)
        self.assertEqual(controller.resolve_entity_id("04564850cc50e3d1ca35"), "switch.cisterna_presa")
        self.assertEqual(controller.resolve_entity_id("luce_corridoio"), "switch.luce_corridoio")
        self.assertEqual(controller.resolve_entity_id("light.luce_cucina"), "light.luce_cucina")

        # 6. Test SynergiesHelper
        sol_syn = SynergiesHelper.calculate_solar_synergy(p_solare=2000.0, soc=80.0)
        self.assertTrue(sol_syn["solar_optimal"])
        self.assertEqual(sol_syn["solar_badge_class"], "badge-success")

        dry_syn = SynergiesHelper.calculate_drying_synergy(
            washer_data={"is_running": True},
            drying_index={"score": 75, "desc": "Ottimo"}
        )
        self.assertIsNotNone(dry_syn)
        self.assertTrue(dry_syn["optimal"])


    def test_devices_deduplication(self):
        from backend.routers.devices import build_devices_catalog
        from backend.homeassistant_service import homeassistant_service

        homeassistant_service.entities = {
            "valve.aiuola_valve": {
                "entity_id": "valve.aiuola_valve",
                "state": "closed",
                "attributes": {"friendly_name": "Valvola Orto HA"}
            }
        }

        catalog = build_devices_catalog()
        valve_devices = [d for d in catalog["devices"] if "valve.aiuola_valve" in d.get("raw_id", "") or "valve.aiuola_valve" in d.get("id", "")]
        self.assertEqual(len(valve_devices), 1, "La valvola presente su HA deve essere inclusa nel catalogo")

    def test_fujitsu_climate_cucina_integration(self):
        from backend.homeassistant import parse_climate_data, CatalogHelper
        from backend.routers.devices import build_devices_catalog
        from backend.homeassistant_service import homeassistant_service

        homeassistant_service.entities = {
            "climate.cucina": {
                "entity_id": "climate.cucina",
                "state": "cool",
                "attributes": {
                    "friendly_name": "Cucina",
                    "current_temperature": 28.5,
                    "temperature": 26.0,
                    "hvac_modes": ["off", "cool", "heat", "auto", "dry"],
                    "fan_modes": ["auto", "low", "medium", "high", "diffuse"],
                    "fan_mode": "medium",
                    "swing_modes": ["vertical", "horizontal", "both"],
                    "swing_mode": "vertical"
                }
            },
            "sensor.climatizzatore_potenza": {"state": "450.0"},
            "sensor.climatizzatore_energia_totale": {"state": "128.5"},
            "sensor.climatizzatore_tensione": {"state": "230.2"},
            "sensor.climatizzatore_corrente": {"state": "2.1"}
        }

        climates = parse_climate_data(homeassistant_service.entities)
        self.assertEqual(len(climates), 1)
        cucina = climates[0]
        self.assertEqual(cucina["name"], "Cucina")
        self.assertEqual(cucina["brand"], "Fujitsu")
        self.assertEqual(cucina["model_name"], "Fujitsu General FGLair (AC-UTY)")
        self.assertEqual(cucina["current_temp"], 28.5)
        self.assertEqual(cucina["target_temp"], 26.0)
        self.assertEqual(cucina["power_w"], 450.0)
        self.assertEqual(cucina["voltage_v"], 230.2)
        self.assertEqual(cucina["energy_total_kwh"], 128.5)
        self.assertTrue(cucina["is_on"])
        self.assertTrue(cucina["rotate_up_down"])

        catalog = build_devices_catalog()
        cucina_dev = next((d for d in catalog["devices"] if "climate.cucina" in d.get("raw_id", "")), None)
        self.assertIsNotNone(cucina_dev)
        self.assertEqual(cucina_dev["category"], "climate")
        self.assertEqual(cucina_dev["category_label"], "Climatizzatore Fujitsu FGLair • HA")
        self.assertEqual(cucina_dev["power_w"], 450.0)


    def test_tropical_nights_and_soil_moisture(self):
        from backend.database import (
            get_tropical_nights_stats, get_soil_moisture_summary,
            check_and_update_records, get_all_records, get_timeseries, get_history_kpis, save_reading
        )
        from fastapi.testclient import TestClient
        from backend.main import app

        # 1. Inserisci letture con notti tropicali e sensori suolo
        save_reading({
            "timestamp": "2026-07-15T04:00:00",
            "temp_c": 22.5,
            "soil_moisture": {"ch1": 42.0}
        })
        save_reading({
            "timestamp": "2026-07-16T04:00:00",
            "temp_c": 26.2, # Notte Rovente >= 25°C
            "soil_moisture": {"ch1": 40.0}
        })
        save_reading({
            "timestamp": "2026-07-17T04:00:00",
            "temp_c": 23.0,
            "soil_moisture": {"ch1": 55.0}
        })

        # 2. Test calcolo statistiche Notti Tropicali
        trop_stats = get_tropical_nights_stats(year=2026)
        self.assertEqual(trop_stats["year"], 2026)
        self.assertGreaterEqual(trop_stats["total_tropical_nights"], 3)
        self.assertGreaterEqual(trop_stats["total_super_tropical_nights"], 1)
        self.assertGreaterEqual(trop_stats["highest_min_temp"], 22.5)
        self.assertGreaterEqual(trop_stats["max_streak"], 1)
        self.assertIn("monthly_stats", trop_stats)

        # 3. Test record temp_min_highest
        new_recs = check_and_update_records({
            "temp_min_highest": 26.2,
            "temp_min_highest_date": "2026-07-16",
            "timestamp": "2026-07-16T08:00:00"
        })
        all_records = get_all_records()
        rec_keys = [r["record_key"] for r in all_records]
        self.assertIn("temp_min_highest", rec_keys)

        # 4. Test stato e trend umidità terreno
        soil_summary = get_soil_moisture_summary()
        self.assertTrue(soil_summary["has_sensors"])
        self.assertIn("ch1", soil_summary["channels"])
        self.assertIn("status_label", soil_summary["channels"]["ch1"])
        self.assertIn("trend_icon", soil_summary["channels"]["ch1"])

        # 5. Test timeseries soil moisture
        ts = get_timeseries("24h")
        self.assertIn("soil_moisture", ts)

        # 6. Test KPI archivio con tropical_nights
        kpis = get_history_kpis("2026-07-01", "2026-07-31")
        self.assertIn("tropical_nights", kpis)
        self.assertIn("very_hot_nights", kpis)
        self.assertGreaterEqual(kpis["tropical_nights"], 3)
        self.assertGreaterEqual(kpis["very_hot_nights"], 1)

        # 7. Test API endpoints
        client = TestClient(app, cookies={settings.AUTH_COOKIE_NAME: settings.AUTH_TOKEN} if settings.AUTH_TOKEN else {})
        r_trop = client.get("/api/climate/tropical-nights?year=2026")
        self.assertEqual(r_trop.status_code, 200)
        self.assertIn("total_tropical_nights", r_trop.json())

        r_soil = client.get("/api/soil/summary")
        self.assertEqual(r_soil.status_code, 200)
        self.assertIn("has_sensors", r_soil.json())

        r_page = client.get("/records")
        self.assertEqual(r_page.status_code, 200)
        self.assertIn("Climatologia Notti Tropicali", r_page.text)
        self.assertIn("Minima Più Alta", r_page.text)

        r_charts = client.get("/charts")
        self.assertEqual(r_charts.status_code, 200)
        self.assertIn("chartSoil", r_charts.text)

        r_radar = client.get("/radar")
        self.assertEqual(r_radar.status_code, 200)
        self.assertIn("radar-map", r_radar.text)
        self.assertIn("STATION_LAT", r_radar.text)
        self.assertIn("RainViewer", r_radar.text)

        r_kiosk = client.get("/kiosk")
        self.assertEqual(r_kiosk.status_code, 200)
        self.assertIn("kiosk-container", r_kiosk.text)
        self.assertIn("kiosk-clock", r_kiosk.text)

        r_home = client.get("/")
        self.assertEqual(r_home.status_code, 200)
        self.assertIn("hero_tropical_pill", r_home.text)

        # 8. Test alert engine soil dry & soil wet
        from backend import alert_engine
        from backend.alert_engine import AlertEngine
        test_engine = AlertEngine()
        test_engine.last_soil_alert = {}
        test_engine.last_soil_wet_alert = {}

        original_send = alert_engine.notifier.send_alert
        mock_soil_alerts = []
        alert_engine.notifier.send_alert = lambda *args, **kwargs: mock_soil_alerts.append((args, kwargs))

        try:
            # Terreno troppo umido / saturo
            test_engine._check_soil_moisture({
                "soil_moisture": {"ch1": 85.0},
                "rain_rate_mm_hr": 0.0,
                "daily_rain_mm": 0.0
            }, now=100000.0)
            self.assertIn("ch1", test_engine.last_soil_wet_alert)

            # Terreno secco
            test_engine._check_soil_moisture({
                "soil_moisture": {"ch2": 12.0},
                "rain_rate_mm_hr": 0.0,
                "daily_rain_mm": 0.0
            }, now=100000.0)
            self.assertIn("ch2", test_engine.last_soil_alert)
        finally:
            alert_engine.notifier.send_alert = original_send

    def test_api_live_security_and_sanitization(self):
        """Verifica che /api/live non esponga MAI credenziali, PASSKEY, MAC o dati raw."""
        from fastapi.testclient import TestClient
        from backend.main import app

        save_reading({
            "PASSKEY": "SECRET_MAC_KEY_12345",
            "stationtype": "GW1100_TEST",
            "raw_data_json": '{"PASSKEY": "SECRET_MAC_KEY_12345"}',
            "raw_payload": "PASSKEY=SECRET_MAC_KEY_12345",
            "station_mac": "AA:BB:CC:DD:EE:FF",
            "temp_c": 24.5,
            "humidity": 55.0,
            "pressure_rel_hpa": 1014.2,
            "wind_speed_kmh": 6.2,
            "rain_rate_mm_hr": 0.0
        })

        client = TestClient(app, cookies={settings.AUTH_COOKIE_NAME: settings.AUTH_TOKEN} if settings.AUTH_TOKEN else {})
        res = client.get("/api/live")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        # Sicurezza
        self.assertNotIn("PASSKEY", data)
        self.assertNotIn("raw_data_json", data)
        self.assertNotIn("raw_payload", data)
        self.assertNotIn("station_mac", data)
        self.assertNotIn("stationtype", data)
        self.assertEqual(data.get("temp_c"), 24.5)
        self.assertIn("analytics", data)
        self.assertIn("now_highlights", data["analytics"])
        self.assertIn("air_quality", data["analytics"])
        self.assertIn("solar_forecast", data["analytics"])
        self.assertIn("rain_nowcast", data["analytics"])

    def test_air_quality_and_pollens_engine(self):
        """Testa il motore di analisi qualità dell'aria EAQI e pollini CAMS."""
        from backend.forecast_service import forecast_service
        from backend.analytics import evaluate_window_ventilation

        mock_raw = {
            "current": {
                "european_aqi": 2,
                "pm2_5": 14.5,
                "pm10": 22.0,
                "nitrogen_dioxide": 18.0,
                "ozone": 55.0,
                "grass_pollen": 45.0,
                "olive_pollen": 12.0
            }
        }
        res = forecast_service._process_air_quality_payload(mock_raw)
        self.assertEqual(res["eaqi"]["value"], 2)
        self.assertEqual(res["eaqi"]["label"], "Buona")
        self.assertEqual(res["pollutants"]["pm2_5"]["val"], 14.5)
        self.assertIn("grass", res["pollens"])
        self.assertEqual(res["pollens"]["grass"]["level"], "Alto")

        # Test cross-check finestre con AQI degradato
        bad_aqi = {
            "eaqi": {"value": 4, "label": "Scadente"},
            "pollutants": {"pm2_5": {"val": 38.0}},
            "dominant_pollen": {"severity_score": 1, "name": "Nessuno"}
        }
        win_advice = evaluate_window_ventilation(
            temp_out=21.0,
            hum_out=50.0,
            temp_in=25.0,
            hum_in=50.0,
            rain_rate=0.0,
            air_quality=bad_aqi
        )
        self.assertEqual(win_advice["status"], "close_aqi")
        self.assertIn("PM2.5", win_advice["desc"])

    def test_evapotranspiration_and_smart_irrigation(self):
        """Testa il calcolo di ET₀ e il consigliere d'irrigazione intelligente WH51."""
        from backend.analytics import calc_evapotranspiration, evaluate_smart_irrigation

        et0 = calc_evapotranspiration(temp_c=28.0, humidity=40.0, solar_rad=600.0, wind_kmh=12.0)
        self.assertGreaterEqual(et0, 2.5)
        self.assertLessEqual(et0, 8.5)

        # 1. Pioggia prevista nelle 24h -> Non irrigare
        adv_rain = evaluate_smart_irrigation(
            soil_moisture_pct=22.0,
            temp_c=28.0,
            solar_rad=600.0,
            rain_forecast_24h_mm=6.5,
            recent_rain_48h_mm=0.0,
            et_mm=et0
        )
        self.assertEqual(adv_rain["status"], "skip_rain")
        self.assertEqual(adv_rain["liters_sqm_rec"], 0.0)

        # 2. Terreno secco e nessuna pioggia -> Consiglia irrigazione
        adv_water = evaluate_smart_irrigation(
            soil_moisture_pct=20.0,
            temp_c=30.0,
            solar_rad=700.0,
            rain_forecast_24h_mm=0.0,
            recent_rain_48h_mm=0.0,
            et_mm=et0
        )
        self.assertEqual(adv_water["status"], "water_needed")
        self.assertGreater(adv_water["liters_sqm_rec"], 1.5)

    def test_solar_forecast_and_battery_predictor(self):
        """Testa la stima di produzione fotovoltaico e finestra elettrodomestici."""
        from backend.forecast_service import forecast_service

        res = forecast_service.fetch_solar_forecast(aton_data={"soc": 45, "p_solare": 1500, "p_utenze": 600})
        self.assertGreater(res["tomorrow_est_kwh"], 5.0)
        self.assertIn("11:00", res["best_appliances_window"])
        self.assertIsNotNone(res["battery_100_est"])

    def test_record_delta_threshold_and_cooldown(self):
        """Testa che piccole variazioni e temperature notturne in calo non generino spam di record."""
        from backend.database import check_and_update_records, get_all_records, get_connection
        from backend.alert_engine import AlertEngine

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM weather_extremes WHERE record_key = 'temp_max'")
        cursor.execute("DELETE FROM records_history WHERE record_key = 'temp_max'")
        conn.commit()
        conn.close()

        # Imposta record base
        check_and_update_records("temp_max", 38.0, "2026-08-10 14:00:00")
        
        # Incremento sotto soglia (0.05°C < 0.2°C) -> non deve aggiornare
        upd_small = check_and_update_records("temp_max", 38.05, "2026-08-10 14:05:00")
        self.assertFalse(upd_small["is_new"])

        # Incremento significativo (38.5°C >= 38.2°C) -> deve aggiornare
        upd_big = check_and_update_records("temp_max", 38.5, "2026-08-10 14:30:00")
        self.assertTrue(upd_big["is_new"])

        # Test cooldown per-key su AlertEngine
        ae = AlertEngine()
        ae.last_record_alert_by_key = {}
        now_ts = 1000000.0
        
        # Primo alert su temp_min -> consentito
        can_send_1 = ae._should_send_record_alert("temp_min", now_ts)
        self.assertTrue(can_send_1)
        
        # Secondo alert su temp_min 5 minuti dopo -> bloccato da cooldown
        can_send_2 = ae._should_send_record_alert("temp_min", now_ts + 300.0)
        self.assertFalse(can_send_2)
        
        # Alert su temp_max -> consentito (chiave diversa)
        can_send_3 = ae._should_send_record_alert("temp_max", now_ts + 300.0)
        self.assertTrue(can_send_3)

    def test_climate_automations_config(self):
        from backend.database import get_climate_automations_config, save_climate_automations_config
        cfg = get_climate_automations_config()
        self.assertIn("master_enabled", cfg)
        self.assertIn("away_action", cfg)
        self.assertIn("comfort_guard_action", cfg)
        self.assertIn("comfort_max_temp", cfg)

        saved = save_climate_automations_config({
            "away_action": "notify",
            "max_runtime_hours": 6,
            "comfort_guard_action": "on",
            "comfort_max_temp": 26.0,
            "comfort_min_rest_min": 25
        })
        self.assertEqual(saved["max_runtime_hours"], 6)
        self.assertEqual(saved["comfort_guard_action"], "on")
        self.assertEqual(saved["comfort_max_temp"], 26.0)
        self.assertEqual(saved["comfort_min_rest_min"], 25)

        from fastapi.testclient import TestClient
        from backend.main import app
        from backend.config import settings
        client = TestClient(app, cookies={settings.AUTH_COOKIE_NAME: settings.AUTH_TOKEN})
        resp = client.get("/api/climate/automations/config")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("config", resp.json())
        self.assertEqual(resp.json()["config"]["comfort_max_temp"], 26.0)

        # Test trigger test-action comfort
        resp_test = client.post("/api/climate/automations/test-action", json={"scenario": "comfort"})
        self.assertEqual(resp_test.status_code, 200)
        self.assertEqual(resp_test.json()["status"], "sent")

    def test_civil_protection_service(self):
        from backend.civil_protection_service import (
            civil_protection_service, _parse_alert_level, _point_in_polygon, ALERT_SEVERITY
        )
        
        # Test helper livello di allerta
        self.assertEqual(_parse_alert_level("Assenza di fenomeni"), "VERDE")
        self.assertEqual(_parse_alert_level("ORDINARIA CRITICITA' PER RISCHIO TEMPORALI / ALLERTA GIALLA"), "GIALLA")
        self.assertEqual(_parse_alert_level("MODERATA CRITICITA' / ALLERTA ARANCIONE"), "ARANCIONE")
        self.assertEqual(_parse_alert_level("ELEVATA CRITICITA' / ALLERTA ROSSA"), "ROSSA")

        # Test point in polygon
        poly = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]
        self.assertTrue(_point_in_polygon(5.0, 5.0, poly))
        self.assertFalse(_point_in_polygon(15.0, 5.0, poly))

        # Test fetch_alerts
        data = civil_protection_service.fetch_alerts()
        self.assertIn("status", data)
        self.assertIn("today", data)
        self.assertIn("tomorrow", data)
        self.assertIn("zone_name", data)
        self.assertIn(data["today"]["level"], ["VERDE", "GIALLA", "ARANCIONE", "ROSSA"])

        # Test API endpoints
        from fastapi.testclient import TestClient
        from backend.main import app
        from backend.config import settings
        client = TestClient(app, cookies={settings.AUTH_COOKIE_NAME: settings.AUTH_TOKEN})
        
        resp = client.get("/api/civil_protection")
        self.assertEqual(resp.status_code, 200)
        json_resp = resp.json()
        self.assertEqual(json_resp["status"], "success")
        self.assertIn("today", json_resp)

        # Test test-alert civil protection
        resp_test = client.post("/api/test-alert?alert_type=civil_protection")
        self.assertEqual(resp_test.status_code, 200)
        self.assertEqual(resp_test.json()["status"], "sent")

    def test_device_scheduler(self):
        from backend.device_scheduler import device_scheduler
        from backend.database import get_active_scheduled_tasks, cancel_scheduled_task
        from fastapi.testclient import TestClient
        from backend.main import app
        from backend.config import settings
        client = TestClient(app, cookies={settings.AUTH_COOKIE_NAME: settings.AUTH_TOKEN})

        # 1. Crea schedule con ritardo 60 minuti (es. accendi clima tra 1 ora)
        t1 = device_scheduler.create_schedule(
            ecosystem="thinq",
            device_id="dev_clima_cameretta_123",
            device_name="Clima Cameretta",
            action="turn_on",
            delay_minutes=60
        )
        self.assertTrue(t1["task_id"].startswith("sched_"))
        self.assertEqual(t1["action"], "turn_on")
        self.assertEqual(t1["device_name"], "Clima Cameretta")

        # 2. Crea schedule con ritardo 300 minuti (es. spegni dopo 5 ore)
        t2 = device_scheduler.create_schedule(
            ecosystem="tuya",
            device_id="dev_cisterna_999",
            device_name="Cisterna",
            action="turn_off",
            delay_minutes=300
        )
        self.assertEqual(t2["action"], "turn_off")

        # 3. Verifica query task attivi
        active = device_scheduler.get_schedules()
        self.assertTrue(any(x["task_id"] == t1["task_id"] for x in active))
        self.assertTrue(any(x["task_id"] == t2["task_id"] for x in active))

        # 4. Verifica API GET /api/devices/schedules
        resp = client.get("/api/devices/schedules")
        self.assertEqual(resp.status_code, 200)
        scheds = resp.json().get("schedules", [])
        self.assertTrue(len(scheds) >= 2)

        # 5. Verifica API POST /api/devices/schedule
        resp_post = client.post("/api/devices/schedule", json={
            "ecosystem": "tuya",
            "device_id": "test_plug_api",
            "device_name": "Presa Test",
            "action": "turn_off",
            "delay_minutes": 15
        })
        self.assertEqual(resp_post.status_code, 200)
        task_api = resp_post.json()["task"]
        self.assertEqual(task_api["action"], "turn_off")

        # 6. Verifica API DELETE /api/devices/schedule/{task_id}
        resp_del = client.delete(f"/api/devices/schedule/{task_api['task_id']}")
        self.assertEqual(resp_del.status_code, 200)
        self.assertEqual(resp_del.json()["status"], "cancelled")

        # 7. Verifica esecuzione task scaduto
        # Crea task già scaduto nel passato
        import backend.device_scheduler
        backend.device_scheduler.notifier.send_alert = MagicMock(return_value={"success": True})
        past_iso = "2020-01-01T00:00:00+00:00"
        t_due = device_scheduler.create_schedule(
            ecosystem="tuya",
            device_id="dev_past",
            device_name="Dispositivo Passato",
            action="turn_off",
            target_time_iso=past_iso
        )
        import asyncio
        loop = asyncio.new_event_loop()
        count = loop.run_until_complete(device_scheduler.execute_due_tasks())
        loop.close()
        self.assertGreaterEqual(count, 1)

        # Pulisci task t1 e t2
        device_scheduler.cancel_schedule(t1["task_id"])
        device_scheduler.cancel_schedule(t2["task_id"])

    def test_tuya_local_crud_and_endpoints(self):
        from backend.database import (
            save_tuya_local_device, get_tuya_local_devices, get_tuya_local_device,
            update_tuya_local_status, update_tuya_local_device_ip, delete_tuya_local_device
        )
        from fastapi.testclient import TestClient
        from backend.main import app
        from backend.config import settings
        client = TestClient(app, cookies={settings.AUTH_COOKIE_NAME: settings.AUTH_TOKEN})

        # 1. Save local device
        save_tuya_local_device(
            device_id="local_test_plug_01",
            name="Presa Cisterna LAN",
            local_key="0123456789abcdef",
            ip_address="192.168.1.150",
            version="3.3",
            category="cz"
        )

        dev = get_tuya_local_device("local_test_plug_01")
        self.assertIsNotNone(dev)
        self.assertEqual(dev["name"], "Presa Cisterna LAN")
        self.assertEqual(dev["local_key"], "0123456789abcdef")
        self.assertEqual(dev["ip_address"], "192.168.1.150")

        # 2. Update status and IP
        update_tuya_local_status("local_test_plug_01", is_on=True, power_w=240.5, voltage_v=229.0, current_a=1.05)
        update_tuya_local_device_ip("local_test_plug_01", "192.168.1.155")
        
        dev_updated = get_tuya_local_device("local_test_plug_01")
        self.assertEqual(dev_updated["ip_address"], "192.168.1.155")
        self.assertTrue(dev_updated["is_on"])
        self.assertEqual(dev_updated["power_w"], 240.5)

        # 3. GET /api/tuya/local/devices
        resp = client.get("/api/tuya/local/devices")
        self.assertEqual(resp.status_code, 200)
        local_devs = resp.json().get("devices", [])
        self.assertTrue(any(d["device_id"] == "local_test_plug_01" for d in local_devs))

        # 4. POST /api/tuya/local/device
        resp_post = client.post("/api/tuya/local/device", json={
            "device_id": "api_local_dev_99",
            "name": "Luce Giardino LAN",
            "local_key": "fedcba9876543210",
            "ip_address": "192.168.1.160",
            "version": "3.3"
        })
        self.assertEqual(resp_post.status_code, 200)

        # 5. DELETE /api/tuya/local/device
        resp_del = client.delete("/api/tuya/local/device/api_local_dev_99")
        self.assertEqual(resp_del.status_code, 200)
        self.assertEqual(resp_del.json()["status"], "ok")

        # Clean up
        delete_tuya_local_device("local_test_plug_01")

    def test_device_aliases_and_rename_endpoints(self):
        from backend.database import save_device_alias, get_device_aliases, delete_device_alias
        from backend.routers.devices import build_devices_catalog
        from fastapi.testclient import TestClient
        from backend.main import app
        from backend.config import settings
        client = TestClient(app, cookies={settings.AUTH_COOKIE_NAME: settings.AUTH_TOKEN})

        # 1. Test database functions
        test_id = "test_alias_dev_100"
        save_device_alias(test_id, "Nuovo Nome Test")
        aliases = get_device_aliases()
        self.assertEqual(aliases.get(test_id), "Nuovo Nome Test")

        # 2. Test API GET /api/devices/aliases
        resp_get = client.get("/api/devices/aliases")
        self.assertEqual(resp_get.status_code, 200)
        self.assertEqual(resp_get.json()["aliases"].get(test_id), "Nuovo Nome Test")

        # 3. Test API POST /api/devices/rename
        resp_rename = client.post("/api/devices/rename", json={
            "device_id": "tuya_test_renamed_plug",
            "alias": "Presa Sala TV",
            "ecosystem": "tuya"
        })
        self.assertEqual(resp_rename.status_code, 200)
        self.assertEqual(resp_rename.json()["alias"], "Presa Sala TV")
        
        aliases_after = get_device_aliases()
        self.assertEqual(aliases_after.get("tuya_test_renamed_plug"), "Presa Sala TV")
        self.assertEqual(aliases_after.get("test_renamed_plug"), "Presa Sala TV")

        # 4. Test GET /devices page loads with timer & rename attributes
        resp_page = client.get("/devices")
        self.assertEqual(resp_page.status_code, 200)
        self.assertIn("modal-rename-box", resp_page.text)
        self.assertIn("card-rename-trigger", resp_page.text)

        # Cleanup
        delete_device_alias(test_id)
        delete_device_alias("tuya_test_renamed_plug")
        delete_device_alias("test_renamed_plug")

    def test_monthly_records_and_digest(self):
        from backend.database import (
            calculate_monthly_summary, save_monthly_summary,
            get_monthly_records, get_all_monthly_summaries,
            rebuild_all_historical_monthly_summaries
        )
        from backend.config import settings
        from backend.alert_engine import engine
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app, cookies={settings.AUTH_COOKIE_NAME: settings.AUTH_TOKEN} if settings.AUTH_TOKEN else {})

        # 1. Test rebuild historical summaries
        rebuild_res = rebuild_all_historical_monthly_summaries()
        self.assertEqual(rebuild_res["status"], "success")

        # 2. Test get monthly records and summaries
        m_recs = get_monthly_records()
        self.assertGreaterEqual(len(m_recs), 10)
        
        m_sums = get_all_monthly_summaries(limit=10)
        self.assertIsInstance(m_sums, list)

        # 3. Test API GET /api/records/monthly
        resp_api = client.get("/api/records/monthly")
        self.assertEqual(resp_api.status_code, 200)
        self.assertIn("monthly_records", resp_api.json())
        self.assertIn("monthly_summaries", resp_api.json())

        # 4. Test API GET /api/export/records-csv
        resp_csv = client.get("/api/export/records-csv")
        self.assertEqual(resp_csv.status_code, 200)
        self.assertIn("ALBO DEI RECORD MENSILI STORICI", resp_csv.text)

        # 5. Test send monthly digest simulation
        digest_res = engine.send_monthly_digest(year=2026, month=8)
        self.assertIn("title", digest_res)
        self.assertIn("Resoconto Mensile", digest_res["title"])

    def test_samsung_health_and_health_connect_integration(self):
        from backend.homeassistant.parsers.health import parse_health_data
        from backend.homeassistant.catalog import CatalogHelper
        from backend.homeassistant import homeassistant_service
        from fastapi.testclient import TestClient
        from backend.main import app
        from backend.config import settings

        client = TestClient(app, cookies={settings.AUTH_COOKIE_NAME: settings.AUTH_TOKEN} if settings.AUTH_TOKEN else {})

        # 1. Mock entities dictionary matching user's Samsung S26 Health Connect setup
        mock_entities = {
            "sensor.samsung_s26_daily_steps": {"entity_id": "sensor.samsung_s26_daily_steps", "state": "3450"},
            "sensor.samsung_s26_steps_sensor": {"entity_id": "sensor.samsung_s26_steps_sensor", "state": "140000"},
            "sensor.samsung_s26_total_calories_burned": {"entity_id": "sensor.samsung_s26_total_calories_burned", "state": "2100.5"},
            "sensor.samsung_s26_basal_metabolic_rate": {"entity_id": "sensor.samsung_s26_basal_metabolic_rate", "state": "1650.0"},
            "sensor.samsung_s26_daily_distance": {"entity_id": "sensor.samsung_s26_daily_distance", "state": "1250.0"},
            "sensor.samsung_s26_daily_floors": {"entity_id": "sensor.samsung_s26_daily_floors", "state": "4"},
            "sensor.samsung_s26_heart_rate": {"entity_id": "sensor.samsung_s26_heart_rate", "state": "72.0"},
            "sensor.samsung_s26_oxygen_saturation": {"entity_id": "sensor.samsung_s26_oxygen_saturation", "state": "98.0"},
            "sensor.samsung_s26_vo2_max": {"entity_id": "sensor.samsung_s26_vo2_max", "state": "38.5"},
            "sensor.samsung_s26_sleep_duration": {"entity_id": "sensor.samsung_s26_sleep_duration", "state": "430.0"},
            "sensor.samsung_s26_weight": {"entity_id": "sensor.samsung_s26_weight", "state": "80500.0"},
            "sensor.samsung_s26_body_fat": {"entity_id": "sensor.samsung_s26_body_fat", "state": "27.5"},
            "sensor.samsung_s26_lean_body_mass": {"entity_id": "sensor.samsung_s26_lean_body_mass", "state": "58300.0"},
            "sensor.samsung_s26_body_water_mass": {"entity_id": "sensor.samsung_s26_body_water_mass", "state": "42500.0"},
            "sensor.samsung_s26_bone_mass": {"entity_id": "sensor.samsung_s26_bone_mass", "state": "2900.0"},
            "sensor.samsung_s26_daily_hydration": {"entity_id": "sensor.samsung_s26_daily_hydration", "state": "1500.0"},
            "sensor.samsung_s26_battery_level": {"entity_id": "sensor.samsung_s26_battery_level", "state": "85"}
        }

        # 2. Test parser output
        health = parse_health_data(mock_entities)
        self.assertTrue(health["is_available"])
        self.assertEqual(health["steps"]["daily"], 3450)
        self.assertEqual(health["steps"]["floors"], 4)
        self.assertEqual(health["steps"]["distance_km"], 1.25)
        self.assertEqual(health["calories"]["total_kcal"], 2100.5)
        self.assertEqual(health["calories"]["active_kcal"], 450.5)
        self.assertEqual(health["heart"]["rate_bpm"], 72)
        self.assertEqual(health["heart"]["spo2_pct"], 98.0)
        self.assertEqual(health["sleep"]["duration_formatted"], "7h 10m")
        self.assertEqual(health["body"]["weight_kg"], 80.5)
        self.assertEqual(health["body"]["fat_pct"], 27.5)
        self.assertEqual(health["battery_pct"], 85)

        # 3. Test Catalog inclusion
        catalog_devs = CatalogHelper.get_catalog_devices(mock_entities, enabled=True)
        health_dev = next((d for d in catalog_devs if d["id"] == "hass_health_samsung"), None)
        self.assertIsNotNone(health_dev)
        self.assertEqual(health_dev["category"], "health")
        self.assertIn("passi", health_dev["status_text"])

        # 4. Test API GET /api/health/summary
        resp_h = client.get("/api/health/summary")
        self.assertEqual(resp_h.status_code, 200)

        # 5. Test Live API includes health payload
        resp_live = client.get("/api/live")
        self.assertEqual(resp_live.status_code, 200)
        self.assertIn("health", resp_live.json())

        # 6. Test API GET /api/health/history
        resp_hist = client.get("/api/health/history?days=14")
        self.assertEqual(resp_hist.status_code, 200)
        self.assertIn("history", resp_hist.json())
        self.assertIn("analytics", resp_hist.json())
        self.assertIn("avg_daily_steps_7d", resp_hist.json()["analytics"])

        # 7. Test Smartwatch multi-device step resolution (Watch with 8,750 steps vs Phone with 1,200 steps)
        mock_watch_entities = {
            "sensor.samsung_s26_daily_steps": {"entity_id": "sensor.samsung_s26_daily_steps", "state": "1200"},
            "sensor.galaxy_watch6_steps_sensor": {"entity_id": "sensor.galaxy_watch6_steps_sensor", "state": "8750"},
            "sensor.galaxy_watch6_heart_rate": {"entity_id": "sensor.galaxy_watch6_heart_rate", "state": "76.0"},
            "sensor.galaxy_watch6_battery_level": {"entity_id": "sensor.galaxy_watch6_battery_level", "state": "92"},
            "sensor.samsung_s26_battery_level": {"entity_id": "sensor.samsung_s26_battery_level", "state": "78"},
        }
        watch_health = parse_health_data(mock_watch_entities)
        self.assertTrue(watch_health["is_available"])
        self.assertEqual(watch_health["steps"]["daily"], 8750)
        self.assertEqual(watch_health["steps"]["watch_steps"], 8750)
        self.assertEqual(watch_health["steps"]["phone_steps"], 1200)
        self.assertTrue(watch_health["has_smartwatch"])
        self.assertIn("Galaxy Watch", watch_health["device_name"])
        self.assertEqual(watch_health["watch_battery_pct"], 92)
        self.assertEqual(watch_health["battery_pct"], 78)

        # 8. Test regression fix: Android hardware steps_sensor (cumulative since boot) must not overwrite daily_steps
        # Also test watch battery_level not being overwritten by battery_state ('discharging'), and clean device name
        mock_real_setup = {
            "sensor.samsung_s26_daily_steps": {"entity_id": "sensor.samsung_s26_daily_steps", "state": "2599"},
            "sensor.samsung_s26_steps_sensor": {"entity_id": "sensor.samsung_s26_steps_sensor", "state": "11099"},
            "sensor.samsung_s26_daily_distance": {"entity_id": "sensor.samsung_s26_daily_distance", "state": "1970.974"},
            "sensor.samsung_s26_battery_level": {"entity_id": "sensor.samsung_s26_battery_level", "state": "86"},
            "sensor.galaxy_watch_ultra_70kf_daily_steps": {"entity_id": "sensor.galaxy_watch_ultra_70kf_daily_steps", "state": "778"},
            "sensor.galaxy_watch_ultra_70kf_steps_sensor": {"entity_id": "sensor.galaxy_watch_ultra_70kf_steps_sensor", "state": "345328"},
            "sensor.galaxy_watch_ultra_70kf_battery_level": {"entity_id": "sensor.galaxy_watch_ultra_70kf_battery_level", "state": "100"},
            "sensor.galaxy_watch_ultra_70kf_battery_state": {"entity_id": "sensor.galaxy_watch_ultra_70kf_battery_state", "state": "discharging"},
            "sensor.galaxy_watch_ultra_70kf_current_time_zone": {
                "entity_id": "sensor.galaxy_watch_ultra_70kf_current_time_zone",
                "state": "Central European Summer Time",
                "attributes": {"friendly_name": "Galaxy Watch Ultra (70KF) Current time zone"}
            },
            "sensor.samsung_s26_weight": {
                "entity_id": "sensor.samsung_s26_weight",
                "state": "79900.0",
                "attributes": {"date": "2026-09-05T06:33:57Z", "source": "com.tuya.smartlife"}
            }
        }
        real_health = parse_health_data(mock_real_setup)
        self.assertTrue(real_health["is_available"])
        self.assertEqual(real_health["steps"]["daily"], 2599)  # NOT 11099!
        self.assertEqual(real_health["steps"]["total_odometer"], 345328)
        self.assertEqual(real_health["steps"]["distance_km"], 1.97)  # NOT 8.32 km!
        self.assertEqual(real_health["battery_pct"], 86)
        self.assertEqual(real_health["watch_battery_pct"], 100)  # NOT None!
        self.assertNotIn("Current time zone", real_health["device_name"])
        self.assertIn("Galaxy Watch Ultra", real_health["device_name"])
        self.assertEqual(real_health["body"]["weight_kg"], 79.9)
        self.assertIsNotNone(real_health["body"]["measured_at_formatted"])


    def test_devices_catalog_tristate_and_ecowitt(self):
        from backend.routers.devices import build_devices_catalog
        from backend.database import save_reading
        
        save_reading({
            "temp_c": 26.5,
            "temp_in_c": 24.0,
            "humidity": 45.0,
            "wind_speed_kmh": 8.0,
            "lightning_distance_km": 15.0,
            "lightning_count": 2,
            "lightning_last_time": "10:15",
            "soil_moisture": {"ch1": 58.0}
        })
        
        catalog = build_devices_catalog()
        devices = catalog.get("devices", [])
        dev_ids = [d["id"] for d in devices]
        
        self.assertIn("ecowitt_station_gateway", dev_ids)
        self.assertIn("ecowitt_wh57_lightning", dev_ids)
        
        gw_dev = next(d for d in devices if d["id"] == "ecowitt_station_gateway")
        self.assertEqual(gw_dev["category"], "weather")
        self.assertTrue(gw_dev["is_online"])
        self.assertTrue(gw_dev["is_on"])
        self.assertIn("Connessa & Live", gw_dev["status_text"])
        
        l_dev = next(d for d in devices if d["id"] == "ecowitt_wh57_lightning")
        self.assertEqual(l_dev["category"], "weather")
        self.assertTrue(l_dev["is_online"])
        self.assertTrue(l_dev["is_on"]) # is_on = True because lightning distance detected
    def test_quiet_hours_and_night_alert_system(self):
        """Testa il sistema di Quiet Hours (Non Disturbare Notturno) e preavviso Notte Tropicale."""
        from datetime import datetime
        from unittest.mock import patch
        from backend.config import settings
        from backend.notifier import notifier, EMERGENCY_ALERT_TYPES
        from backend.alert_engine import AlertEngine
        from backend.database import get_alert_logs

        # 1. Test logica intervallo orario is_in_quiet_hours (23:00 - 07:00)
        settings.QUIET_HOURS_ENABLED = True
        settings.QUIET_HOURS_START = 23
        settings.QUIET_HOURS_END = 7

        dt_night_23 = datetime(2026, 8, 10, 23, 15, 0)
        dt_night_03 = datetime(2026, 8, 11, 3, 30, 0)
        dt_morning_06 = datetime(2026, 8, 11, 6, 59, 0)
        dt_morning_07 = datetime(2026, 8, 11, 7, 0, 0)
        dt_day_14 = datetime(2026, 8, 11, 14, 0, 0)

        self.assertTrue(settings.is_in_quiet_hours(dt_night_23))
        self.assertTrue(settings.is_in_quiet_hours(dt_night_03))
        self.assertTrue(settings.is_in_quiet_hours(dt_morning_06))
        self.assertFalse(settings.is_in_quiet_hours(dt_morning_07))
        self.assertFalse(settings.is_in_quiet_hours(dt_day_14))

        # Disabilitando il toggle generale
        settings.QUIET_HOURS_ENABLED = False
        self.assertFalse(settings.is_in_quiet_hours(dt_night_03))
        settings.QUIET_HOURS_ENABLED = True

        # 2. Test soppressione push per allarmi ordinari e passaggio per emergenze durante Quiet Hours
        from backend.notifier import NotificationService
        with patch.object(settings, "is_in_quiet_hours", return_value=True), \
             patch.object(notifier, "_send_web_push") as mock_web_push, \
             patch("requests.post") as mock_requests_post:

            # A. Allarme ordinario (es. batteria scarica alle 03:00 o terreno secco)
            NotificationService.send_alert(
                notifier,
                alert_type="battery_low",
                title="🪫 Batteria Aton Bassa",
                message="Batteria al 15% di notte.",
                priority="normal"
            )
            # Web push e ntfy NON devono essere stati chiamati (silenzio notturno)
            mock_web_push.assert_not_called()
            mock_requests_post.assert_not_called()

            # B. Emergenza reale (es. allagamento, grandine, sovraccarico 4.5 kW)
            NotificationService.send_alert(
                notifier,
                alert_type="leak",
                title="🚨 ALLARME ALLAGAMENTO!",
                message="Rilevata perdita d'acqua.",
                priority="urgent"
            )
            mock_web_push.assert_called_once()
            if settings.ENABLE_NTFY and settings.NTFY_TOPIC:
                mock_requests_post.assert_called_once()

        # 3. Test preavviso Notte Tropicale nel bilancio serale delle 21:00
        ae = AlertEngine()
        mock_forecast = {
            "hourly_next_36h": [
                {"temp_c": 26.5}, {"temp_c": 25.2}, {"temp_c": 24.8},
                {"temp_c": 23.5}, {"temp_c": 22.0}, {"temp_c": 21.5}
            ]
        }
        with patch("backend.forecast_service.forecast_service.fetch_open_meteo", return_value=mock_forecast), \
             patch.object(notifier, "send_alert") as mock_engine_send_alert:
            res = ae.send_evening_energy_digest()
            self.assertIn("🌴 Notte Tropicale Prevista", res["message"])
            self.assertIn("21.5°C", res["message"])

        # Reset flag
        settings.QUIET_HOURS_ENABLED = True

    def test_fixes_audit_and_optimizations(self):
        import time
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from backend.main import app
        from backend.alert_engine import AlertEngine
        from backend.ecowitt_parser import parse_ecowitt_payload
        from backend.notifier import NotificationService

        # 1. Test root endpoints for Service Worker, Manifest and Redirect
        client = TestClient(app, cookies={settings.AUTH_COOKIE_NAME: settings.AUTH_TOKEN} if settings.AUTH_TOKEN else {})
        r_sw = client.get("/sw.js")
        self.assertEqual(r_sw.status_code, 200)
        self.assertEqual(r_sw.headers.get("Service-Worker-Allowed"), "/")

        r_man = client.get("/manifest.json")
        self.assertEqual(r_man.status_code, 200)

        r_redir = client.get("/alerts", follow_redirects=False)
        self.assertEqual(r_redir.status_code, 301)
        self.assertEqual(r_redir.headers.get("location"), "/alerts-page")

        # 2. Test Rain event logic fix: event_rain > 0 with rain_rate == 0 must not keep is_raining True
        ae = AlertEngine()
        now = time.time()
        # Start of rain
        ae._check_rain({"rain_rate_mm_hr": 5.0, "event_rain_mm": 5.0}, now)
        self.assertTrue(ae.is_raining)
        # Rain stopped 20 minutes ago, but gateway still reports event_rain = 5.0 mm
        ae._check_rain({"rain_rate_mm_hr": 0.0, "event_rain_mm": 5.0}, now + 1200)
        self.assertFalse(ae.is_raining)

        # 3. Test Lightning count reset at midnight
        ae.last_lightning_count = 15
        ae.last_lightning_epoch = 1700000000
        # Gateway resets to 0 at midnight
        ae._check_lightning({"lightning": {"count_total": 0, "distance_km": None, "last_strike_epoch": 1700000000}}, now)
        self.assertEqual(ae.last_lightning_count, 0)
        # First strike of the new day
        with patch.object(notifier, "send_alert") as mock_l_alert:
            ae._check_lightning({"lightning": {"count_total": 1, "distance_km": 12.0, "last_strike_epoch": 1700000000}}, now + 60)
            self.assertEqual(ae.last_lightning_count, 1)
            mock_l_alert.assert_called_once()

        # 4. Test Ecowitt parser supports both "lightning" and "lightning_num"
        raw_p1 = {"PASSKEY": "MOCK", "lightning": "8", "lightning_distance": "14", "dateutc": "2026-08-25 10:00:00"}
        p1 = parse_ecowitt_payload(raw_p1)
        self.assertEqual(p1["lightning"]["count_total"], 8)
        self.assertEqual(p1["lightning"]["distance_km"], 14.0)

        raw_p2 = {"PASSKEY": "MOCK", "lightning_num": "12", "lightning_distance": "6", "dateutc": "2026-08-25 10:00:00"}
        p2 = parse_ecowitt_payload(raw_p2)
        self.assertEqual(p2["lightning"]["count_total"], 12)

        # 5. Test quiet hours bypass for manual test alerts
        with patch.object(settings, "is_in_quiet_hours", return_value=True), \
             patch.object(notifier, "_send_web_push") as mock_wp:
            # Ordinary test alert without force should be silenced
            NotificationService.send_alert(
                notifier,
                alert_type="record",
                title="Test Silenced",
                message="Msg",
                priority="normal",
                force=False
            )
            mock_wp.assert_not_called()

            # Test alert with force=True should bypass quiet hours
            NotificationService.send_alert(
                notifier,
                alert_type="record",
                title="Test Forced",
                message="Msg",
                priority="high",
                force=True
            )
            mock_wp.assert_called_once()

    def test_centralized_helpers_and_devices_catalog(self):
        from backend.helpers import (
            safe_float, safe_int, f_to_c, c_to_f, inch_to_mm, mm_to_inch,
            mph_to_kmh, kmh_to_mph, inhg_to_hpa, hpa_to_inhg, wm2_to_lux, lux_to_wm2,
            get_month_name, get_weekday_name, to_local_datetime_str, ITALIAN_MONTHS, ITALIAN_WEEKDAYS
        )
        from backend.devices_catalog import build_devices_catalog
        from backend.homeassistant.parsers.appliances import WASHER_STATE_MAP, DISHWASHER_STATE_MAP

        # 1. Conversions & Safe Parsing
        self.assertEqual(safe_float("12.5"), 12.5)
        self.assertEqual(safe_float(None, 0.0), 0.0)
        self.assertEqual(safe_float("", 5.5), 5.5)
        self.assertEqual(safe_float("bad", 9.9), 9.9)

        self.assertEqual(safe_int("42"), 42)
        self.assertEqual(safe_int(None, 0), 0)
        self.assertEqual(safe_int("", 7), 7)
        self.assertEqual(safe_int("bad", -1), -1)

        self.assertEqual(f_to_c(32.0), 0.0)
        self.assertEqual(c_to_f(0.0), 32.0)
        self.assertEqual(inch_to_mm(1.0), 25.4)
        self.assertEqual(mm_to_inch(25.4), 1.0)
        self.assertEqual(mph_to_kmh(10.0), 16.1)
        self.assertEqual(kmh_to_mph(16.0934), 10.0)
        self.assertEqual(inhg_to_hpa(29.92), 1013.2)
        self.assertEqual(hpa_to_inhg(1013.2), 29.92)
        self.assertEqual(wm2_to_lux(10.0), 1267.0)
        self.assertEqual(lux_to_wm2(1267.0), 10.0)

        # 2. Date Localization
        self.assertEqual(get_month_name(1), "Gennaio")
        self.assertEqual(get_month_name(8), "Agosto")
        self.assertEqual(get_weekday_name(0), "Lunedì")
        self.assertEqual(get_weekday_name(6), "Domenica")
        self.assertIn("2026-07-15", to_local_datetime_str("2026-07-15T12:00:00Z"))

        # 3. Appliance State Maps
        self.assertIn("weightSensing", WASHER_STATE_MAP)
        self.assertIn("delay_wash", WASHER_STATE_MAP)
        self.assertIn("delayStart", DISHWASHER_STATE_MAP)
        self.assertIn("pre_wash", DISHWASHER_STATE_MAP)

        # 4. Devices Catalog Aggregator
        catalog = build_devices_catalog()
        self.assertIn("devices", catalog)
        self.assertIn("active_schedules", catalog)
        self.assertIn("stats", catalog)
        self.assertIsInstance(catalog["devices"], list)
        self.assertGreaterEqual(len(catalog["devices"]), 1)

    def test_health_sync_and_steps_metadata(self):
        """Testa la presenza dei metadati di aggiornamento passi e del trigger sensori mobile."""
        import asyncio
        from backend.homeassistant.parsers.health import parse_health_data
        from backend.homeassistant_service import homeassistant_service

        mock_entities = {
            "sensor.samsung_s26_daily_steps": {
                "entity_id": "sensor.samsung_s26_daily_steps",
                "state": "8450",
                "last_updated": "2026-09-05T18:30:00Z",
                "attributes": {
                    "sources": ["com.sec.android.app.shealth"],
                    "unit_of_measurement": "steps",
                    "friendly_name": "Samsung S26 Daily Steps"
                }
            }
        }
        res = parse_health_data(mock_entities)
        self.assertTrue(res["is_available"])
        self.assertEqual(res["steps"]["daily"], 8450)
        self.assertEqual(res["steps"]["source_entity"], "sensor.samsung_s26_daily_steps")
        self.assertIn("com.sec.android.app.shealth", res["steps"]["sources"])
        self.assertIsNotNone(res["steps"]["last_updated_formatted"])

        # Verifica che il metodo request_mobile_sensor_update esista e sia invocabile
        self.assertTrue(hasattr(homeassistant_service, "request_mobile_sensor_update"))

if __name__ == "__main__":
    unittest.main()







