#!/usr/bin/env python3
"""Collect provisional temperature-compensated TDS into AquaCore data.tds.

No temperature or pH probes are configured: insert NULL for both fields.
The provisional 0.2626 factor assumes boiled Primo water contained 13 ppm;
this is NOT a certified calibration and must not be used for safety control.
"""
import argparse
import logging
import os
import statistics
import time

import pymysql
from dotenv import load_dotenv
from sensorstest import adc_read, estimate_tds_ppm, DEFAULT_TDS_FACTOR

LOG = logging.getLogger("aquacore.tds")


def save_tds(ppm):
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
            # Unavailable temp/pH are NULL rather than fictitious measurements.
            cursor.execute(
                "INSERT INTO `data` (`Datetime`,`temp`,`ph`,`tds`) "
                "VALUES (NOW(), NULL, NULL, %s)", (round(ppm, 2),)
            )
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description="Provisional TDS to AquaCore MariaDB")
    parser.add_argument("--bus", type=int, default=int(os.getenv("TDS_I2C_BUS", "2")))
    parser.add_argument("--address", type=lambda s: int(s, 0), default=0x48)
    parser.add_argument("--temperature", type=float, default=float(os.getenv("TDS_WATER_TEMP_C", "22")))
    parser.add_argument("--tds-factor", type=float, default=DEFAULT_TDS_FACTOR)
    parser.add_argument("--interval", type=float, default=30)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.bus < 0 or args.interval < 1 or not 1 <= args.samples <= 30:
        parser.error("Invalid bus, interval or sample count")
    if not -2 <= args.temperature <= 55 or not 0 < args.tds_factor <= 10:
        parser.error("Invalid temperature or provisional factor")
    load_dotenv(os.getenv("AQUACORE_ENV", os.path.join(os.path.dirname(__file__), ".env")))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    LOG.warning("TDS readings are PROVISIONAL, not reference-calibrated; water temp %.1f C",
                args.temperature)
    while True:
        try:
            readings = []
            for _ in range(args.samples):
                raw, voltage = adc_read(args.bus, args.address, 3)
                readings.append(voltage)
                time.sleep(0.1)
            volts = statistics.median(readings)
            ppm = estimate_tds_ppm(volts, args.temperature) * args.tds_factor
            save_tds(ppm)
            LOG.info("Saved TDS %.2f ppm (A3 %.5f V, multiplier %.4f, temp %.1f C)",
                     ppm, volts, args.tds_factor, args.temperature)
        except (OSError, ValueError, pymysql.MySQLError) as exc:
            LOG.exception("TDS reading not saved: %s", exc)
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
