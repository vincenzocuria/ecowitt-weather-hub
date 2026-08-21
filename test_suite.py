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
        self.assertIn("Database SQLite & Manutenzione", res_set.text)
        self.assertIn("Personalizzazione Nomi Sensori", res_set.text)
        self.assertIn("Notifiche Push", res_set.text)

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

        client = TestClient(app, cookies={settings.AUTH_COOKIE_NAME: settings.AUTH_TOKEN} if settings.AUTH_TOKEN else {})
        res = client.get("/api/energy/house-breakdown")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("total_house_w", data)
        self.assertIn("monitored_power_w", data)
        self.assertIn("unmonitored_power_w", data)
        self.assertIn("monitored_pct", data)
        self.assertIn("unmonitored_pct", data)
        self.assertIn("active_consumers", data)
        self.assertIn("standby_devices", data)
        self.assertIsInstance(data["active_consumers"], list)
        self.assertIsInstance(data["standby_devices"], list)

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
            "soil_moisture": {"ch1": 42.0, "ch2": 18.0}
        })
        save_reading({
            "timestamp": "2026-07-16T04:00:00",
            "temp_c": 26.2, # Notte Rovente >= 25°C
            "soil_moisture": {"ch1": 40.0, "ch2": 15.0}
        })
        save_reading({
            "timestamp": "2026-07-17T04:00:00",
            "temp_c": 23.0,
            "soil_moisture": {"ch1": 55.0, "ch2": 35.0}
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

        r_home = client.get("/")
        self.assertEqual(r_home.status_code, 200)
        self.assertIn("hero_tropical_pill", r_home.text)

        # 8. Test alert engine soil dry & soil wet
        from backend.alert_engine import AlertEngine
        test_engine = AlertEngine()
        test_engine.last_soil_alert = {}
        test_engine.last_soil_wet_alert = {}

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


if __name__ == "__main__":
    unittest.main()





