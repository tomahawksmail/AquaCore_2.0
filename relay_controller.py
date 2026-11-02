#!/usr/bin/env python3
"""AquaCore Orange Pi: apply database-requested equipment states to relays.

Run scheduler.py separately. This worker NEVER changes MariaDB status.
Default mode is DRY RUN; pass --apply after testing pin assignments.
"""
import argparse
import logging
import os
import signal
import gpiod
from gpiod.line import Direction, Value
import time

import pymysql
from pymysql.cursors import DictCursor
from dotenv import load_dotenv

LOG = logging.getLogger("aquacore.relay")
RUNNING = True

# Orange Pi Zero 2W relay layout, by physical relay channel:
# CO2=PH4(228); Oxygen=PI6(262); Main Light=PH5(229);
# Backlight=PI16(272); Plant Light=PC12(76); UV=PI0(256);
# CPU cooler=PH8(232). Unassigned: PH9(233), PH6(230), PH7(231).
# Each pair is (PHYSICAL_HEADER_PIN, SUNXI_GPIO_NUMBER).
# Controlled using libgpiod v2 on gpiochip1.
PIN_MAP = {
    "co2_status": (18, 228),         # 1 PH4
    "o2_status": (22, 262),          # 2 PI6
    "MasterL_status": (24, 229),     # PH5
    "Backlight_status": (37, 272),   # 5 PI16
    "PlantL_status": (36, 76),       # 6 PC12
    "UV_status": (29, 256),          # 7 PI0 (moved from PH5)
}

# Unused relay channels: kept unconfigured/uncontrolled.
SPARE_PIN_MAP = {
    "spare_ph9": (26, 233),  # PH9 / physical 26
    "spare_ph6": (23, 230),  # PH6 / physical 23
    "spare_ph7": (19, 231),  # PH7 / physical 19
}

COOLER_PIN = (21, 232)  # PH8 / physical pin 21
CPU_TEMP_PATH = "/sys/class/thermal/thermal_zone0/temp"
COOLER_ON_C = 70.0
COOLER_OFF_C = 65.0


def cpu_temperature_c(path=CPU_TEMP_PATH):
    """Read CPU temperature in degrees C; reject missing/implausible readings."""
    with open(path, "r", encoding="ascii") as file:
        raw = file.read().strip()
    temperature = float(raw) / 1000.0
    if not -20 <= temperature <= 130:
        raise ValueError("CPU temperature out of range: " + str(temperature))
    return temperature


def desired_cooler_on(temperature, previous_on):
    """Hysteresis: switch on strictly above 70C; off at or below 65C."""
    if temperature > COOLER_ON_C:
        return True
    if temperature <= COOLER_OFF_C:
        return False
    return previous_on


def update_cooler(request, previous_on, apply):
    try:
        temperature = cpu_temperature_c()
        on = desired_cooler_on(temperature, previous_on)
        description = f"{temperature:.1f}C"
    except (OSError, ValueError) as exc:
        # Cooling is fail-on if the CPU temperature cannot be read.
        on = True
        description = f"temperature unavailable ({exc}); fail-on"
    if previous_on is None or on != previous_on:
        if apply:
            if request is None:
                raise RuntimeError("GPIO request unavailable")
            request.set_value(COOLER_PIN[1], Value.INACTIVE if on else Value.ACTIVE)
        LOG.info("CPU cooler %s at %s (%s)", "ON" if on else "OFF", description,
                 "APPLIED" if apply else "DRY RUN")
    return on


def load_config():
    load_dotenv(os.getenv("AQUACORE_ENV", "/home/orangepi/AquaCore/.env"))
    all_pins = [physical for physical, _ in (*PIN_MAP.values(), *SPARE_PIN_MAP.values(), COOLER_PIN)]
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

def request_relay_lines(pins):
    """Claim aquarium and cooler GPIO lines in one persistent request."""
    line_ids=[number for _,number in pins.values()] + [COOLER_PIN[1]]
    settings=gpiod.LineSettings(direction=Direction.OUTPUT,output_value=Value.ACTIVE)
    # No active_low flag: ACTIVE means physical HIGH; on the relay module HIGH = OFF.
    request=gpiod.request_lines("/dev/gpiochip1",consumer="aquacore-relays",
                               config={tuple(line_ids):settings})
    return request


def setup_pins(pins, apply):
    for field,(physical,pin) in pins.items():
        LOG.info("%s => physical pin %s / chip1 offset %s",field,physical,pin)
    LOG.info("CPU cooler => physical pin %s / chip1 offset %s", *COOLER_PIN)
    return request_relay_lines(pins) if apply else None


def apply_states(rows,pins,previous,apply,request=None):
    for field,(physical,pin) in pins.items():
        state=rows[field]
        if state not in ("checked","unchecked"):
            LOG.warning("Ignoring invalid state %s=%r",field,state)
            continue
        if previous.get(field)==state:
            continue
        # Active-low relay input: LOW energizes; HIGH de-energizes.
        level=Value.INACTIVE if state=="checked" else Value.ACTIVE
        if apply:
            if request is None:
                raise RuntimeError("GPIO request unavailable")
            request.set_value(pin,level)
        LOG.info("%s -> %s, pin %s / line %s (%s)",field,state,physical,pin,
                 "APPLIED" if apply else "DRY RUN")
        previous[field]=state


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
    request=setup_pins(pins,args.apply)
    cooler_on = None
    try:
      while RUNNING:
        try:
            cooler_on = update_cooler(request, cooler_on, args.apply)
        except (OSError, RuntimeError, ValueError):
            LOG.exception("Cooler update failed")
        try:
            rows=get_status(pins)
            apply_states(rows,pins,previous,args.apply,request)
        except (pymysql.MySQLError,OSError,RuntimeError,ValueError,KeyError):
            LOG.exception("Relay cycle failed; retaining previous output")
        time.sleep(args.interval)
    finally:
        if request is not None:
            # Before releasing, ask for OFF. Released line levels still are not
            # guaranteed by the kernel; use external hardware failsafes.
            for _field,(_physical,pin) in pins.items():
                try:request.set_value(pin,Value.ACTIVE)
                except OSError:LOG.exception("Unable to de-energize line %s",pin)
            try:
                request.set_value(COOLER_PIN[1], Value.INACTIVE)  # request cooling on shutdown
            except OSError:
                LOG.exception("Unable to energize CPU cooler on shutdown")
            request.release()

if __name__ == "__main__":
    main()
