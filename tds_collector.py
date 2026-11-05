#!/usr/bin/env python3
"""Collect ADS1115 TDS, optional NTC water temperature and calibrated pH.

A1 NTC requires a 10k B3950 probe with 10k pull-up to 3.3V.
A0 pH requires real pH 7 and 4 buffer reference voltages.
Unconfigured or invalid measurements are stored as NULL, never invented.
TDS factor 0.2626 is a provisional estimate, not certified calibration.
"""
import argparse
import logging
import os
import statistics
import time

import pymysql
from dotenv import load_dotenv
from sensorstest import adc_read, estimate_tds_ppm, DEFAULT_TDS_FACTOR
from sensor_conversion import calibrated_ph, ntc_celsius

LOG = logging.getLogger("aquacore.tds")


def save_sample(ppm, temp=None, ph=None):
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
                 round(ppm, 2))
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
        connect_timeout=5,
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT temp_offset_c,ph7_voltage,ph4_voltage FROM sensor_calibration WHERE id=1")
            return cursor.fetchone() or {}
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description="Provisional TDS to AquaCore MariaDB")
    parser.add_argument("--bus", type=int, default=int(os.getenv("TDS_I2C_BUS", "2")))
    parser.add_argument("--address", type=lambda s: int(s, 0), default=0x48)
    parser.add_argument("--temperature", type=float, default=float(os.getenv("TDS_WATER_TEMP_C", "22")))
    parser.add_argument("--tds-factor", type=float, default=DEFAULT_TDS_FACTOR)
    parser.add_argument("--ntc", action="store_true",
                        default=os.getenv("NTC_ENABLED", "").lower() in ("1","true","yes"),
                        help="Enable A1 thermistor (10k B3950 with 10k pull-up to 3.3V)")
    parser.add_argument("--ntc-supply", type=float, default=float(os.getenv("NTC_SUPPLY_V", "3.3")))
    parser.add_argument("--ph7-voltage", type=float, default=float(os.environ["PH7_V"]) if os.getenv("PH7_V") else None)
    parser.add_argument("--ph4-voltage", type=float, default=float(os.environ["PH4_V"]) if os.getenv("PH4_V") else None)
    parser.add_argument("--interval", type=float, default=30)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.bus < 0 or args.interval < 1 or not 1 <= args.samples <= 30:
        parser.error("Invalid bus, interval or sample count")
    if not -2 <= args.temperature <= 55 or not 0 < args.tds_factor <= 10:
        parser.error("Invalid temperature or provisional factor")
    if not 2.5 <= args.ntc_supply <= 3.5:
        parser.error("Invalid NTC supply voltage")
    if (args.ph7_voltage is None) != (args.ph4_voltage is None):
        parser.error("Provide both pH buffer voltages or neither")
    if args.ph7_voltage is not None:
        try:
            calibrated_ph(args.ph7_voltage, args.ph7_voltage, args.ph4_voltage)
        except ValueError as exc:
            parser.error(str(exc))
    load_dotenv(os.getenv("AQUACORE_ENV", os.path.join(os.path.dirname(__file__), ".env")))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    LOG.warning("TDS remains PROVISIONAL; NTC=%s pH calibrated=%s, fallback temp %.1f C",
                args.ntc, args.ph7_voltage is not None, args.temperature)
    while True:
        try:
            calibration = calibration_settings()
            readings = []
            for _ in range(args.samples):
                raw, voltage = adc_read(args.bus, args.address, 3)
                readings.append(voltage)
                time.sleep(0.1)
            volts = statistics.median(readings)
            water_temp = None
            if args.ntc:
                try:
                    ntc_samples = [adc_read(args.bus, args.address, 1) for _ in range(args.samples)]
                    if any(raw >= 32767 for raw, _ in ntc_samples):
                        raise ValueError("ADS1115 A1 saturated")
                    water_temp = ntc_celsius(statistics.median(v for _, v in ntc_samples),
                                              supply_v=args.ntc_supply) + float(calibration.get('temp_offset_c') or 0)
                    if not -2 <= water_temp <= 55:
                        raise ValueError('Calibrated water temperature outside supported range')
                except (OSError, ValueError) as exc:
                    LOG.warning("NTC measurement unavailable: %s", exc)
            ph = None
            v7 = calibration.get('ph7_voltage') if calibration.get('ph7_voltage') is not None else args.ph7_voltage
            v4 = calibration.get('ph4_voltage') if calibration.get('ph4_voltage') is not None else args.ph4_voltage
            if v7 is not None and v4 is not None:
                try:
                    ph_samples = [adc_read(args.bus, args.address, 0) for _ in range(args.samples)]
                    if any(raw >= 32767 for raw, _ in ph_samples):
                        raise ValueError("ADS1115 A0 saturated")
                    ph = calibrated_ph(statistics.median(v for _, v in ph_samples),
                                       float(v7), float(v4))
                except (OSError, ValueError) as exc:
                    LOG.warning("pH measurement unavailable: %s", exc)
            temperature = water_temp if water_temp is not None else args.temperature
            ppm = estimate_tds_ppm(volts, temperature) * args.tds_factor
            save_sample(ppm, water_temp, ph)
            LOG.info("Saved temp=%s C pH=%s TDS=%.2f ppm (A3 %.5f V; TDS factor %.4f; comp temp %.1f C)",
                     f"{water_temp:.2f}" if water_temp is not None else "NULL",
                     f"{ph:.2f}" if ph is not None else "NULL",
                     ppm, volts, args.tds_factor, temperature)
        except (OSError, ValueError, pymysql.MySQLError) as exc:
            LOG.exception("TDS reading not saved: %s", exc)
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
