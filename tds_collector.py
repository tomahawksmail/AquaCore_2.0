#!/usr/bin/env python3
"""Collect ADS1115 TDS, optional NTC water temperature and calibrated pH.

A1 NTC requires a 10k B3950 probe with 10k pull-up to 3.3V.
A0 pH uses saved 6.86 (2.54 V) and 4.01 (3.04 V) buffer references.
A1 must be enabled and calibrated: no fixed 22 C temperature estimate.
TDS factor 0.2626 is a provisional estimate, not certified calibration.
"""
import argparse
import logging
import math
import os
import statistics
import time

import pymysql
from dotenv import load_dotenv
from sensorstest import adc_read, estimate_tds_ppm, DEFAULT_TDS_FACTOR
from sensor_conversion import ntc_celsius, temperature_compensated_ph_two_points

LOG = logging.getLogger("aquacore.tds")


def median_ph_voltage(bus, address, count=5, spacing_s=1.0, *,
                      reader=None, sleeper=None):
    """Sample A0 over time; return one robust median voltage for storage.

    Five samples spaced one second apart span roughly four seconds (plus
    conversion time). A single spurious electrical spike cannot dominate
    the stored pH. Only the median goes into the pH calibration curve, then
    into the database used by both dashboard and charts.

    Parameters are injectable for deterministic tests without I²C hardware.
    """
    if not isinstance(count, int) or not 1 <= count <= 30:
        raise ValueError("pH samples must be an integer between 1 and 30")
    if not math.isfinite(spacing_s) or not 0 <= spacing_s <= 5:
        raise ValueError("Invalid pH sample interval")
    reader = reader or adc_read
    sleeper = sleeper or time.sleep
    values = []
    for index in range(count):
        raw, volts = reader(bus, address, 0)
        if raw >= 32767 or raw <= -32768 or not math.isfinite(volts) or not 0 < volts < 4.096:
            raise ValueError("Invalid or saturated ADS1115 A0 voltage")
        values.append(volts)
        if index < count - 1 and spacing_s:
            sleeper(spacing_s)
    return statistics.median(values)


