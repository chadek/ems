import unittest
from datetime import datetime, timedelta
import time

from ems import EMS
import gpiozero
from gpiozero.pins.mock import MockFactory

gpiozero.Device.pin_factory = MockFactory()


class TestEms(unittest.TestCase):
    def setUp(self):
        self.ems = EMS("ems-test.conf")
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

        self.ems.last_battery_measurements = {
            "time": now,
            "last": 25.09,
            "charging_current": 6,
            "discharge_current": 0,
        }
        self.ems.last_pv_measurements = {
            "time": now,
            "last": 70.5,
            "A": 15.0,
            "W": 369,
            "Wh": None,
        }
        self.ems.last_out_measurements = {
            "time": now,
            "last": 229.9,
            "Hz": 50.0,
            "load_percent": 9,
            "load_va": 298,
            "load_watt": 209,
            "load_watthour": None,
        }

        self.ems.short_mean_battery_measurements = {
            "time": now,
            "mean_DC_V": 26.526666666666667,
            "mean_DC_V_scc": 26.570000000000004,
            "mean_battery_voltage_to_steady_while_charging": 0.0,
            "mean_charging_current": 26.666666666666668,
            "mean_discharge_current": 0.0,
            "mean_soc": 100.0,
        }
        self.ems.short_mean_pv_measurements = {
            "time": now,
            "mean_A": 29.0,
            "mean_DC_V": 54.13333333333333,
            "mean_W": 774.3333333333334,
        }
        self.ems.short_mean_out_measurements = {
            "time": now,
            "mean_AC_V": 230.1,
            "mean_Hz": 50.0,
            "mean_load_percent": 3.0,
            "mean_load_va": 91.66666666666667,
            "mean_load_watt": 68.66666666666667,
        }
        self.ems.long_mean_battery_measurements = {
            "time": now,
            "mean_DC_V": 26.506547619047616,
            "mean_DC_V_scc": 26.554999999999982,
            "mean_battery_voltage_to_steady_while_charging": 0.0,
            "mean_charging_current": 27.035714285714285,
            "mean_discharge_current": 0.0,
            "mean_soc": 100.0,
        }
        self.ems.long_mean_pv_measurements = {
            "time": now,
            "mean_A": 29.80952380952381,
            "mean_DC_V": 54.16547619047612,
            "mean_W": 782.2261904761905,
        }
        self.ems.long_mean_out_measurements = {
            "time": now,
            "mean_AC_V": 229.9547619047619,
            "mean_Hz": 49.9904761904762,
            "mean_load_percent": 2.642857142857143,
            "mean_load_va": 80.98809523809524,
            "mean_load_watt": 63.98809523809524,
        }

    def tearDown(self):
        del self.ems

    def test_StartHeater(self):
        self.ems.heater["on"] = False
        self.ems.StartHeater()
        self.assertTrue(self.ems.heater["on"])

    def test_StopHeater(self):
        self.ems.heater["on"] = True
        self.ems.StopHeater()
        self.assertFalse(self.ems.heater["on"])

    def test_StartHeater_Timer(self):
        time = datetime.now()
        self.ems.run_timer = time
        self.ems.heater["on"] = True
        self.ems.StartHeater()
        self.assertEqual(self.ems.run_timer, time)
        self.ems.heater["on"] = False
        self.ems.StartHeater()
        self.assertNotEqual(self.ems.run_timer, time)

    def test_Heater_Timer(self):
        self.ems.heater["on"] = False
        self.ems.StartHeater()
        time.sleep(1)
        self.ems.StopHeater()
        self.assertEqual(int(self.ems.heater["heating_time_counter"]), 1)

        self.ems.heater["on"] = False
        self.ems.StartHeater()
        time.sleep(2)
        self.ems.StopHeater()
        self.assertEqual(int(self.ems.heater["heating_time_counter"]), 3)

    def test_Heater_Timer_Reset(self):
        self.ems.heater["heating_time_counter"] = 1000
        self.ems.CheckHeater()
        self.assertEqual(self.ems.heater["heating_time_counter"], 1000)
        self.ems.heater["heating_time_reset"] = datetime.now() - timedelta(days=1)
        self.ems.CheckHeater()
        self.assertEqual(self.ems.heater["heating_time_counter"], 0)

    def test_Heater_Timer_Stop(self):
        self.ems.heater["on"] = True
        self.ems.heater["off_condition"]["max_daily_run"] = 1
        self.ems.heater["heating_time_counter"] = 3500
        self.ems.CheckHeater()
        self.assertTrue(self.ems.heater["on"])

        self.ems.heater["heating_time_counter"] = 3601
        self.ems.CheckHeater()
        self.assertFalse(self.ems.heater["on"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
