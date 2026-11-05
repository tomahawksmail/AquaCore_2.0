"""Second dosing pump API; queues requests for the relay worker, never drives GPIO."""
import os
from functools import wraps
from flask import Blueprint, request, session, abort, jsonify
from fertilizer_math import calibrated_seconds, calibrate_rate

bp = Blueprint("fertilizer2", __name__, url_prefix="/api/fertilizer/2")

def _logged_in(fn):
    @wraps(fn)
    def check(*args, **kwargs):
        if not session.get("user"):
            abort(401)
        return fn(*args, **kwargs)
    return check

def db():
    from app import db as app_db
    return app_db()

def query(sql, params=(), one=False):
    from app import query as app_query
    return app_query(sql, params, one)

def mutate(sql, params):
    from app import mutate as app_mutate
    return app_mutate(sql, params)

@bp.post('/schedule/days')
@_logged_in
def save_fertilizer_schedule_days():
    """Weekday schedule: 0=Monday, 6=Sunday."""
    if int(session.get('role', 0)) != 1:
        abort(403)
    payload = request.get_json(silent=True)
    days = payload.get('days') if isinstance(payload, dict) else None
    if not isinstance(days, list) or len(days) > 7 or any(
            type(day) is not int or not 0 <= day <= 6 for day in days
    ) or len(set(days)) != len(days):
        return jsonify(error="Use unique weekday numbers 0 through 6"), 400
    mask = sum(1 << day for day in days)
    mutate("UPDATE fertilizer_pump2 SET fertilizer_weekdays=%s LIMIT 1", (mask,))
    response = jsonify(ok=True, times_per_week=len(days), days=days)
    response.headers["Cache-Control"] = "no-store"
    return response



def _fertilizer_request(kind):
    """Queue a time-bounded GPIO pulse (the Flask process never touches GPIO)."""
    if int(session.get('role', 0)) != 1:
        abort(403)
    if os.getenv("PUMP2_ENABLED","0").lower() not in ("1","true","yes"):
        return jsonify(error="Pump 2 relay is disabled until wiring is verified"),409
    with db() as con:
        try:
            with con.cursor() as cur:
                cur.execute(
                    'SELECT fertilizer_dose_ml AS dose_ml,'
                    'fertilizer_ml_per_second AS ml_per_second,'
                    'fertilizer_manual_request_id AS manual_request_id,'
                    'fertilizer_manual_processed_id AS manual_processed_id,'
                    'fertilizer_manual_requested_at AS manual_requested_at,'
                    'fertilizer_pulse_state AS pulse_state,'
                    'fertilizer_pulse_kind AS pulse_kind,'
                    'fertilizer_pulse_finished_at AS pulse_finished_at,'
                    'NOW() AS now_time FROM fertilizer_pump2 LIMIT 1 FOR UPDATE'
                )
                row=cur.fetchone()
                if row is None:
                    return jsonify(error='Fertilizer pump is not configured'),409
                if kind == 'calibration':
                    payload=request.get_json(silent=True)
                    requested=payload.get('duration_seconds') if isinstance(payload,dict) else None
                    if type(requested) is not int or not 2 <= requested <= 60:
                        return jsonify(error='Test duration must be 2–60 whole seconds'),400
                    duration=float(requested)
                elif kind == 'manual':
                    # Priming/maintenance independent of calibration and dose_ml.
                    # Always capped at 30s; operator can switch OFF sooner.
                    duration=30.0
                else:
                    duration=calibrated_seconds(row['dose_ml'],row['ml_per_second'])
                    if duration is None:
                        return jsonify(error='Calibrate the pump and set an achievable dose (1–60 seconds runtime) first'),409
                last=row['manual_requested_at']
                age=(row['now_time']-last).total_seconds() if last is not None else None
                # Retry a confirmed-OFF calibration or one skipped before activation.
                # Failed/interrupted/unconfirmed runs retain the safety cooldown.
                confirmed_retry = (kind == 'calibration'
                    and row['pulse_kind'] == 'calibration'
                    and row['manual_request_id'] == row['manual_processed_id']
                    and row['pulse_state'] in ('completed', 'skipped')
                    and row['pulse_finished_at'] is not None)
                required_gap = 5 if confirmed_retry else 120
                if age is not None and age < required_gap:
                    remaining = max(1, int(__import__('math').ceil(required_gap - age)))
                    return jsonify(error=f'Pump cooldown: retry in {remaining} seconds',
                                   retry_after_seconds=remaining),429
                if row['manual_request_id'] != row['manual_processed_id']:
                    # Expired, unprocessed requests must never run late.
                    # This row is locked, so the relay worker cannot claim it
                    # while we retire it. Only do this after the cooldown.
                    if age is None or age < 18:
                        return jsonify(error='Another pump request is pending'),409
                    cur.execute(
                        "UPDATE fertilizer_pump2 SET "
                        "fertilizer_manual_processed_id=fertilizer_manual_request_id "
                        "WHERE fertilizer_manual_processed_id<fertilizer_manual_request_id"
                    )
                new_id=int(row['manual_request_id'])+1
                cur.execute(
                    'UPDATE fertilizer_pump2 SET fertilizer_manual_request_id=%s,'
                    'fertilizer_manual_duration_seconds=%s,'
                    'fertilizer_manual_requested_at=NOW(),fertilizer_manual_kind=%s,'
                    "fertilizer_pulse_request_id=%s,fertilizer_pulse_kind=%s,"
                    "fertilizer_pulse_state='queued',"
                    'fertilizer_pulse_started_at=NULL,'
                    'fertilizer_pulse_finished_at=NULL,'
                    'fertilizer_pulse_duration_seconds=%s ',
                    (new_id,duration,kind,new_id,kind,duration)
                )
                cur.execute(
                    'INSERT INTO loging (`User`,`Event`,`Datetime`) VALUES (%s,%s,NOW())',
                    (session['user'],f'Fertilizer Pump 2 {kind} pulse requested: {duration:.2f} seconds')
                )
            con.commit()
        except Exception:
            con.rollback()
            raise
    response=jsonify(queued=True,request_id=new_id,duration_seconds=duration,
                     note='Queued, not verified delivered. Check relay logs.')
    response.headers['Cache-Control']='no-store'
    return response,202


