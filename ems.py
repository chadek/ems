# -*- coding: utf-8 -*-

import argparse
import subprocess
import syslog
import json
from datetime import datetime, timedelta
import requests
import time
import gpiozero
import signal


class EMS:
    # init class loading config file value
    def __init__(self, config_path):
        try:
            with open(config_path, "r") as jsonfile:
                config = json.load(jsonfile)
                # store the wall config in this var to update the config file
                self.conf = config
        except Exception as e:
            syslog.syslog(syslog.LOG_ERR, "Failed to load configuration: {}".format(e))
            raise e

        # Register signal handlers
        signal.signal(signal.SIGTERM, self.graceful_exit)  # for systemd stops
        signal.signal(signal.SIGINT, self.graceful_exit)  # for Ctrl+C

        self.conf["mean"]["short"] = int(self.conf["mean"]["short"])
        self.conf["mean"]["long"] = int(self.conf["mean"]["long"])
        if "hydro" in self.conf:
            self.conf["hydro"]["off_condition"]["long"]["battery_voltage_limit"] = (
                float(
                    self.conf["hydro"]["off_condition"]["long"]["battery_voltage_limit"]
                )
            )
            self.conf["hydro"]["on_condition"]["battery_voltage"] = float(
                self.conf["hydro"]["on_condition"]["battery_voltage"]
            )

            RELAY_HYDRO_PIN = int(self.conf["hydro"]["relay_pin"])
            self.hydro = {
                "enable": True,
                "timer": datetime.now()
                - timedelta(minutes=int(self.conf["hydro"]["state_timer"])),
                "state_timer": int(self.conf["hydro"]["state_timer"]),
                "off_condition": self.conf["hydro"]["off_condition"],
                "on_condition": self.conf["hydro"]["on_condition"],
                "on": False,
            }
            self.relay_hydro = gpiozero.OutputDevice(
                RELAY_HYDRO_PIN, active_high=False, initial_value=False
            )
        else:
            self.hydro = {"enable": False}

        if "heater" in self.conf:
            self.conf["heater"]["off_condition"]["timeout"] = int(
                self.conf["heater"]["off_condition"]["timeout"]
            )
            self.conf["heater"]["off_condition"]["max_daily_run"] = float(
                self.conf["heater"]["off_condition"]["max_daily_run"]
            )
            self.conf["heater"]["off_condition"]["short"]["battery_voltage_limit"] = (
                float(
                    self.conf["heater"]["off_condition"]["short"][
                        "battery_voltage_limit"
                    ]
                )
            )
            self.conf["heater"]["off_condition"]["short"]["load_limit"] = float(
                self.conf["heater"]["off_condition"]["short"]["load_limit"]
            )
            self.conf["heater"]["off_condition"]["long"]["battery_voltage_limit"] = (
                float(
                    self.conf["heater"]["off_condition"]["long"][
                        "battery_voltage_limit"
                    ]
                )
            )
            self.conf["heater"]["off_condition"]["long"]["load_limit"] = float(
                self.conf["heater"]["off_condition"]["long"]["load_limit"]
            )
            self.conf["heater"]["off_condition"]["long"]["input_power"] = float(
                self.conf["heater"]["off_condition"]["long"]["input_power"]
            )
            self.conf["heater"]["on_condition"]["battery_voltage"] = float(
                self.conf["heater"]["on_condition"]["battery_voltage"]
            )
            self.conf["heater"]["on_condition"]["input_power"] = int(
                self.conf["heater"]["on_condition"]["input_power"]
            )
            # Triggered by the output pin going high: active_high=True
            # Initially off: initial_value=False
            RELAY_HEATER_PIN = int(self.conf["heater"]["relay_pin"])
            self.heater = {
                "heating_time_counter": float(0),
                "heating_time_reset": datetime.now(),
                "state_timer": int(self.conf["heater"]["state_timer"]),
                "off_condition": self.conf["heater"]["off_condition"],
                "on_condition": self.conf["heater"]["on_condition"],
                "on": False,
                "timer": datetime.now()
                - timedelta(minutes=int(self.conf["heater"]["state_timer"])),
            }

            self.run_timer = datetime.now().timestamp()
            self.relay_heater = gpiozero.OutputDevice(
                RELAY_HEATER_PIN, active_high=False, initial_value=False
            )
        else:
            self.heater = {"enable": False}

        self.victoriametrics_url = "{}:{}".format(
            self.conf["victoria"]["url"], self.conf["victoria"]["port"]
        )

    def graceful_exit(self, signum, frame):
        # debug print(f"Signal received at {frame.f_code.co_filename}, line {frame.f_lineno}")
        syslog.syslog(
            syslog.LOG_INFO,
            "Received signal {}, disable hydro and Heater".format(signum),
        )
        if self.hydro["enable"] == True:
            self.StopHydro()
        if self.heater["enable"] == True:
            self.StopHeater()
        exit(0)

    def QueryVictoriaMetrics(self, params):
        url = "{}/api/v1/query".format(self.victoriametrics_url)
        try:
            response = requests.get(url, params=params)
            if response.status_code == 200:
                # Parse the JSON response
                result = response.json()
                return result["data"]["result"][0]["value"]
            else:
                syslog.syslog(
                    syslog.LOG_ERR,
                    "Failed to fetch data. HTTP Status code: {}".format(
                        response.status_code
                    ),
                )
        except Exception as e:
            syslog.syslog(syslog.LOG_ERR, "Error while querying data {}".format(e))
            raise e

    def GetLastBatteryData(self):
        try:
            result = {}
            entry = [
                "battery_DC_V",
                "battery_charging_current",
                "battery_discharge_current",
            ]
            for item in entry:
                tmp = self.QueryVictoriaMetrics({"query": item})
                result[item] = float(tmp[1])
            result["time"] = tmp[0]
            self.last_battery_measurements = result
        except Exception as e:
            syslog.syslog(
                syslog.LOG_ERR, "Error while getting Battery data {}".format(e)
            )
            raise e
        return True

    def GetMeanBatteryData(self, range):
        try:
            result = {}
            entry = [
                "battery_DC_V",
                "battery_charging_current",
                "battery_discharge_current",
            ]
            for item in entry:
                tmp = self.QueryVictoriaMetrics(
                    {"query": "avg_over_time({}[{}m])".format(item, range)}
                )
                result[item] = float(tmp[1])
            result["time"] = tmp[0]
        except Exception as e:
            syslog.syslog(
                syslog.LOG_ERR, "Error while getting Battery data {}".format(e)
            )
            raise e
        return result

    def GetLastPVData(self):
        try:
            result = {}
            entry = [
                "pv_DC_V",
                "pv_A",
                "pv_W",
            ]
            for item in entry:
                tmp = self.QueryVictoriaMetrics({"query": item})
                result[item] = float(tmp[1])
            result["time"] = tmp[0]
            self.last_pv_measurements = result
        except Exception as e:
            syslog.syslog(syslog.LOG_ERR, "Error while getting pv data {}".format(e))
            raise e
        return True

    def GetMeanPVData(self, range):
        try:
            result = {}
            entry = [
                "pv_DC_V",
                "pv_A",
                "pv_W",
            ]
            for item in entry:
                tmp = self.QueryVictoriaMetrics(
                    {"query": "avg_over_time({}[{}m])".format(item, range)}
                )
                result[item] = float(tmp[1])
            result["time"] = tmp[0]
        except Exception as e:
            syslog.syslog(
                syslog.LOG_ERR, "Error while getting mean PV data {}".format(e)
            )
            raise e
        return result

    def GetLastOutData(self):
        try:
            result = {}
            entry = [
                "out_AC_V",
                "out_Hz",
                "out_load_percent",
                "out_load_va",
                "out_load_watt",
            ]
            for item in entry:
                tmp = self.QueryVictoriaMetrics({"query": item})
                result[item] = float(tmp[1])
            result["time"] = tmp[0]
            self.last_out_measurements = result
        except Exception as e:
            syslog.syslog(
                syslog.LOG_ERR, "Error while getting smart grid data {}".format(e)
            )
            raise e
        return True

    def GetMeanOutData(self, range):
        try:
            result = {}
            entry = [
                "out_AC_V",
                "out_Hz",
                "out_load_percent",
                "out_load_va",
                "out_load_watt",
            ]
            for item in entry:
                tmp = self.QueryVictoriaMetrics(
                    {"query": "avg_over_time({}[{}m])".format(item, range)}
                )
                result[item] = float(tmp[1])
            result["time"] = tmp[0]
        except Exception as e:
            syslog.syslog(
                syslog.LOG_ERR, "Error while getting mean smart grid data {}".format(e)
            )
            raise e
        return result

    def GetLastGridData(self):
        try:
            result = {}
            entry = ["grid_AC_V", "grid_Hz"]
            for item in entry:
                tmp = self.QueryVictoriaMetrics({"query": item})
                result[item] = float(tmp[1])
            result["time"] = tmp[0]
            self.last_grid_measurements = result
        except Exception as e:
            syslog.syslog(syslog.LOG_ERR, "Error while getting grid data {}".format(e))
            raise e
        return True

    def GetMeanGridData(self, range):
        try:
            result = {}
            entry = ["grid_AC_V", "grid_Hz"]
            for item in entry:
                tmp = self.QueryVictoriaMetrics(
                    {"query": "avg_over_time({}[{}m])".format(item, range)}
                )
                result[item] = float(tmp[1])
            result["time"] = tmp[0]
        except Exception as e:
            syslog.syslog(
                syslog.LOG_ERR, "Error while getting mean grid data {}".format(e)
            )
            raise e
        return result

        # condition :
        # on if :
        #   battery voltage > 26
        #   power in > 400W
        #   off more than 10 minutes
        # immediatly off if :
        #   load higher than X (mean on 15 sec) (2800W?)
        #   battery voltage lower than X (22?) (mean on 15 sec)
        # off after X (20?) minutes running if :
        #   load mean (on 10min) higher than X (2000W)
        #   battery voltage mean (on 10min) lower than X (23?) volts

    def CheckHeater(self):
        now = datetime.now()
        deadline = now - timedelta(seconds=int(self.heater["off_condition"]["timeout"]))

        date = [
            datetime.fromtimestamp(self.last_battery_measurements["time"]),
            datetime.fromtimestamp(self.last_pv_measurements["time"]),
            datetime.fromtimestamp(self.last_out_measurements["time"]),
        ]

        # reset heating timer counter
        if self.heater["heating_time_reset"].day != datetime.today().day:
            syslog.syslog(
                syslog.LOG_INFO,
                "ems: reset max daily heating run counter. Running time: {}".format(
                    self.heater["heating_time_counter"]
                ),
            )
            self.heater["heating_time_counter"] = float(0)
            self.heater["heating_time_reset"] = datetime.now()

        if self.heater["on"]:
            # if last grid value to old power off
            if date[0] < deadline or date[1] < deadline or date[2] < deadline:
                print("Last value too old !!!")
                print("Disable heater !!!")
                self.StopHeater()
                self.heater["timer"] = datetime.now()
                syslog.syslog(
                    syslog.LOG_WARNING,
                    "ems: deadline condition match, turning off heater. No data incoming since {}".format(
                        date
                    ),
                )
                return

            # if run more than X hours per stop
            if (
                self.heater["off_condition"]["max_daily_run"] * 3600
                < self.heater["heating_time_counter"]
            ):
                self.StopHeater()
                self.heater["timer"] = datetime.now()
                print("Max daily run reached, turn off heater")
                syslog.syslog(
                    syslog.LOG_INFO,
                    "ems: Max daily run reached, turning off heater. Running time: {}".format(
                        self.heater["heating_time_counter"]
                    ),
                )
                return

            # if short condition match, trigger power off
            if (
                self.heater["off_condition"]["short"]["load_limit"]
                < self.short_mean_out_measurements["out_load_watt"]
                or self.heater["off_condition"]["short"]["battery_voltage_limit"]
                > self.short_mean_battery_measurements["battery_DC_V"]
            ):
                self.StopHeater()
                self.heater["timer"] = datetime.now()
                print("short limit, turn off heater")
                syslog.syslog(
                    syslog.LOG_INFO,
                    "ems: short condition match, turning off heater. Battery {}, Load: {}".format(
                        self.short_mean_battery_measurements["battery_DC_V"],
                        self.short_mean_out_measurements["out_load_watt"],
                    ),
                )
                return
            # if long condition match, trigger power off
            if (
                self.heater["off_condition"]["long"]["load_limit"]
                < self.long_mean_out_measurements["out_load_watt"]
                or self.heater["off_condition"]["long"]["battery_voltage_limit"]
                > self.long_mean_battery_measurements["battery_DC_V"]
                or self.heater["off_condition"]["long"]["input_power"]
                > self.long_mean_pv_measurements["pv_W"]
            ):
                self.StopHeater()
                self.heater["timer"] = datetime.now()
                print("long limit, turn off heater")
                syslog.syslog(
                    syslog.LOG_INFO,
                    "ems: long condition match, turning off heater. Battery {}, Load: {}, Input_power: {}".format(
                        self.long_mean_battery_measurements["battery_DC_V"],
                        self.long_mean_out_measurements["out_load_watt"],
                        self.long_mean_pv_measurements["pv_W"],
                    ),
                )
                return

        deadline = now - timedelta(minutes=self.heater["state_timer"])

        # if off more than X minutes we try to start heater and daily run not reached
        if (
            not self.heater["on"]
            and self.heater["timer"] < deadline
            and self.heater["off_condition"]["max_daily_run"] * 3600
            > self.heater["heating_time_counter"]
        ):
            # if last input higher than 26 V and 400w, we start heater
            if (
                self.last_battery_measurements["battery_DC_V"]
                > self.heater["on_condition"]["battery_voltage"]
                and self.last_pv_measurements["pv_W"]
                > self.heater["on_condition"]["input_power"]
                and self.last_out_measurements["out_load_watt"]
                < self.heater["on_condition"]["output_power_limit"]
            ):
                print("Start Heater !")
                syslog.syslog(
                    syslog.LOG_INFO,
                    "ems: start condition match, turning on heater. Battery {}, Input power: {}, Load: {}".format(
                        self.last_battery_measurements["battery_DC_V"],
                        self.last_pv_measurements["pv_W"],
                        self.last_out_measurements["out_load_watt"],
                    ),
                )
                self.StartHeater()
                self.heater["timer"] = datetime.now()
                return
        # If no condition was match, ensure current config is apply
        if self.heater["on"]:
            self.StartHeater()
        else:
            self.StopHeater()

    def CheckHydro(self):
        now = datetime.now()
        deadline = now - timedelta(seconds=int(self.hydro["off_condition"]["timeout"]))

        date = [
            datetime.fromtimestamp(self.last_battery_measurements["time"]),
            datetime.fromtimestamp(self.last_pv_measurements["time"]),
            datetime.fromtimestamp(self.last_out_measurements["time"]),
        ]
        if self.hydro["on"]:
            # if last grid value to old power off
            if date[0] < deadline or date[1] < deadline or date[2] < deadline:
                print("Last value too old !!!")
                print("Disable hydro !!!")
                self.StopHydro()
                self.hydro["timer"] = datetime.now()
                syslog.syslog(
                    syslog.LOG_WARNING,
                    "ems: deadline condition match, turning off hydro. No data incoming since {}".format(
                        date
                    ),
                )
                return

            if (
                self.hydro["off_condition"]["long"]["battery_voltage_limit"]
                < self.long_mean_battery_measurements["battery_DC_V"]
            ):
                self.StopHydro()
                self.hydro["timer"] = datetime.now()
                print("long limit, turn off hydro")
                syslog.syslog(
                    syslog.LOG_INFO,
                    "ems: long condition match, turning off hydro. Battery {}, Load: {}, Input_power: {}".format(
                        self.long_mean_battery_measurements["battery_DC_V"],
                        self.long_mean_out_measurements["out_load_watt"],
                        self.long_mean_pv_measurements["pv_W"],
                    ),
                )
                return
            # talvez parar segun la hora:
            #

        deadline = now - timedelta(minutes=self.hydro["state_timer"])
        if not self.hydro["on"] and self.hydro["timer"] < deadline:
            if (
                self.last_battery_measurements["battery_DC_V"]
                < self.hydro["on_condition"]["battery_voltage"]
                or self.last_pv_measurements["pv_W"]
                < self.hydro["on_condition"]["input_power"]
                or self.last_out_measurements["out_load_watt"]
                > self.hydro["on_condition"]["output_power_limit"]
            ):

                print("Start Hydro !")
                syslog.syslog(
                    syslog.LOG_INFO,
                    "ems: start condition match, starting hydro. Battery {}, Input power: {}, Load: {}".format(
                        self.last_battery_measurements["battery_DC_V"],
                        self.last_pv_measurements["pv_W"],
                        self.last_out_measurements["out_load_watt"],
                    ),
                )
                self.StartHydro()
                self.hydro["timer"] = datetime.now()
                return

        # If no condition was match, ensure current config is apply
        if self.hydro["on"]:
            self.StartHydro()
        else:
            self.StopHydro()

    def StartHydro(self):
        self.hydro["on"] = True
        self.relay_hydro.on()

    def StopHydro(self):
        self.hydro["on"] = False
        self.relay_hydro.off()

    def StartHeater(self):
        if not self.heater["on"]:
            self.run_timer = datetime.now().timestamp()
        self.heater["on"] = True
        self.relay_heater.on()

    def StopHeater(self):
        if self.heater["on"]:
            self.heater["heating_time_counter"] += (
                datetime.now().timestamp() - self.run_timer
            )
        self.heater["on"] = False
        self.relay_heater.off()

    def Run(self):
        syslog.syslog(syslog.LOG_INFO, "ems started")
        while True:
            failCount = 0
            now = datetime.now()
            try:
                self.GetLastBatteryData()
                self.GetLastPVData()
                self.GetLastOutData()
                # useless for now self.GetLastGridData()

                self.short_mean_battery_measurements = self.GetMeanBatteryData(
                    self.conf["mean"]["short"]
                )
                self.short_mean_pv_measurements = self.GetMeanPVData(
                    self.conf["mean"]["short"]
                )
                self.short_mean_out_measurements = self.GetMeanOutData(
                    self.conf["mean"]["short"]
                )
                # useless for now self.short_mean_grid_measurements = self.GetMeanGridData(self.heater["off_condition"]["short"]["mean"])
                self.long_mean_battery_measurements = self.GetMeanBatteryData(
                    self.conf["mean"]["long"]
                )
                self.long_mean_pv_measurements = self.GetMeanPVData(
                    self.conf["mean"]["long"]
                )
                self.long_mean_out_measurements = self.GetMeanOutData(
                    self.conf["mean"]["long"]
                )
                # useless for now self.long_mean_grid_measurements = self.GetMeanGridData(date[1], now_str)
                failCount = 0
            except Exception as e:
                syslog.syslog(
                    syslog.LOG_WARNING, "Failed to get influx data {}".format(e)
                )
                failCount += 1

            if failCount == 0:
                if self.heater["enable"] == True:
                    self.CheckHeater()
                if self.hydro["enable"] == True:
                    self.CheckHydro()

            elif failCount >= 10:
                syslog.syslog(
                    syslog.LOG_ERR,
                    "{} inverter polling failed in a raw, process".format(e),
                )
            time.sleep(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--conf", help="path to a config file")
    args = parser.parse_args()

    ems = EMS(args.conf)
    ems.Run()
