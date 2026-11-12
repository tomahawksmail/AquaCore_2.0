"""Opt-in sensor calibration API; samples ADC without driving equipment GPIO."""
import math
import os
import statistics
import time
from datetime import datetime

from flask import Blueprint, abort, jsonify, request, session
from sensor_conversion import (ntc_celsius, calibrated_ph, calibrated_ph_three_points,
                               validate_ph_three_points, buffer_reference_ph)
from sensorstest import estimate_tds_ppm
from sensorstest import adc_read

bp = Blueprint("sensor_calibration", __name__, url_prefix="/api/sensors/calibration")


def _admin():
    if not session.get("user"):
        abort(401)
    if int(session.get("role", 0)) != 1:
        abort(403)


def _db():
    from app import db
    return db()


def _sample(channel):
    bus = int(os.getenv("TDS_I2C_BUS", "2"))
    vals = []
    for _ in range(12):
        raw, volts = adc_read(bus, 0x48, channel)
        if raw == 32767:
            raise ValueError("ADC saturated: check safe voltage/wiring")
        if not 0 < volts < 4.096:
            raise ValueError("Invalid ADC voltage")
        vals.append(volts)
        time.sleep(0.07)
    if max(vals) - min(vals) > 0.08:
        raise ValueError("Reading unstable; allow probe to settle and try again")
    return statistics.median(vals)


@bp.get("")
def status():
    _admin()
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT temp_offset_c,ph7_voltage,ph4_voltage,tds_factor,ph_factor,temp_factor, "
                        "ph401_voltage,ph686_voltage,ph918_voltage, "
                        "ph401_reference,ph686_reference,ph918_reference, "
                        "ph401_temp_c,ph686_temp_c,ph918_temp_c "
                        "FROM sensor_calibration WHERE id=1")
            row = cur.fetchone()
    resp = jsonify(row or {})
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.post("/sample")
def sample():
    _admin()
    body = request.get_json(silent=True) or {}
    kind = body.get("kind")
    if kind not in ("temp", "ph7", "ph4", "ph401", "ph686", "ph918"):
        return jsonify(error="Invalid reference"), 400
    try:
        temperature = None
        reference_ph = None
        if kind in ("ph401", "ph686", "ph918"):
            raw_temp = body.get("temperature_c")
            if isinstance(raw_temp, bool) or raw_temp is None:
                raise ValueError("Enter measured liquid temperature before capturing a buffer")
            temperature = float(raw_temp)
            if not math.isfinite(temperature):
                raise ValueError("Invalid liquid temperature")
            reference_ph = buffer_reference_ph(kind, temperature)
        volts = _sample(1 if kind == "temp" else 0)
        base = (ntc_celsius(volts, supply_v=float(os.getenv("NTC_SUPPLY_V", "3.3")))
                if kind == "temp" else None)
    except (OSError, ValueError, TypeError) as exc:
        return jsonify(error=str(exc)), 409
    session["sensor_reference_" + kind] = {
        "volts": volts, "ts": time.time(),
        "temperature_c": temperature, "reference_ph": reference_ph,
    }
    resp = jsonify(kind=kind, voltage=round(volts, 5),
                   temperature_c=temperature, reference_ph=reference_ph,
                   temperature_uncalibrated=round(base, 2) if base is not None else None)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.post("/save")
def save():
    _admin()
    body = request.get_json(silent=True) or {}
    kind = body.get("kind")

    def previous(name):
        value = session.get("sensor_reference_" + name)
        if not isinstance(value, dict) or time.time() - float(value.get("ts", 0)) > 900:
            raise ValueError("Capture a fresh reference reading first (within 15 minutes)")
        return float(value["volts"])

    try:
        if kind == "temp":
            volts = previous("temp")
            reference = float(body.get("reference_c"))
            if not math.isfinite(reference) or not 5 <= reference <= 40:
                raise ValueError("Temperature reference must be between 5 and 40 °C")
            offset = reference - ntc_celsius(volts, supply_v=float(os.getenv("NTC_SUPPLY_V", "3.3")))
            if abs(offset) > 5:
                raise ValueError("Temperature offset exceeds 5 °C; check NTC probe and resistor")
            with _db() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE sensor_calibration SET temp_offset_c=%s,temp_updated_at=NOW() WHERE id=1",
                                (offset,))
                conn.commit()
            session.pop("sensor_reference_temp", None)
            result = {"ok": True, "temp_offset_c": round(offset, 3)}
        elif kind == "ph3":
            if body.get("confirmed_buffers") is not True:
                raise ValueError("Confirm the three correctly prepared 4.01, 6.86 and 9.18 buffers")
            captures = []
            for name in ("ph401", "ph686", "ph918"):
                record = session.get("sensor_reference_" + name)
                if not isinstance(record, dict):
                    raise ValueError("Capture all three buffers before saving")
                voltage = previous(name)
                temperature = float(record["temperature_c"])
                ref = buffer_reference_ph(name, temperature)
                captures.append((voltage, ref, temperature))
            (v401, p401, t401), (v686, p686, t686), (v918, p918, t918) = captures
            validate_ph_three_points(v401, v686, v918, p401, p686, p918)
            with _db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE sensor_calibration SET "
                        "ph401_voltage=%s,ph686_voltage=%s,ph918_voltage=%s, "
                        "ph401_reference=%s,ph686_reference=%s,ph918_reference=%s, "
                        "ph401_temp_c=%s,ph686_temp_c=%s,ph918_temp_c=%s, "
                        "ph_factor=1.0,ph_updated_at=NOW() WHERE id=1",
                        (v401,v686,v918,p401,p686,p918,t401,t686,t918))
                    if cur.rowcount != 1:
                        raise ValueError("Missing sensor_calibration id=1 row")
                conn.commit()
            for name in ("ph401", "ph686", "ph918"):
                session.pop("sensor_reference_" + name, None)
            result = {"ok": True, "ph401_voltage": round(v401, 5),
                      "ph686_voltage": round(v686, 5),
                      "ph918_voltage": round(v918, 5),
                      "references": {"ph401": round(p401, 4),
                                     "ph686": round(p686, 4),
                                     "ph918": round(p918, 4)}}
        elif kind == "ph":
            if body.get("confirmed_buffers") is not True:
                raise ValueError("Confirm certified pH 7.00 and pH 4.00 buffer solutions")
            v7, v4 = previous("ph7"), previous("ph4")
            calibrated_ph(v7, v7, v4)  # validates distinct voltages
            with _db() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE sensor_calibration SET ph7_voltage=%s,ph4_voltage=%s,"
                                "ph_updated_at=NOW() WHERE id=1", (v7, v4))
                conn.commit()
            session.pop("sensor_reference_ph7", None)
            session.pop("sensor_reference_ph4", None)
            result = {"ok": True, "ph7_voltage": round(v7, 5), "ph4_voltage": round(v4, 5)}
        else:
            raise ValueError("Unknown calibration kind")
    except (ValueError, TypeError, OverflowError) as exc:
        return jsonify(error=str(exc)), 400
    resp = jsonify(result)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.post("/factors")