@bp.get('/status')
@_logged_in
def fertilizer_pulse_status():
    """Progress reported from relay worker GPIO commands (not flow feedback)."""
    row=query(
        "SELECT fertilizer_dose_ml AS dose_ml,"
        "fertilizer_ml_per_second AS ml_per_second,"
        "fertilizer_manual_request_id AS manual_request_id,"
        "fertilizer_manual_processed_id AS manual_processed_id,"
        "fertilizer_manual_requested_at AS manual_requested_at,"
        "fertilizer_calibration_saved_request_id AS calibration_saved_request_id,"
        "fertilizer_pulse_request_id AS pulse_request_id,"
        "fertilizer_pulse_kind AS pulse_kind,"
        "fertilizer_pulse_state AS pulse_state,"
        "fertilizer_pulse_duration_seconds AS pulse_duration_seconds,"
        "fertilizer_pulse_started_at AS pulse_started_at,"
        "fertilizer_pulse_finished_at AS pulse_finished_at,"
        "TIMESTAMPDIFF(MICROSECOND,fertilizer_pulse_started_at,NOW(3))/1000000.0 "
        "AS elapsed_seconds,"
        "TIMESTAMPDIFF(MICROSECOND,fertilizer_manual_requested_at,NOW(3))/1000000.0 "
        "AS request_age_seconds "
        "FROM fertilizer_pump2 LIMIT 1",one=True
    )
    if row is None:
        return jsonify(error='Fertilizer configuration missing'),404
    state=row['pulse_state']
    elapsed=float(row['elapsed_seconds'] or 0)
    duration=float(row['pulse_duration_seconds'] or 0)
    age=float(row['request_age_seconds'] or 0)
    if state == 'running' and elapsed > duration+5:
        state='unconfirmed'  # Worker may have crashed; never report completion.
    if state == 'queued' and age > 18:
        state='stale'
    if state == 'stop_requested' and age > duration+5:
        state='unconfirmed'  # OFF acknowledgement missing; physical state unknown.
    confirmed_retry = (row['pulse_kind'] == 'calibration'
        and int(row['manual_request_id']) == int(row['manual_processed_id'])
        and row['pulse_state'] in ('completed', 'skipped')
        and row['pulse_finished_at'] is not None)
    calibration_retry_after = (max(0, (5 if confirmed_retry else 120) - age)
                               if row['manual_requested_at'] else 0)
    response=jsonify(
        calibration_retry_after_seconds=calibration_retry_after,
        request_id=int(row['pulse_request_id']),
        kind=row['pulse_kind'],
        state=state,
        duration_seconds=duration,
        elapsed_seconds=max(0,elapsed),
        request_age_seconds=max(0,age),
        calibrated=row['ml_per_second'] is not None,
        calibration_saved_request_id=int(row['calibration_saved_request_id']),
        dose_ml=float(row['dose_ml'] or 0),
        manual_on=row['pulse_kind']=='manual' and state in
            ('queued','running','stop_requested'),
        # 'completed' means the worker issued OFF, not that liquid flowed.
        note='Relay command status only; pumped volume is not measured'
    )
    response.headers['Cache-Control']='no-store'
    return response


@bp.post('/dose')
@_logged_in
def manual_fertilizer_dose():
    return _fertilizer_request('dose')


