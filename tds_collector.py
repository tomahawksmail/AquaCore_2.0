#!/usr/bin/env python3
"""Collect ADS1115 TDS, optional NTC water temperature and calibrated pH.

A1 NTC requires a 10k B3950 probe with 10k pull-up to 5.0V.
A0 pH uses measured 4.01/6.86/9.18 voltages when present, or legacy 7/4.
Unconfigured or invalid measurements are stored as NULL, never invented.
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
from sensor_conversion import (calibrated_ph, calibrated_ph_three_points,
                               temperature_compensated_ph_three_points, ntc_celsius)

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
            cursor.execute("SELECT ntc_enabled,ntc_supply_v,temp_offset_c,temp_updated_at,ph7_voltage,ph4_voltage,tds_factor,ph_factor,temp_factor,"
                           "ph401_voltage,ph686_voltage,ph918_voltage,"
                           "ph401_temp_c,ph686_temp_c,ph918_temp_c,"
                           "ph401_reference,ph686_reference,ph918_reference "
                           "FROM sensor_calibration WHERE id=1")
            return cursor.fetchone() or {}
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description="Provisional TDS to AquaCore MariaDB")
    parser.add_argument("--bus", type=int, default=int(os.getenv("TDS_I2C_BUS", "2")))
    parser.add_argument("--address", type=lambda s: int(s, 0), default=0x48)
    parser.add_argument("--temperature", type=float, default=float(os.getenv("TDS_WATER_TEMP_C", "22")))
    parser.add_argument("--tds-factor", type=float, default=DEFAULT_TDS_FACTOR)
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
    if (args.ph7_voltage is None) != (args.ph4_voltage is None):
        parser.error("Provide both pH buffer voltages or neither")
    if args.ph7_voltage is not None:
        try:
            calibrated_ph(args.ph7_voltage, args.ph7_voltage, args.ph4_voltage)
        except ValueError as exc:
            parser.error(str(exc))
    load_dotenv(os.getenv("AQUACORE_ENV", os.path.join(os.path.dirname(__file__), ".env")))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    LOG.warning("TDS remains PROVISIONAL; NTC enabled and supply are read from MariaDB each cycle; "
                "pH CLI calibrated=%s, fallback TDS temp %.1f C",
                args.ph7_voltage is not None, args.temperature)
    while True:
        try:
            calibration = calibration_settings()
            ntc_enabled = bool(int(calibration.get('ntc_enabled') or 0))
            ntc_supply_v = float(calibration.get('ntc_supply_v') if
                                 calibration.get('ntc_supply_v') is not None else 5.0)
            if not math.isfinite(ntc_supply_v) or not 4.5 <= ntc_supply_v <= 5.5:
                if ntc_enabled:
                    LOG.warning("Invalid NTC divider supply in MariaDB; A1 disabled for this sample")
                ntc_enabled = False
            readings = []
            for _ in range(args.samples):
                raw, voltage = adc_read(args.bus, args.address, 3)
                readings.append(voltage)
                time.sleep(0.1)
            volts = statistics.median(readings)
            water_temp = None
            if ntc_enabled and calibration.get('temp_updated_at') is None:
                LOG.warning("A1 enabled but temperature calibration has not been saved; "
                            "leaving temp NULL and pH ATC OFF")
            if ntc_enabled and calibration.get('temp_updated_at') is not None:
                try:
                    ntc_samples = [adc_read(args.bus, args.address, 1) for _ in range(args.samples)]
                    if any(raw >= 32767 for raw, _ in ntc_samples):
                        raise ValueError("ADS1115 A1 saturated")
                    temp_raw = ntc_celsius(statistics.median(v for _, v in ntc_samples),
                                             supply_v=ntc_supply_v)
                    water_temp = temp_raw * float(calibration.get('temp_factor') if calibration.get('temp_factor') is not None else 1.0) + float(calibration.get('temp_offset_c') or 0)
                    if not -2 <= water_temp <= 55:
                        raise ValueError('Calibrated water temperature outside supported range')
                except (OSError, ValueError) as exc:
                    LOG.warning("NTC measurement unavailable: %s", exc)
            ph = None
            ph_atc = False
            v7 = calibration.get('ph7_voltage') if calibration.get('ph7_voltage') is not None else args.ph7_voltage
            v4 = calibration.get('ph4_voltage') if calibration.get('ph4_voltage') is not None else args.ph4_voltage
            three_keys = ('ph401_voltage','ph686_voltage','ph918_voltage',
                          'ph401_reference','ph686_reference','ph918_reference')
            has_three = all(calibration.get(key) is not None for key in three_keys)
            if has_three or (v7 is not None and v4 is not None):
                try:
                    # A0 is sampled across multiple seconds rather than
                    # taking five nearly simultaneous reads. This rejects
                    # isolated spikes before pH conversion and DB storage.
                    ph_voltage = median_ph_voltage(
                        args.bus, args.address, count=args.samples, spacing_s=1.0)
                    temp_keys = ('ph401_temp_c', 'ph686_temp_c', 'ph918_temp_c')
                    # Never silently use the collector's fallback temperature
                    # as measured water temperature. ATC needs a real NTC
                    # reading and a completed temperature calibration.
                    ph_atc = bool(has_three and water_temp is not None
                                 and calibration.get('temp_updated_at') is not None
                                 and all(calibration.get(k) is not None for k in temp_keys)
                                 and 0 <= water_temp <= 50)
                    if ph_atc:
                        ph_raw = temperature_compensated_ph_three_points(
                            ph_voltage,
                            *(float(calibration[k]) for k in three_keys),
                            *(float(calibration[k]) for k in temp_keys),
                            water_temp)
                    elif has_three:
                        ph_raw = calibrated_ph_three_points(
                            ph_voltage, *(float(calibration[key]) for key in three_keys))
                    else:
                        ph_raw = calibrated_ph(ph_voltage, float(v7), float(v4))
                    ph = 7.0 + (ph_raw - 7.0) * float(
                        calibration.get('ph_factor') if calibration.get('ph_factor') is not None else 1.0)
                    if not 0 <= ph <= 14:
                        raise ValueError("Corrected pH outside 0-14")
                except (OSError, ValueError) as exc:
                    LOG.warning("pH measurement unavailable: %s", exc)
            temperature = water_temp if water_temp is not None else args.temperature
            tds_factor = float(calibration.get('tds_factor') if calibration.get('tds_factor') is not None else args.tds_factor)
            if not 0.001 <= tds_factor <= 10:
                raise ValueError("Invalid database TDS factor")
            ppm = estimate_tds_ppm(volts, temperature) * tds_factor
            save_sample(ppm, water_temp, ph)
            LOG.info("Saved temp=%s C pH=%s TDS=%.2f ppm (pH ATC=%s; A3 %.5f V; TDS factor %.4f; TDS temp %.1f C)",
                     f"{water_temp:.2f}" if water_temp is not None else "NULL",
                     f"{ph:.2f}" if ph is not None else "NULL",
                     "ON" if ph_atc else "OFF",
                     ppm, volts, tds_factor, temperature)
        except (OSError, ValueError, pymysql.MySQLError) as exc:
            LOG.exception("TDS reading not saved: %s", exc)
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
