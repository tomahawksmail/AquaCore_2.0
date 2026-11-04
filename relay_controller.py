#!/usr/bin/env python3
"""AquaCore Orange Pi: apply database-requested equipment states to relays.

Run scheduler.py separately. This worker NEVER changes MariaDB status.
Default mode is DRY RUN; pass --apply after testing pin assignments.
"""
import argparse
import logging
import os
import signal
import threading
from datetime import datetime
import gpiod
from gpiod.line import Direction, Value
import time

import pymysql
from pymysql.cursors import DictCursor
from dotenv import load_dotenv
from fertilizer_math import calibrated_seconds

LOG = logging.getLogger("aquacore.relay")
RUNNING = True

# Orange Pi Zero 2W relay layout, by physical relay channel:
# CO2=PH4(228); Oxygen=PI6(262); Main Light=PH5(229);
# Backlight=PI16(272); Plant Light=PC12(76); UV=PI0(256);
# CPU cooler=PH8(232); fertilizer pump=PH9(233).
# Unassigned: PH6(230), PH7(231).
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
    "spare_ph6": (23, 230),  # PH6 / physical 23
    "spare_ph7": (19, 231),  # PH7 / physical 19
}

COOLER_PIN = (21, 232)  # PH8 / physical pin 21
PUMP_PIN = (26, 233)    # PH9 / physical pin 26; active-low
PUMP_MAX_SECONDS = 60
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
    all_pins = [physical for physical, _ in (*PIN_MAP.values(), *SPARE_PIN_MAP.values(), COOLER_PIN, PUMP_PIN)]
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
    line_ids=[number for _,number in pins.values()] + [COOLER_PIN[1], PUMP_PIN[1]]
    settings=gpiod.LineSettings(direction=Direction.OUTPUT,output_value=Value.ACTIVE)
    # No active_low flag: ACTIVE means physical HIGH; on the relay module HIGH = OFF.
    request=gpiod.request_lines("/dev/gpiochip1",consumer="aquacore-relays",
                               config={tuple(line_ids):settings})
    return request


def setup_pins(pins, apply):
    for field,(physical,pin) in pins.items():
        LOG.info("%s => physical pin %s / chip1 offset %s",field,physical,pin)
    LOG.info("CPU cooler => physical pin %s / chip1 offset %s", *COOLER_PIN)
    LOG.info("Fertilizer pump => physical pin %s / chip1 offset %s", *PUMP_PIN)
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