def save_sample(ppm=None, temp=None, ph=None):
    connection = pymysql.connect(
        host=os.getenv("DB_HOST") or "localhost",
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER") or "aquacore_web",
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME") or "_AquaCore_",
        connect_timeout=5,
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            # Invalid or unconfigured sensors remain NULL, not fake zeros.
            cursor.execute(
                "INSERT INTO `data` (`Datetime`,`temp`,`ph`,`tds`) "
                "VALUES (NOW(), %s, %s, %s)",
                (round(temp, 2) if temp is not None else None,
                 round(ph, 3) if ph is not None else None,
                 round(ppm, 2) if ppm is not None else None)
            )
    finally:
        connection.close()


def calibration_settings():
    connection = pymysql.connect(
        host=os.getenv("DB_HOST") or "localhost",
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER") or "aquacore_web",
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME") or "_AquaCore_",
        connect_timeout=5, autocommit=True,
        cursorclass=pymysql.cursors.DictCursor)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT ntc_enabled,ntc_supply_v,temp_offset_c,temp_updated_at,"
                "tds_factor,temp_factor,ph686_voltage,ph401_voltage,"
                "ph686_temp_c,ph401_temp_c FROM sensor_calibration WHERE id=1")
            return cursor.fetchone() or {}
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description="AquaCore calibrated A1/A0/A3 sensor collector")
    parser.add_argument("--bus", type=int, default=int(os.getenv("TDS_I2C_BUS", "2")))
    parser.add_argument("--address", type=lambda s: int(s, 0), default=0x48)
    parser.add_argument("--interval", type=float, default=30)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.bus < 0 or args.interval < 1 or not 1 <= args.samples <= 30:
        parser.error("Invalid bus, interval or sample count")
    load_dotenv(os.getenv("AQUACORE_ENV", os.path.join(os.path.dirname(__file__), ".env")))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    while True:
        try:
            config = calibration_settings()
            water_temp = None
            ph = None
            ppm = None
            ph_voltage = None
            ph_mode = "A1_UNAVAILABLE"
            try:
                if not bool(int(config.get("ntc_enabled") or 0)):
                    raise ValueError("A1 NTC not enabled")
                if config.get("temp_updated_at") is None:
                    raise ValueError("A1 NTC not calibrated")
                supply = float(config.get("ntc_supply_v") if config.get("ntc_supply_v") is not None else 3.3)
                if not 3.0 <= supply <= 3.6:
                    raise ValueError("Invalid A1 divider voltage")
                values = [adc_read(args.bus, args.address, 1) for _ in range(args.samples)]
                if any(raw >= 32767 or raw <= -32768 for raw, _ in values):
                    raise ValueError("A1 ADC saturated")
                raw_temp = ntc_celsius(statistics.median(v for _, v in values), supply_v=supply)
                factor = float(config.get("temp_factor") if config.get("temp_factor") is not None else 1.0)
                water_temp = raw_temp * factor + float(config.get("temp_offset_c") or 0)
                if not math.isfinite(water_temp) or not 0 <= water_temp <= 50:
                    raise ValueError("Calibrated A1 temperature outside 0-50 C")
            except (TypeError, ValueError, OSError, OverflowError) as exc:
                LOG.warning("Calibrated A1 unavailable: %s. pH/TDS NULL", exc)

            if water_temp is not None:
                try:
                    ph_voltage = median_ph_voltage(
                        args.bus, args.address, count=args.samples, spacing_s=1.0)
                    keys = ("ph686_voltage","ph401_voltage","ph686_temp_c","ph401_temp_c")
                    if not all(config.get(k) is not None for k in keys):
                        raise ValueError("Two-point pH calibration missing")
                    ph = temperature_compensated_ph_two_points(
                        ph_voltage,
                        float(config["ph686_voltage"]), float(config["ph401_voltage"]),
                        float(config["ph686_temp_c"]), float(config["ph401_temp_c"]),
                        water_temp)
                    ph_mode = "TWO_BUFFER_A1_ATC"
                except (TypeError, ValueError, OSError, OverflowError) as exc:
                    ph_mode = "TWO_BUFFER_INVALID"
                    LOG.warning("pH unavailable: %s (A0=%s V)", exc, ph_voltage)

                try:
                    samples = [adc_read(args.bus, args.address, 3) for _ in range(args.samples)]
                    if any(raw >= 32767 or raw <= -32768 for raw, _ in samples):
                        raise ValueError("A3 TDS ADC saturated")
                    vtds = statistics.median(v for _, v in samples)
                    tds_factor = float(config.get("tds_factor") if config.get("tds_factor") is not None else DEFAULT_TDS_FACTOR)
                    if not math.isfinite(tds_factor) or not 0.001 <= tds_factor <= 10:
                        raise ValueError("Invalid TDS factor")
                    ppm = estimate_tds_ppm(vtds, water_temp) * tds_factor
                except (OSError, ValueError, TypeError, OverflowError) as exc:
                    LOG.warning("TDS unavailable: %s", exc)

            save_sample(ppm, water_temp, ph)
            LOG.info("Saved temp=%s C pH=%s TDS=%s ppm (mode=%s A0=%s V; A1 ATC=%s)",
                     f"{water_temp:.2f}" if water_temp is not None else "NULL",
                     f"{ph:.2f}" if ph is not None else "NULL",
                     f"{ppm:.2f}" if ppm is not None else "NULL",
                     ph_mode, f"{ph_voltage:.5f}" if ph_voltage is not None else "NULL",
                     "ON" if water_temp is not None else "OFF")
        except (OSError, ValueError, TypeError, pymysql.MySQLError):
            LOG.exception("Sensor reading not saved")
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
