# -*- coding: utf-8 -*-

import argparse
import subprocess
import syslog
import json
from datetime import datetime, timedelta
import influxdb
import time
import gpiozero


#


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

        self.conf["heater"]["off_condition"]["timeout"] = int(
            self.conf["heater"]["off_condition"]["timeout"]
        )
        self.conf["heater"]["off_condition"]["short"]["mean"] = int(
            self.conf["heater"]["off_condition"]["short"]["mean"]
        )
        self.conf["heater"]["off_condition"]["short"]["battery_voltage_limit"] = float(
            self.conf["heater"]["off_condition"]["short"]["battery_voltage_limit"]
        )
        self.conf["heater"]["off_condition"]["short"]["load_limit"] = float(
            self.conf["heater"]["off_condition"]["short"]["load_limit"]
        )
        self.conf["heater"]["off_condition"]["long"]["mean"] = int(
            self.conf["heater"]["off_condition"]["long"]["mean"]
        )
        self.conf["heater"]["off_condition"]["long"]["battery_voltage_limit"] = float(
            self.conf["heater"]["off_condition"]["long"]["battery_voltage_limit"]
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
        RELAY_PIN = int(self.conf["heater"]["relay_pin"])
        self.heater = {
            "state_timer": int(self.conf["heater"]["state_timer"]),
            "off_condition": self.conf["heater"]["off_condition"],
            "on_condition": self.conf["heater"]["on_condition"],
            "on": False,
            "timer": datetime.now()
            - timedelta(minutes=int(self.conf["heater"]["state_timer"])),
        }

        self.status_timer = datetime.now()
        self.relay = gpiozero.OutputDevice(
            RELAY_PIN, active_high=False, initial_value=False
        )
        self.influx_client = influxdb.InfluxDBClient(
            self.conf["influx"]["host"],
            self.conf["influx"]["port"],
            self.conf["influx"]["user"],
            self.conf["influx"]["password"],
            self.conf["influx"]["database"],
        )

    def GetLastBatteryData(self):
        try:
            result = self.influx_client.query(
                "SELECT LAST(DC_V), charging_current, discharge_current FROM battery"
            )
            self.last_battery_measurements = list(result.get_points())[0]
        except Exception as e:
            syslog.syslog(
                syslog.LOG_ERR, "Error while getting Battery data {}".format(e)
            )
            raise e
        return True

    def GetMeanBatteryData(self, start, end):
        try:
            result = self.influx_client.query(
                "SELECT MEAN(*) FROM battery WHERE time >= '{}' AND time <= '{}' GROUP BY * fill(0)".format(
                    start, end
                )
            )
        except Exception as e:
            syslog.syslog(
                syslog.LOG_ERR, "Error while getting Battery data {}".format(e)
            )
            raise e
        return list(result.get_points())[0]

    def GetLastPVData(self):
        try:
            result = self.influx_client.query("SELECT LAST(DC_V), A, W, Wh FROM pv")
            self.last_pv_measurements = list(result.get_points())[0]
        except Exception as e:
            syslog.syslog(syslog.LOG_ERR, "Error while getting pv data {}".format(e))
            raise e
        return True

    def GetMeanPVData(self, start, end):
        try:
            result = self.influx_client.query(
                "SELECT MEAN(*) FROM pv WHERE time >= '{}' AND time <= '{}' GROUP BY * fill(0)".format(
                    start, end
                )
            )
        except Exception as e:
            syslog.syslog(
                syslog.LOG_ERR, "Error while getting mean PV data {}".format(e)
            )
            raise e
        return list(result.get_points())[0]

    def GetLastOutData(self):
        try:
            result = self.influx_client.query(
                "SELECT LAST(AC_V), Hz, load_percent, load_va, load_watt, load_watthour FROM out"
            )
            self.last_out_measurements = list(result.get_points())[0]
        except Exception as e:
            syslog.syslog(
                syslog.LOG_ERR, "Error while getting smart grid data {}".format(e)
            )
            raise e
        return True

    def GetMeanOutData(self, start, end):
        try:
            result = self.influx_client.query(
                "SELECT MEAN(*) FROM out WHERE time >= '{}' AND time <= '{}' GROUP BY * fill(0)".format(
                    start, end
                )
            )
        except Exception as e:
            syslog.syslog(
                syslog.LOG_ERR, "Error while getting mean smart grid data {}".format(e)
            )
            raise e
        return list(result.get_points())[0]

    def GetLastGridData(self):
        try:
            result = self.influx_client.query("SELECT LAST(AC_V), Hz FROM grid")
            self.last_grid_measurements = list(result.get_points())[0]
        except Exception as e:
            syslog.syslog(syslog.LOG_ERR, "Error while getting grid data {}".format(e))
            raise e
        return True

    def GetMeanGridData(self, start, end):
        try:
            result = self.influx_client.query(
                "SELECT MEAN(*) FROM grid WHERE time >= '{}' AND time <= '{}' GROUP BY * fill(0)".format(
                    start, end
                )
            )
        except Exception as e:
            syslog.syslog(
                syslog.LOG_ERR, "Error while getting mean grid data {}".format(e)
            )
            raise e
        return list(result.get_points())[0]

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
        format = "%Y-%m-%dT%H:%M:%SZ"
        date = [
            datetime.strptime(self.last_battery_measurements["time"], format),
            datetime.strptime(self.last_pv_measurements["time"], format),
            datetime.strptime(self.last_out_measurements["time"], format),
        ]
        if self.heater["on"]:
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
            if (
                self.heater["off_condition"]["short"]["load_limit"]
                < self.short_mean_out_measurements["mean_load_watt"]
                or self.heater["off_condition"]["short"]["battery_voltage_limit"]
                > self.short_mean_battery_measurements["mean_DC_V"]
            ):
                self.StopHeater()
                self.heater["timer"] = datetime.now()
                print("short limit, turn off heater")
                syslog.syslog(
                    syslog.LOG_INFO,
                    "ems: short condition match, turning off heater. Battery {}, Load: {}".format(
                        self.short_mean_battery_measurements["mean_DC_V"],
                        self.short_mean_out_measurements["mean_load_watt"],
                    ),
                )
                return
            if (
                self.heater["off_condition"]["long"]["load_limit"]
                < self.long_mean_out_measurements["mean_load_watt"]
                or self.heater["off_condition"]["long"]["battery_voltage_limit"]
                > self.long_mean_battery_measurements["mean_DC_V"]
                or self.heater["off_condition"]["long"]["input_power"]
                > self.long_mean_pv_measurements["mean_W"]
            ):
                self.StopHeater()
                self.heater["timer"] = datetime.now()
                print("long limit, turn off heater")
                syslog.syslog(
                    syslog.LOG_INFO,
                    "ems: long condition match, turning off heater. Battery {}, Load: {}, Input_power: {}".format(
                        self.long_mean_battery_measurements["mean_DC_V"],
                        self.long_mean_out_measurements["mean_load_watt"],
                        self.long_mean_pv_measurements["mean_W"],
                    ),
                )
                return

        deadline = now - timedelta(minutes=self.heater["state_timer"])
        # if off more than X minutes we try to start heater
        if not self.heater["on"] and self.heater["timer"] < deadline:
            # if last input higher than 26 V and 400w, we start heater
            if (
                self.last_battery_measurements["last"]
                > self.heater["on_condition"]["battery_voltage"]
                and self.last_pv_measurements["W"]
                > self.heater["on_condition"]["input_power"]
                and self.last_out_measurements["load_watt"]
                < self.heater["on_condition"]["output_power_limit"]
            ):
                print("Start Heater !")
                syslog.syslog(
                    syslog.LOG_INFO,
                    "ems: start condition match, turning on heater. Battery {}, Input power: {}, Load: {}".format(
                        self.last_battery_measurements["last"],
                        self.last_pv_measurements["W"],
                        self.last_out_measurements["load_watt"],
                    ),
                )
                self.StartHeater()
                self.heater["timer"] = datetime.now()
                print(self.heater)
                return
        # If no condition was match, ensure current config is apply
        if self.heater["on"]:
            self.StartHeater()
        else:
            self.StopHeater()

    def StartHeater(self):
        self.relay.on()
        self.heater["on"] = True

    def StopHeater(self):
        self.heater["on"] = False
        self.relay.off()

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
                format = "%Y-%m-%dT%H:%M:%SZ"
                now_str = datetime.strftime(now, format)
                date = [
                    datetime.strftime(
                        now
                        - timedelta(
                            seconds=int(self.heater["off_condition"]["short"]["mean"])
                        ),
                        format,
                    ),
                    datetime.strftime(
                        now
                        - timedelta(
                            minutes=int(self.heater["off_condition"]["long"]["mean"])
                        ),
                        format,
                    ),
                ]
                self.short_mean_battery_measurements = self.GetMeanBatteryData(
                    date[0], now_str
                )
                self.short_mean_pv_measurements = self.GetMeanPVData(date[0], now_str)
                self.short_mean_out_measurements = self.GetMeanOutData(date[0], now_str)
                # useless for now self.short_mean_grid_measurements = self.GetMeanGridData(date[0], now_str)
                self.long_mean_battery_measurements = self.GetMeanBatteryData(
                    date[1], now_str
                )
                self.long_mean_pv_measurements = self.GetMeanPVData(date[1], now_str)
                self.long_mean_out_measurements = self.GetMeanOutData(date[1], now_str)
                # useless for now self.long_mean_grid_measurements = self.GetMeanGridData(date[1], now_str)
                failCount = 0
            except Exception as e:
                syslog.syslog(syslog.LOG_ERR, "Failed to get influx data {}".format(e))
                failCount += 1

            if failCount == 0:
                self.CheckHeater()

            elif failCount == 10:
                syslog.syslog(
                    syslog.LOG_ERR,
                    "{} inverter polling failed in a raw, process".format(e),
                )
            time.sleep(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--conf", help="path to a config file")
    args = parser.parse_args()

    ems = EMS(args.conf)
    ems.Run()
