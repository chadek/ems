import unittest
from datetime import datetime, timedelta
import time

from ems import EMS
import gpiozero
from gpiozero.pins.mock import MockFactory

gpiozero.Device.pin_factory = MockFactory()


class TestEmsConf(unittest.TestCase):
    def setUp(self):
        self.ems = EMS("ems-test-hydro-conf.conf")
        now = datetime.now().timestamp()

    def tearDown(self):
        del self.ems

    def test_HeaterDisable(self):
        self.assertFalse(self.ems.heater["enable"])

    def test_HydroEnable(self):
        self.assertTrue(self.ems.hydro["enable"])


class TestEms(unittest.TestCase):
    def setUp(self):
        self.ems = EMS("ems-test.conf")
        now = datetime.now().timestamp()

        self.ems.last_battery_measurements = {
            "time": now,
            "battery_DC_V": 25.09,
            "battery_charging_current": 6,
            "battery_discharge_current": 0,
        }
        self.ems.last_pv_measurements = {
            "time": now,
            "pv_DC_V": 70.5,
            "pv_A": 15.0,
            "pv_W": 369,
            "pv_Wh": None,
        }
        self.ems.last_out_measurements = {
            "time": now,
            "out_AC_V": 229.9,
            "out_Hz": 50.0,
            "out_load_percent": 9,
            "ou_load_va": 298,
            "out_load_watt": 209,
            "out_load_watthour": None,
        }

        self.ems.short_mean_battery_measurements = {
            "time": now,
            "battery_DC_V": 26.526666666666667,
            "battery_DC_V_scc": 26.570000000000004,
            "battery_voltage_to_steady_while_charging": 0.0,
            "battery_charging_current": 26.666666666666668,
            "battery_discharge_current": 0.0,
            "battery_soc": 100.0,
        }
        self.ems.short_mean_pv_measurements = {
            "time": now,
            "pv_A": 29.0,
            "pv_DC_V": 54.13333333333333,
            "pv_W": 774.3333333333334,
        }
        self.ems.short_mean_out_measurements = {
            "time": now,
            "out_AC_V": 230.1,
            "out_Hz": 50.0,
            "out_load_percent": 3.0,
            "out_load_va": 91.66666666666667,
            "out_load_watt": 68.66666666666667,
        }
        self.ems.long_mean_battery_measurements = {
            "time": now,
            "battery_DC_V": 26.506547619047616,
            "battery_DC_V_scc": 26.554999999999982,
            "battery_voltage_to_steady_while_charging": 0.0,
            "battery_charging_current": 27.035714285714285,
            "battery_discharge_current": 0.0,
            "battery_soc": 100.0,
        }
        self.ems.long_mean_pv_measurements = {
            "time": now,
            "pv_A": 29.80952380952381,
            "pv_DC_V": 54.16547619047612,
            "pv_W": 782.2261904761905,
        }
        self.ems.long_mean_out_measurements = {
            "time": now,
            "out_AC_V": 229.9547619047619,
            "out_Hz": 49.9904761904762,
            "out_load_percent": 2.642857142857143,
            "out_load_va": 80.98809523809524,
            "out_load_watt": 63.98809523809524,
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
