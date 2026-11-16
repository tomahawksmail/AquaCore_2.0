"""Sensor calibration endpoints. No simulated temperature or provisional pH mode."""
import math
import os
import pymysql
import statistics
import time

from flask import Blueprint, abort, jsonify, request, session
from sensor_conversion import (
    ntc_celsius, buffer_reference_ph, calibrated_ph_from_points,
    temperature_compensated_ph_two_points,
)
from sensorstest import adc_read

bp = Blueprint("sensor_calibration", __name__, url_prefix="/api/sensors/calibration")

CALIBRATION_FIELDS = (
    "ntc_enabled,ntc_supply_v,temp_offset_c,temp_updated_at,"
    "tds_factor,temp_factor,ph686_voltage,ph401_voltage,"
    "ph686_temp_c,ph401_temp_c,ph_updated_at"
)


def _admin():
    if not session.get("user"):
        abort(401)
    if int(session.get("role", 0)) != 1:
        abort(403)


def _db():
    from app import db
    return db()


def _settings():
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT " + CALIBRATION_FIELDS + " FROM sensor_calibration WHERE id=1")
            return cur.fetchone() or {}


def _sample(channel):
    bus = int(os.getenv("TDS_I2C_BUS", "2"))
    readings = []
    for _ in range(12):
        raw, voltage = adc_read(bus, 0x48, channel)
        if raw >= 32767 or raw <= -32768 or not math.isfinite(voltage) or not 0 < voltage < 4.096:
            raise ValueError("Invalid ADS1115 voltage: check supply and wiring")
        readings.append(voltage)
        time.sleep(0.07)
    if max(readings)-min(readings) > 0.08:
        raise ValueError("Reading unstable; allow probe to settle")
    return statistics.median(readings)


def _ntc_settings(config):
    enabled = bool(int(config.get("ntc_enabled") or 0))
    supply = float(config.get("ntc_supply_v") if config.get("ntc_supply_v") is not None else 3.3)
    if not math.isfinite(supply) or not 3.0 <= supply <= 3.6:
        raise ValueError("NTC supply must be between 3.0 and 3.6 V")
    return enabled, supply


def _calibrated_ntc_temperature(voltage, config):
    enabled, supply = _ntc_settings(config)
    if not enabled or config.get("temp_updated_at") is None:
        raise ValueError("A1 NTC must be enabled and calibrated")
    raw = ntc_celsius(voltage, supply_v=supply)
    temperature = raw * float(config.get("temp_factor") if config.get("temp_factor") is not None else 1) + float(config.get("temp_offset_c") or 0)
    if not math.isfinite(temperature) or not 0 <= temperature <= 50:
        raise ValueError("A1 temperature outside supported 0-50 C range")
    return temperature


