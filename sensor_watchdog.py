#!/usr/bin/env python3
"""Insert zero readings when AquaCore's sensor writer stops sending data.

This is a separate OPTIONAL watchdog; it does not read sensors or control GPIO.
It uses MariaDB server time and a single named lock to avoid duplicate writers.
"""
import argparse
import logging
import os
import signal
import time
from datetime import timedelta

import pymysql
from dotenv import load_dotenv
from pymysql.cursors import DictCursor

LOG = logging.getLogger("aquacore.sensor_watchdog")
RUNNING = True
LOCK_NAME = "aquacore_sensor_zero_fallback"

def stop(_signum, _frame):
    global RUNNING
    RUNNING = False

def connect():
    return pymysql.connect(
        host=os.getenv("DB_HOST") or os.getenv("HOST") or "localhost",
        user=os.getenv("DB_USER") or os.getenv("USER"),
        password=os.getenv("DB_PASSWORD") or os.getenv("PASSWORD"),
        database=os.getenv("DB_NAME") or os.getenv("DATABASE"),
        cursorclass=DictCursor, autocommit=False,
        connect_timeout=5, read_timeout=5, write_timeout=5,
    )

def check_and_insert(stale_seconds, interval_seconds, apply=False):
    connection = connect()
    locked = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK(%s, 0) AS obtained", (LOCK_NAME,))
            locked = cursor.fetchone()["obtained"] == 1
            if not locked:
                LOG.warning("Another watchdog holds the database lock; skipping")
                return
            cursor.execute("SELECT NOW() AS now_time")
            now = cursor.fetchone()["now_time"]
            cursor.execute(
                "SELECT Id, Datetime, temp, ph, tds FROM `data` "
                "ORDER BY Datetime DESC, Id DESC LIMIT 1"
            )
            latest = cursor.fetchone()
            if not latest:
                LOG.warning("No sensor rows yet; not fabricating an initial reading")
                return
            stamp = latest["Datetime"]
            if stamp is None:
                LOG.warning("Latest row has NULL Datetime; skipping")
                return
            age = (now - stamp).total_seconds()
            if age < 0:
                LOG.warning("Latest sensor timestamp is in the future; skipping")
                return
            if age < stale_seconds:
                LOG.debug("Latest reading age %.0fs; healthy", age)
                return
            # Avoid writing more often than once per interval by checking the
            # timestamp of the last row, whether real or synthetic.
            # A synthetic all-zero row cannot be distinguished from real zeros,
            # so apply a staleness threshold only to the latest row.
            if age < max(stale_seconds, interval_seconds):
                return
            LOG.warning("No new readings for %.0f seconds", age)
            if not apply:
                LOG.warning("DRY RUN: would insert temp=0, ph=0, tds=0")
                return
            cursor.execute(
                "INSERT INTO `data` (`Datetime`, `temp`, `ph`, `tds`) "
                "VALUES (NOW(), 0, 0, 0)"
            )
            connection.commit()
            LOG.warning("Inserted zero row into data (Id %s)", cursor.lastrowid)
    except Exception:
        connection.rollback()
        raise
    finally:
        if locked:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT RELEASE_LOCK(%s)", (LOCK_NAME,))
            except pymysql.MySQLError:
                LOG.exception("Failed to release advisory lock")
        connection.close()

def main():
    parser = argparse.ArgumentParser(description="AquaCore sensor missing-data watchdog")
    parser.add_argument("--apply", action="store_true", help="Write zeros into MariaDB (default: dry-run)")
    parser.add_argument("--stale-seconds", type=int, default=120)
    parser.add_argument("--poll-seconds", type=int, default=15)
    args = parser.parse_args()
    if args.stale_seconds < 15 or args.poll_seconds < 1:
        parser.error("stale-seconds >= 15 and poll-seconds >= 1 required")
    load_dotenv(os.getenv("AQUACORE_ENV", os.path.join(os.path.dirname(__file__), ".env")))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    LOG.warning("Sensor watchdog started (%s, stale=%ds)", "LIVE" if args.apply else "DRY RUN", args.stale_seconds)
    while RUNNING:
        try:
            check_and_insert(args.stale_seconds, args.poll_seconds, args.apply)
        except (pymysql.MySQLError, OSError, ValueError):
            LOG.exception("Sensor watchdog check failed")
        time.sleep(args.poll_seconds)

if __name__ == "__main__":
    main()
