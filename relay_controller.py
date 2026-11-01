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

# Orange Pi Zero 2W relay layout, by physical relay channel:
# 1 CO2=PH4; 2 Oxygen=PI6; 3 Main Light=PH9; 4 unused=PH5;
# 5 Backlight=PI16; 6 Plant Light=PC12; 7 UV=PI0.
# Each pair is (PHYSICAL_HEADER_PIN, SUNXI_GPIO_NUMBER).
# NOTE: Current driver uses wiringOP 'gpio -g'; not libgpiod.
PIN_MAP = {
    "co2_status": (18, 228),         # 1 PH4
    "o2_status": (22, 262),          # 2 PI6
    "MasterL_status": (26, 233),     # 3 PH9
    "Backlight_status": (37, 272),   # 5 PI16
    "PlantL_status": (36, 76),       # 6 PC12
    "UV_status": (29, 256),          # 7 PI0 (moved from PH5)
}

# Unused relay channels: kept unconfigured/uncontrolled.
SPARE_PIN_MAP = {
    "spare_4": (24, 229),  # 4 PH5 — intentionally skipped
    "spare_8": (23, 230),  # 8 PH6 / SPI clock
    "spare_9": (21, 232),  # 9 PH8 / SPI MISO
    "spare_10": (19, 231), # 10 PH7 / SPI MOSI
}

def load_config():
    load_dotenv(os.getenv("AQUACORE_ENV", "/home/orangepi/AquaCore/.env"))
    all_pins = [physical for physical, _ in (*PIN_MAP.values(), *SPARE_PIN_MAP.values())]
    if len(set(all_pins)) != len(all_pins):
        raise ValueError('Duplicate physical header pins across relay modules')
    return dict(PIN_MAP)

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
    subprocess.run(["gpio", "-g", *map(str,args)], check=True,
                   timeout=3, stdout=subprocess.DEVNULL)

def setup_pins(pins, apply):
    for field, (physical, pin) in pins.items():
        if apply:
            gpio("mode", pin, "out")
        LOG.info("%s => physical pin %s (SoC GPIO %s)", field, physical, pin)

def apply_states(rows, pins, previous, apply):
    for field, (physical, pin) in pins.items():
        state = rows[field]
        if state not in ("checked", "unchecked"):
            LOG.warning("Skipping invalid/NULL %s=%r", field, state)
            continue
        if previous.get(field) == state:
            continue
        # Existing board: 'down' energizes relay, 'up' de-energizes it.
        level = 0 if state == "checked" else 1
        if apply:
            gpio("write", pin, level)
        LOG.info("%s -> %s on physical %s / SoC GPIO %s (%s)", field, state, physical, pin,
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
