"""Opt-in sensor calibration API; samples ADC without driving equipment GPIO."""
import math
import os
import statistics
import time
from datetime import datetime

from flask import Blueprint, abort, jsonify, request, session
from sensor_conversion import ntc_celsius, calibrated_ph
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
            cur.execute("SELECT temp_offset_c,ph7_voltage,ph4_voltage FROM sensor_calibration WHERE id=1")
            row = cur.fetchone()
    resp = jsonify(row or {})
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.post("/sample")
def sample():
    _admin()
    body = request.get_json(silent=True) or {}
    kind = body.get("kind")
    if kind not in ("temp", "ph7", "ph4"):
        return jsonify(error="Invalid reference"), 400
    try:
        volts = _sample(1 if kind == "temp" else 0)
        base = (ntc_celsius(volts, supply_v=float(os.getenv("NTC_SUPPLY_V", "3.3")))
                if kind == "temp" else None)
    except (OSError, ValueError) as exc:
        return jsonify(error=str(exc)), 409
    session["sensor_reference_" + kind] = {"volts": volts, "ts": time.time()}
    resp = jsonify(kind=kind, voltage=round(volts, 5),
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