class FertilizerPump:
    """At-most-once manual and scheduled pulses, with bounded GPIO runtime.

    Progress records describe GPIO commands, not measured liquid movement.
    The OFF timer runs independently of database and UI polling.
    """
    def __init__(self, request, apply):
        self.request = request
        self.apply = apply
        self.lock = threading.Lock()
        self.timer = None
        self.active = False
        self.pulse_request_id = None
        self.generation = 0  # invalidate callbacks from an older pump pulse
        if apply:
            # The freshly claimed line is initialized HIGH/OFF. A previous
            # interrupted run must never display as still running.
            with database() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE fertilizer_pump SET pulse_state='interrupted',"
                        "pulse_finished_at=NOW(3) WHERE id=1 AND pulse_state='running'"
                    )

    def record_pulse_end(self, request_id, status):
        if request_id is None or not self.apply:
            return
        with database() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE fertilizer_pump SET pulse_state=%s,"
                    "pulse_finished_at=NOW(3) "
                    "WHERE id=1 AND pulse_request_id=%s "
                    "AND pulse_state IN ('running','stop_requested')",
                    (status, request_id)
                )

    def off(self, completed=True, status=None, expected_generation=None):
        """Switch OFF; an old timer can never stop a newer pump run."""
        request_id = None
        state = status or ("completed" if completed else "interrupted")
        with self.lock:
            if expected_generation is not None and expected_generation != self.generation:
                return
            self.generation += 1
            if self.timer is not None:
                self.timer.cancel()
                self.timer = None
            on_before = self.active
            request_id = self.pulse_request_id
            try:
                if self.apply and self.request is not None:
                    self.request.set_value(PUMP_PIN[1], Value.ACTIVE)  # HIGH=OFF
            except OSError:
                LOG.exception("Fertilizer GPIO OFF failed")
                state = "failed"
            finally:
                self.active = False
                self.pulse_request_id = None
            if on_before:
                LOG.info("Fertilizer pump OFF (%s)",state)
        if request_id is not None:
            try:
                self.record_pulse_end(request_id,state)
            except pymysql.MySQLError:
                LOG.exception("Unable to record pump stop: physical OFF was attempted")

    def close(self):
        with self.lock:
            if self.timer is not None:
                self.timer.cancel()
                self.timer = None
        self.off(completed=False)

    def activate(self, duration, source, request_id=None):
        """Start one GPIO pulse after recording the relay worker's start."""
        if not self.apply:
            return
        if not 0.25 <= float(duration) <= PUMP_MAX_SECONDS:
            raise ValueError("Unsafe fertilizer pulse duration")
        if request_id is not None:
            with database() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE fertilizer_pump SET pulse_state='running',"
                        "pulse_started_at=NOW(3),pulse_finished_at=NULL,"
                        "pulse_duration_seconds=%s WHERE id=1 AND pulse_request_id=%s "
                        "AND manual_processed_id=%s AND pulse_state='queued'",
                        (duration,request_id,request_id)
                    )
                    if cursor.rowcount != 1:
                        LOG.warning("Fertilizer pulse %s is not in queued state",request_id)
                        return
        try:
            with self.lock:
                if self.active:
                    raise RuntimeError("Fertilizer pulse already active")
                self.request.set_value(PUMP_PIN[1], Value.INACTIVE)  # LOW=ON
                self.active = True
                self.pulse_request_id = request_id
                self.generation += 1
                timer = threading.Timer(
                    duration, self.off, kwargs={"expected_generation": self.generation}
                )
                timer.daemon = True
                self.timer = timer
                timer.start()
        except Exception:
            with self.lock:
                self.active = False
                self.pulse_request_id = None
                if self.timer is not None:
                    self.timer.cancel()
                    self.timer = None
                try:
                    self.request.set_value(PUMP_PIN[1], Value.ACTIVE)  # best-effort OFF
                except OSError:
                    LOG.exception("Unable to deactivate fertilizer relay after start error")
            if request_id is not None:
                try:
                    self.record_pulse_end(request_id,"failed")
                except pymysql.MySQLError:
                    LOG.exception("Unable to record failed fertilizer activation")
            raise
        LOG.info("Fertilizer pump ON for %.2f seconds (%s)",float(duration),source)

    def poll_manual(self):
        """At-most-once manual request; reject stale requests after restart."""
        with database() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT manual_request_id,manual_processed_id,manual_requested_at,"
                    "manual_duration_seconds,manual_kind,pulse_state,NOW() AS db_now "
                    "FROM fertilizer_pump WHERE id=1"
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("Missing fertilizer_pump row")
                request_id = int(row["manual_request_id"])
                if request_id <= int(row["manual_processed_id"]):
                    return False
                age = ((row["db_now"]-row["manual_requested_at"]).total_seconds()
                       if row["manual_requested_at"] else 9999)
                duration = float(row["manual_duration_seconds"])
                kind = row["manual_kind"]
                if row["pulse_state"] == "stop_requested":
                    if self.apply:
                        cursor.execute(
                            "UPDATE fertilizer_pump SET manual_processed_id=%s,"
                            "pulse_state='stopped',pulse_finished_at=NOW(3) "
                            "WHERE id=1 AND manual_request_id=%s "
                            "AND pulse_state='stop_requested'",
                            (request_id, request_id)
                        )
                    LOG.info("Manual pump request %s canceled before GPIO ON", request_id)
                    return True
                if not self.apply:
                    LOG.info("DRY RUN: pending %s fertilizer pulse %.2fs (age %.1fs)",
                             kind,duration,age)
                    return True
                # Claim before physical activation to prevent accidental re-doses.
                cursor.execute(
                    "UPDATE fertilizer_pump SET manual_processed_id=%s "
                    "WHERE id=1 AND manual_request_id=%s AND manual_processed_id<%s",
                    (request_id,request_id,request_id)
                )
                if cursor.rowcount != 1:
                    return False
        if (not 0 <= age <= 15 or not 0.25 <= duration <= PUMP_MAX_SECONDS
                or kind not in ("dose","calibration","manual")):
            LOG.warning("Skipped stale/invalid fertilizer request %s (age %.1fs)",
                        request_id,age)
            with database() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE fertilizer_pump SET pulse_state='skipped',"
                        "pulse_finished_at=NOW(3) WHERE id=1 AND pulse_request_id=%s "
                        "AND pulse_state='queued'",
                        (request_id,)
                    )
            return True
        self.activate(duration,kind,request_id)
        return True

    def poll_stop(self):
        """Honor OFF within the normal 1s worker cycle; no web GPIO access."""
        if not self.apply:
            return False
        with database() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pulse_request_id,pulse_kind,pulse_state "
                    "FROM fertilizer_pump WHERE id=1"
                )
                row = cursor.fetchone()
                if not row or row["pulse_kind"] != "manual" or row["pulse_state"] != "stop_requested":
                    return False
                request_id = int(row["pulse_request_id"])
        if self.active and self.pulse_request_id == request_id:
            self.off(status="stopped")
        elif not self.active:
            # This covers an OFF request arriving after DB claim but before GPIO ON.
            with database() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE fertilizer_pump SET manual_processed_id=GREATEST("
                        "manual_processed_id,%s),pulse_state='stopped',"
                        "pulse_finished_at=NOW(3) WHERE id=1 "
                        "AND pulse_request_id=%s AND pulse_state='stop_requested'",
                        (request_id,request_id)
                    )
        return True

    def poll(self):
        if self.poll_stop():
            return
        if self.active:
            return
        if self.poll_manual():
            return
        # Only accept a dose in the first ten seconds of its scheduled minute.
        # Never catch up a missed dose after a restart or clock change.
        with database() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT start_time,dose_ml,ml_per_second,last_run_date,"
                    "NOW() AS db_now FROM fertilizer_pump WHERE id=1"
                )
                config = cursor.fetchone()
                if not config:
                    raise RuntimeError("Missing fertilizer_pump id=1; run SQL migration")
                now = config["db_now"]
                duration = calibrated_seconds(config["dose_ml"],config["ml_per_second"])
                start = config["start_time"]
                if isinstance(start, str):
                    hour, minute = map(int, start.split(":")[:2])
                else:
                    hour = start.seconds // 3600
                    minute = (start.seconds // 60) % 60
                if duration is None:
                    return
                if (now.hour != hour or now.minute != minute or
                        now.second >= 10 or config["last_run_date"] == now.date()):
                    return
                if not self.apply:
                    LOG.info("DRY RUN: would dose fertilizer for %.2f seconds",duration)
                    return
                cursor.execute(
                    "UPDATE fertilizer_pump SET last_run_date=CURDATE() "
                    "WHERE id=1 AND (last_run_date IS NULL OR last_run_date<CURDATE()) "
                    "AND dose_ml=%s AND ml_per_second=%s AND start_time=%s",
                    (config["dose_ml"],config["ml_per_second"],start)
                )
                if cursor.rowcount != 1:
                    return
        LOG.info("Fertilizer scheduled dose claimed: %.2f seconds",duration)
        self.activate(duration,"scheduled")


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
    pump = FertilizerPump(request, args.apply)
    try:
      while RUNNING:
        try:
            pump.poll()
        except (pymysql.MySQLError,OSError,RuntimeError,ValueError,KeyError):
            LOG.exception('Fertilizer pump scheduling failed')
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
        pump.close()
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