@bp.get("")
def status():
    _admin()
    response = jsonify(_settings())
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.post("/ntc-settings")
def save_ntc_settings():
    _admin()
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {"enabled", "supply_v"}:
        return jsonify(error="Expected enabled and supply_v"), 400
    if type(body["enabled"]) is not bool or isinstance(body["supply_v"], bool):
        return jsonify(error="Invalid NTC settings"), 400
    try:
        supply = float(body["supply_v"])
        if not math.isfinite(supply) or not 3.0 <= supply <= 3.6:
            raise ValueError("Supply must be between 3.0 and 3.6 V")
    except (ValueError, TypeError, OverflowError) as exc:
        return jsonify(error=str(exc)), 400
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sensor_calibration SET "
                "temp_updated_at=CASE WHEN ntc_enabled<>%s OR ntc_supply_v<>%s THEN NULL ELSE temp_updated_at END,"
                "temp_offset_c=CASE WHEN ntc_enabled<>%s OR ntc_supply_v<>%s THEN 0 ELSE temp_offset_c END,"
                "ntc_enabled=%s,ntc_supply_v=%s WHERE id=1",
                (int(body["enabled"]), supply, int(body["enabled"]), supply,
                 int(body["enabled"]), supply))
        conn.commit()
    response = jsonify(ok=True, ntc_enabled=body["enabled"], ntc_supply_v=supply)
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.post("/sample")
def sample():
    _admin()
    body = request.get_json(silent=True) or {}
    kind = body.get("kind")
    if kind not in ("temp", "ph686", "ph401"):
        return jsonify(error="Unsupported calibration buffer"), 400
    try:
        buffer_temp = None
        buffer_source = None
        reference_ph = None
        config = None
        if kind in ("ph686", "ph401"):
            buffer_source = body.get("temperature_source", "manual")
            if buffer_source == "ntc":
                # Operator must put the NTC and pH probe in the *same* buffer.
                config = _settings()
                buffer_temp = _calibrated_ntc_temperature(_sample(1), config)
            elif buffer_source == "manual":
                supplied = body.get("temperature_c")
                if supplied is None or isinstance(supplied, bool):
                    raise ValueError("Enter actual buffer liquid temperature")
                buffer_temp = float(supplied)
            else:
                raise ValueError("temperature_source must be manual or ntc")
            reference_ph = buffer_reference_ph(kind, buffer_temp)
        if kind == "temp":
            config = _settings()
            enabled, supply = _ntc_settings(config)
            if not enabled:
                raise ValueError("Enable the installed A1 NTC first")
        voltage = _sample(1 if kind == "temp" else 0)
        raw_temp = ntc_celsius(voltage, supply_v=supply) if kind == "temp" else None
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        return jsonify(error=str(exc)), 409
    session["sensor_reference_" + kind] = {
        "volts": voltage, "ts": time.time(), "temperature_c": buffer_temp,
        "temperature_source": buffer_source, "reference_ph": reference_ph,
    }
    response = jsonify(
        kind=kind, voltage=round(voltage, 5),
        temperature_c=buffer_temp, temperature_source=buffer_source,
        reference_ph=reference_ph,
        temperature_uncalibrated=round(raw_temp, 2) if raw_temp is not None else None)
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.post("/save")
def save():
    _admin()
    body = request.get_json(silent=True) or {}
    kind = body.get("kind")

    def captured(name):
        item = session.get("sensor_reference_" + name)
        if not isinstance(item, dict) or time.time() - float(item.get("ts", 0)) > 900:
            raise ValueError("Capture a stable reference within 15 minutes")
        return item, float(item["volts"])

    try:
        if kind == "temp":
            _, voltage = captured("temp")
            ref = float(body.get("reference_c"))
            if not math.isfinite(ref) or not 5 <= ref <= 40:
                raise ValueError("Reference temperature must be 5-40 C")
            settings = _settings()
            enabled, supply = _ntc_settings(settings)
            if not enabled:
                raise ValueError("A1 is disabled")
            factor = float(settings.get("temp_factor") if settings.get("temp_factor") is not None else 1)
            offset = ref - ntc_celsius(voltage, supply_v=supply) * factor
            if abs(offset) > 5:
                raise ValueError("NTC offset exceeds 5 C; check wiring")
            with _db() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE sensor_calibration SET temp_offset_c=%s,temp_updated_at=NOW() WHERE id=1", (offset,))
                conn.commit()
            session.pop("sensor_reference_temp", None)
            result = dict(ok=True, temp_offset_c=round(offset, 3))
        elif kind == "ph2":
            ref686, v686 = captured("ph686")
            ref401, v401 = captured("ph401")
            t686 = float(ref686["temperature_c"])
            t401 = float(ref401["temperature_c"])
            p686 = buffer_reference_ph("ph686", t686)
            p401 = buffer_reference_ph("ph401", t401)
            calibrated_ph_from_points(v686, p686, v686, p401, v401)
            # Only these two verified captures override the operator's supplied
            # 2.54 / 3.04 reference voltages.
            with _db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE sensor_calibration SET ph686_voltage=%s,ph401_voltage=%s,"
                        "ph686_temp_c=%s,ph401_temp_c=%s,ph_updated_at=NOW() WHERE id=1",
                        (v686, v401, t686, t401))
                conn.commit()
            session.pop("sensor_reference_ph686", None)
            session.pop("sensor_reference_ph401", None)
            result = dict(ok=True, ph686_voltage=round(v686, 5), ph401_voltage=round(v401, 5),
                          ph686_temp_c=t686, ph401_temp_c=t401)
        else:
            raise ValueError("Unsupported calibration action")
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return jsonify(error=str(exc)), 400
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.post("/factors")
def save_factors():
    _admin()
    body = request.get_json(silent=True)
    limits = {"tds_factor": (0.001, 10), "temp_factor": (0.8, 1.2)}
    if not isinstance(body, dict) or not body or not set(body).issubset(limits):
        return jsonify(error="Unsupported calibration multiplier"), 400
    try:
        values = {}
        for field, value in body.items():
            if isinstance(value, bool):
                raise ValueError("Invalid multiplier")
            number = float(value)
            if not math.isfinite(number) or not limits[field][0] <= number <= limits[field][1]:
                raise ValueError(field + " outside allowed range")
            values[field] = number
    except (ValueError, TypeError, OverflowError) as exc:
        return jsonify(error=str(exc)), 400
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE sensor_calibration SET " +
                        ",".join(field+"=%s" for field in values)+" WHERE id=1",
                        tuple(values.values()))
        conn.commit()
    response = jsonify(ok=True, **values)
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/live")
def live():
    """Read requested ADS1115 channels; A1 failure cannot hide A0 raw volts."""
    _admin()
    selected = request.args.get("channel", "all").lower()
    if selected not in ("all", "a0", "a1", "a3"):
        return jsonify(error="Invalid ADC channel"), 400
    config = {}
    config_error = None
    try:
        config = _settings()
    except pymysql.MySQLError as exc:
        config_error = str(exc)
    readings = {"a0": None, "a1": None, "a3": None}
    errors = {}
    ntc_error = None
    try:
        ntc_enabled, ntc_supply_v = _ntc_settings(config)
    except (TypeError, ValueError, OverflowError) as exc:
        ntc_enabled, ntc_supply_v = False, None
        ntc_error = str(exc)
    channels = ((0, 1, 3) if selected == "all" else
                (0, 1) if selected == "a0" and ntc_enabled else
                (1, 3) if selected == "a3" and ntc_enabled else
                (int(selected[1]),))
    bus = int(os.getenv("TDS_I2C_BUS", "2"))
    for channel in channels:
        key = "a"+str(channel)
        try:
            samples = []
            for _ in range(2):
                raw, voltage = adc_read(bus, 0x48, channel)
                if raw >= 32767 or raw <= -32768 or not math.isfinite(voltage) or not 0 <= voltage < 4.096:
                    raise ValueError("Invalid or saturated ADS1115 "+key.upper())
                samples.append(voltage)
                time.sleep(0.01)
            readings[key] = round(statistics.median(samples), 6)
        except (OSError, ValueError) as exc:
            errors[key] = str(exc)

    raw_temp, ph_temp, ph_raw = None, None, None
    temp_error = errors.get("a1")
    ph_error = errors.get("a0")
    note = ntc_error or "Calibrated A1 temperature required for pH"
    if ntc_enabled and readings["a1"] is not None:
        try:
            raw_temp = ntc_celsius(readings["a1"], supply_v=ntc_supply_v)
            if config.get("temp_updated_at") is not None:
                ph_temp = _calibrated_ntc_temperature(readings["a1"], config)
                note = "A1 calibrated; temperature-compensated two-buffer pH"
            else:
                note = "Calibrate A1 first"
        except ValueError as exc:
            temp_error = str(exc)
            note = temp_error

    if readings["a0"] is not None:
        try:
            keys = ("ph686_voltage","ph401_voltage","ph686_temp_c","ph401_temp_c")
            if ph_temp is None:
                ph_error = "Calibrated A1 temperature unavailable"
            elif not all(config.get(k) is not None for k in keys):
                ph_error = "Two-buffer pH references missing"
            else:
                ph_raw = temperature_compensated_ph_two_points(
                    readings["a0"], float(config["ph686_voltage"]), float(config["ph401_voltage"]),
                    float(config["ph686_temp_c"]), float(config["ph401_temp_c"]), ph_temp)
        except (TypeError, ValueError) as exc:
            ph_error = str(exc)
    response = jsonify(
        volts=readings, requested_channel=selected, voltage_errors=errors,
        calibration_db_error=config_error, ph_raw=ph_raw, ph_error=ph_error,
        ph_temperature_c=ph_temp, ph_temperature_compensated=ph_raw is not None,
        ph_temperature_note=note, temp_raw=raw_temp, temp_error=temp_error,
        ntc_enabled=ntc_enabled, ntc_supply_v=ntc_supply_v,
        temp_offset_c=float(config.get("temp_offset_c") or 0),
        captured_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    response.headers["Cache-Control"] = "no-store"
    return response