def save_factors():
    """Save bounded, finite calibration multipliers for the sensor collector."""
    _admin()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="Expected JSON object"), 400
    limits = {"tds_factor": (0.001, 10.0),
              "ph_factor": (0.5, 1.5),
              "temp_factor": (0.8, 1.2)}
    if not body or not set(body).issubset(limits):
        return jsonify(error="Provide one or more supported calibration multipliers"), 400
    values = {}
    try:
        for field in body:
            low, high = limits[field]
            if isinstance(body[field], bool):
                raise ValueError(field + " must be a number")
            value = float(body[field])
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{field} must be between {low} and {high}")
            values[field] = value
    except (ValueError, TypeError, OverflowError) as exc:
        return jsonify(error=str(exc)), 400
    with _db() as conn:
        with conn.cursor() as cur:
            fields = tuple(values)
            sql = "UPDATE sensor_calibration SET " + ", ".join(
                field + "=%s" for field in fields) + " WHERE id=1"
            cur.execute(sql, tuple(values[field] for field in fields))
        conn.commit()
    result = jsonify(ok=True, **values)
    result.headers["Cache-Control"] = "no-store"
    return result


@bp.get("/live")
def live():
    """Read-only ADC snapshot for browser preview; never touches relays or DB writes."""
    _admin()
    try:
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT temp_offset_c,ph7_voltage,ph4_voltage,"
                            "tds_factor,ph_factor,temp_factor,"
                            "ph401_voltage,ph686_voltage,ph918_voltage,"
                            "ph401_reference,ph686_reference,ph918_reference "
                            "FROM sensor_calibration WHERE id=1")
                config = cur.fetchone() or {}
        # The installed web service user needs read access to /dev/i2c-2.
        # Use the same ADS1115 PGA as the collector (currently +/-4.096 V).
        readings = {}
        bus = int(os.getenv("TDS_I2C_BUS", "2"))
        for channel in (0, 1, 3):
            values = []
            for _ in range(2):  # keep 3-channel live refresh below 500 ms
                raw, volts = adc_read(bus, 0x48, channel)
                if raw >= 32767:
                    raise ValueError(f"ADS1115 A{channel} saturated")
                values.append(volts)
                time.sleep(0.010)
            readings[f"a{channel}"] = round(statistics.median(values), 6)
        enabled_ntc = os.getenv("NTC_ENABLED", "").lower() in ("1", "true", "yes")
        raw_temp = None
        temp_error = None
        if enabled_ntc:
            try:
                raw_temp = ntc_celsius(readings["a1"], supply_v=float(
                    os.getenv("NTC_SUPPLY_V", "3.3")))
            except ValueError as exc:
                temp_error = str(exc)
        v7, v4 = config.get("ph7_voltage"), config.get("ph4_voltage")
        raw_ph = None
        ph_error = None
        new_keys = ("ph401_voltage","ph686_voltage","ph918_voltage",
                    "ph401_reference","ph686_reference","ph918_reference")
        try:
            if all(config.get(key) is not None for key in new_keys):
                raw_ph = calibrated_ph_three_points(
                    readings["a0"], *(float(config[key]) for key in new_keys))
            elif v7 is not None and v4 is not None:
                raw_ph = calibrated_ph(readings["a0"], float(v7), float(v4))
        except ValueError as exc:
            ph_error = str(exc)
        response = jsonify(
            volts=readings,
            ph_raw=raw_ph,
            ph_error=ph_error,
            temp_raw=raw_temp,
            temp_error=temp_error,
            ntc_enabled=enabled_ntc,
            temp_offset_c=float(config.get("temp_offset_c") or 0),
            fallback_temperature_c=float(os.getenv("TDS_WATER_TEMP_C", "22")),
            tds_voltage=readings["a3"],
            captured_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        response.headers["Cache-Control"] = "no-store"
        return response
    except (OSError, ValueError) as exc:
        return jsonify(error=f"Sensor read failed: {exc}"), 503