@bp.post('/manual/start')
@_logged_in
def manual_pump_start():
    """Start a bounded 30-second maximum pulse; independent of calibration."""
    return _fertilizer_request('manual')


@bp.post('/manual/stop')
@_logged_in
def manual_pump_stop():
    """Request early OFF for the currently pending/running manual pump."""
    if int(session.get('role', 0)) != 1:
        abort(403)
    with db() as con:
        try:
            with con.cursor() as cur:
                cur.execute(
                    'SELECT fertilizer_manual_request_id AS manual_request_id,'
                    'fertilizer_pulse_request_id AS pulse_request_id,'
                    'fertilizer_pulse_kind AS pulse_kind,'
                    'fertilizer_pulse_state AS pulse_state '
                    'FROM fertilizer_pump2 LIMIT 1 FOR UPDATE'
                )
                row=cur.fetchone()
                if not row:
                    return jsonify(error='Fertilizer configuration missing'),409
                if (row['pulse_kind']!='manual' or
                        row['manual_request_id']!=row['pulse_request_id']):
                    return jsonify(error='No manual pump session to stop'),409
                if row['pulse_state'] in ('queued','running'):
                    cur.execute(
                        "UPDATE fertilizer_pump2 SET fertilizer_pulse_state='stop_requested' "
                        "WHERE fertilizer_pulse_request_id=%s "
                        "AND fertilizer_pulse_state IN ('queued','running')",
                        (row['pulse_request_id'],)
                    )
                elif row['pulse_state'] not in ('stop_requested','stopped','completed'):
                    return jsonify(error='Manual pump is not running'),409
            con.commit()
        except Exception:
            con.rollback()
            raise
    response=jsonify(ok=True,note='Relay stop requested; waiting for worker acknowledgment')
    response.headers['Cache-Control']='no-store'
    return response


@bp.post('/calibration/start')
@_logged_in
def start_fertilizer_calibration():
    return _fertilizer_request('calibration')


@bp.post('/calibration/finish')
@_logged_in
def finish_fertilizer_calibration():
    if int(session.get('role',0)) != 1:
        abort(403)
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict):
        return jsonify(error='Expected measured_ml'),400
    with db() as con:
        try:
            with con.cursor() as cur:
                cur.execute(
                    'SELECT fertilizer_manual_request_id AS manual_request_id,'
                    'fertilizer_manual_processed_id AS manual_processed_id,'
                    'fertilizer_manual_kind AS manual_kind,'
                    'fertilizer_manual_requested_at AS manual_requested_at,'
                    'fertilizer_calibration_saved_request_id AS calibration_saved_request_id,'
                    'fertilizer_pulse_state AS pulse_state,'
                    'fertilizer_pulse_kind AS pulse_kind,'
                    'fertilizer_pulse_request_id AS pulse_request_id,'
                    'fertilizer_pulse_finished_at AS pulse_finished_at,'
                    'fertilizer_pulse_duration_seconds AS pulse_duration_seconds,'
                    'NOW() AS now_time FROM fertilizer_pump2 LIMIT 1 FOR UPDATE'
                )
                row=cur.fetchone()
                if row is None:
                    return jsonify(error='Missing pump configuration'),409
                age=((row['now_time']-row['manual_requested_at']).total_seconds()
                     if row['manual_requested_at'] else -1)
                if (row['manual_kind'] != 'calibration'
                        or row['pulse_kind'] != 'calibration'
                        or row['pulse_state'] != 'completed'
                        or row['pulse_request_id'] != row['manual_request_id']
                        or row['pulse_finished_at'] is None
                        or row['manual_request_id'] != row['manual_processed_id']
                        or row['manual_request_id'] == row['calibration_saved_request_id']
                        or not 0 <= age <= 900):
                    return jsonify(error='No completed, recent 10-second calibration test to save'),409
                # Use the DB-recorded completed test duration, never a
                # client-supplied divisor or the old fixed 10-second value.
                rate=calibrate_rate(payload.get('measured_ml'),row['pulse_duration_seconds'])
                if rate is None:
                    return jsonify(error='Enter measured 0.1–500 ml for the completed test'),400
                cur.execute(
                    'UPDATE fertilizer_pump2 SET fertilizer_ml_per_second=%s,'
                    'fertilizer_calibration_saved_request_id=%s',
                    (str(rate),row['manual_request_id'])
                )
                cur.execute(
                    'INSERT INTO loging (`User`,`Event`,`Datetime`) VALUES (%s,%s,NOW())',
                    (session['user'],f"Pump calibrated: {rate} ml/s ({row['pulse_duration_seconds']}s test)")
                )
            con.commit()
        except Exception:
            con.rollback()
            raise
    response=jsonify(ok=True,ml_per_second=float(rate))
    response.headers['Cache-Control']='no-store'
    return response


