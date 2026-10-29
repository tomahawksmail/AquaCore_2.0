"""DB scheduler: one writer for schedule-based status flags.
Run separately from Flask with: python scheduler.py
"""
import logging
import time
from datetime import datetime, timedelta

# Heater intentionally excluded: has temperature setpoint, not ON/OFF schedule.
SCHEDULE_MAP = {
    'co2_status': ('co2_on', 'co2_off'),
    'o2_status': ('o2_on', 'o2_off'),
    'UV_status': ('UV_on', 'UV_off'),
    'MasterL_status': ('Master_light_on', 'Master_light_off'),
    'Backlight_status': ('Backlight_on', 'Backlight_off'),
    'PlantL_status': ('PlantL_on', 'PlantL_off')
}

def minutes(value):
    if value is None: return None
    if isinstance(value,timedelta): return int(value.total_seconds()//60) % 1440
    if hasattr(value,'hour'):return value.hour*60+value.minute
    hh,mm,*rest=map(int,str(value).split(':'))
    return hh*60+mm

def schedule_times(field,options):
    on,off=SCHEDULE_MAP[field]
    a,b=minutes(options.get(on)),minutes(options.get(off))
    if a is None or b is None or a==b:
        raise ValueError('Set distinct ON/OFF times for '+field)
    return a,b

def scheduled_state(field,options,now):
    on,off=schedule_times(field,options)
    minute=now.hour*60+now.minute
    return (on<=minute<off) if on<off else (minute>=on or minute<off)

def next_transition(field,options,now):
    on,off=schedule_times(field,options)
    today=now.replace(hour=0,minute=0,second=0,microsecond=0)
    transitions=[today+timedelta(days=d,minutes=m) for d in range(2) for m in (on,off)]
    return min(t for t in transitions if t>now)

def reconcile():
    from app import db
    # Serialize with manual-update transaction by locking the singleton status row.
    with db() as con:
        try:
            with con.cursor() as cur:
                cur.execute('SELECT NOW() AS t')
                now=cur.fetchone()['t']
                cur.execute('SELECT * FROM `status` FOR UPDATE')
                rows=cur.fetchall()
                if len(rows)!=1: raise RuntimeError('status table must contain exactly one row')
                old=rows[0]
                cur.execute('SELECT * FROM `options`')
                opts=cur.fetchall()
                if len(opts)!=1: raise RuntimeError('options table must contain exactly one row')
                options=opts[0]
                cur.execute('SELECT device,desired,until_at FROM manual_overrides FOR UPDATE')
                overrides={r['device']:r for r in cur.fetchall()}
                for field in SCHEDULE_MAP:
                    try: auto=scheduled_state(field,options,now)
                    except ValueError as exc:
                        logging.warning('%s',exc);continue
                    override=overrides.get(field)
                    active=override and override['until_at']>now
                    desired=override['desired'] if active else ('checked' if auto else 'unchecked')
                    if old.get(field)!=desired:
                        cur.execute('UPDATE `status` SET `'+field+'`=%s',(desired,))
                        logging.info('%s => %s (%s)',field,desired,'manual' if active else 'schedule')
                cur.execute('DELETE FROM manual_overrides WHERE until_at<=%s',(now,))
            con.commit()
        except Exception:
            con.rollback();raise

def insert_missing_sensor_zeros():
    """Write a 0-valued sample once per minute while no sensor rows arrive.

    Existing scheduler process only; never start another watchdog.
    A fresh real sensor row resets the timeout automatically.
    """
    from app import db
    with db() as con:
        try:
            with con.cursor() as cur:
                # Avoid double inserts if the scheduler is accidentally started twice.
                cur.execute("SELECT GET_LOCK('aquacore_sensor_sample_60s', 0) AS acquired")
                if cur.fetchone()['acquired'] != 1:
                    return
                try:
                    cur.execute('SELECT NOW() AS now_time')
                    now = cur.fetchone()['now_time']
                    cur.execute('SELECT `Datetime` FROM `data` ORDER BY `Datetime` DESC, `Id` DESC LIMIT 1')
                    latest = cur.fetchone()
                    if latest and latest['Datetime'] is not None:
                        age = (now - latest['Datetime']).total_seconds()
                        if age < 60 or age < 0:
                            return
                    cur.execute('INSERT INTO `data` (`Datetime`,`temp`,`ph`,`tds`) VALUES (%s,0,0,0)', (now,))
                    con.commit()
                    logging.info('No sensor data for 60 seconds: inserted temp=0, ph=0, tds=0')
                finally:
                    cur.execute("SELECT RELEASE_LOCK('aquacore_sensor_sample_60s')")
            con.commit()
        except Exception:
            con.rollback()
            raise

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    logging.info('AquaCore schedule controller started')
    while True:
        try:
            reconcile()
        except Exception: logging.exception('Scheduler cycle failed')
        try:
            insert_missing_sensor_zeros()
        except Exception: logging.exception('Sensor zero fallback failed')
        time.sleep(5)
