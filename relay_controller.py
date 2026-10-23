#!/usr/bin/env python3
"""AquaCore Orange Pi: apply database-requested equipment states to relays.

Run scheduler.py separately. This worker NEVER changes MariaDB status.
Default mode is DRY RUN; pass --apply after testing pin assignments.
"""
import argparse
import logging
import os
import signal
import subprocess
import time

import pymysql
from pymysql.cursors import DictCursor
from dotenv import load_dotenv

LOG = logging.getLogger("aquacore.relay")
RUNNING = True

# Verified from the user's previous R2 relay wiring. GPIO numbering must match
# the installed 'gpio' utility (not Linux gpiochip line offsets).
KNOWN_PINS = {
    "co2_status": 19,
    "o2_status": 14,
    "UV_status": 12,
}
# MasterL_status, Backlight_status, PlantL_status intentionally UNMAPPED until
# their physical relay pins are confirmed. Heater is deliberately excluded.
ALLOWED_FIELDS = tuple(KNOWN_PINS) + (
    "MasterL_status", "Backlight_status", "PlantL_status"
)

def load_config():
    load_dotenv(os.getenv("AQUACORE_ENV", "/home/orangepi/AquaCore/.env"))
    pins = dict(KNOWN_PINS)
    for field, var in (
        ("MasterL_status", "AQUACORE_GPIO_MAINLIGHT"),
        ("Backlight_status", "AQUACORE_GPIO_BACKLIGHT"),
        ("PlantL_status", "AQUACORE_GPIO_PLANTLIGHT"),
    ):
        if os.getenv(var):
            pins[field] = int(os.environ[var])
    if len(set(pins.values())) != len(pins):
        raise ValueError("GPIO pins must be unique")
    if any(pin < 0 for pin in pins.values()):
        raise ValueError("GPIO pin numbers must be nonnegative")
    return pins

def database():
    config = {
        "host": os.getenv("DB_HOST") or os.getenv("HOST"),
        "user": os.getenv("DB_USER") or os.getenv("USER"),
        "password": os.getenv("DB_PASSWORD") or os.getenv("PASSWORD"),
        "database": os.getenv("DB_NAME") or os.getenv("DATABASE"),
        "connect_timeout": 4,
        "read_timeout": 4,
        "write_timeout": 4,
        "cursorclass": DictCursor,
        "autocommit": True,
    }
    if not config["database"] or not config["user"]:
        raise RuntimeError("Database credentials not configured")
    return pymysql.connect(**config)

def get_status(pins):
    fields = ", ".join("`" + name + "`" for name in pins)
    with database() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT " + fields + " FROM `status`")
            rows = cursor.fetchall()
    if len(rows) != 1:
        raise RuntimeError("Expected exactly one status row; got " + str(len(rows)))
    return rows[0]

def gpio(*args):
    subprocess.run(["gpio", *map(str,args)], check=True,
                   timeout=3, stdout=subprocess.DEVNULL)

def setup_pins(pins, apply):
    for field, pin in pins.items():
        if apply:
            gpio("mode", pin, "out")
        LOG.info("%s mapped to GPIO %s", field, pin)

def apply_states(rows, pins, previous, apply):
    for field, pin in pins.items():
        state = rows[field]
        if state not in ("checked", "unchecked"):
            LOG.warning("Skipping invalid/NULL %s=%r", field, state)
            continue
        if previous.get(field) == state:
            continue
        # Existing board: 'down' energizes relay, 'up' de-energizes it.
        level = "down" if state == "checked" else "up"
        if apply:
            gpio("write", pin, level)
        LOG.info("%s -> %s on GPIO %s (%s)", field, state, pin,
                 "APPLIED" if apply else "DRY RUN")
        previous[field] = state

def stop(_signum, _frame):
    global RUNNING
    RUNNING = False

def main():
    parser = argparse.ArgumentParser(description="AquaCore GPIO relay worker")
    parser.add_argument("--apply", action="store_true",
                        help="Actually write GPIO; default is dry-run")
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    if args.interval < 0.2:
        parser.error("interval must be at least 0.2 seconds")
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    pins = load_config()
    if not args.apply:
        LOG.warning("DRY RUN: no GPIO changes will be made")
    else:
        LOG.warning("LIVE MODE: verify pin wiring and relay polarity first")
    # Do not switch relays to a guess at startup; wait for a valid DB read.
    # In particular, don't write OFF on transient DB failures.
    previous = {}
    setup_pins(pins, args.apply)
    while RUNNING:
        try:
            rows = get_status(pins)
            apply_states(rows, pins, previous, args.apply)
        except (pymysql.MySQLError, OSError, subprocess.SubprocessError,
                RuntimeError, ValueError, KeyError):
            LOG.exception("Relay cycle failed; retaining last GPIO outputs")
            # A failed write must be retried; previous only records successes.
        time.sleep(args.interval)

if __name__ == "__main__":
    main()
