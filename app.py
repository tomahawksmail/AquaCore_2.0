"""AquaCore classic-schema compatible web UI. Hardware logic remains external."""
import os
import secrets
import subprocess
from datetime import datetime, timedelta
from functools import wraps

import pymysql
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort
from werkzeug.security import check_password_hash, generate_password_hash
from dotenv import load_dotenv
from scheduler import next_transition, scheduled_state, SCHEDULE_MAP

load_dotenv()
def local_commit():
    """Show the deployed checkout's commit, not GitHub's newest remote commit."""
    try:
        return subprocess.check_output(
            ['git', 'rev-parse', '--short=7', 'HEAD'],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL, timeout=2, text=True
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return os.getenv('AQUACORE_COMMIT', 'Unavailable')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.jinja_env.globals['deployed_commit'] = local_commit()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', MAX_CONTENT_LENGTH=16384)
if os.environ.get('COOKIE_SECURE', 'false').lower() == 'true':
    app.config['SESSION_COOKIE_SECURE'] = True

METRICS = [('temp', 'Temperature', '°C'), ('ph', 'pH', ''), ('tds', 'TDS', 'ppm')]
DEVICES = [
 ('co2_status','CO₂','co2_on','co2_off'),
 ('o2_status','Oxygen','o2_on','o2_off'),
 ('UV_status','UV sterilizer','UV_on','UV_off'),
 ('MasterL_status','Main light','Master_light_on','Master_light_off'),
 ('Backlight_status','Backlight','Backlight_on','Backlight_off'),
 ('PlantL_status','Plant light','PlantL_on','PlantL_off'),
]
SETTINGS = {'min_temp':(float,0,50), 'max_temp':(float,0,50),
 'min_ph':(float,0,14), 'max_ph':(float,0,14), 'min_tds':(float,0,10000), 'max_tds':(float,0,10000),
 'history':(int,1,720)}
TIME_FIELDS = [f for _,_,a,b in DEVICES for f in (a,b) if f]

def db():
    # Accept both original AquaCore and modern names (modern names take precedence).
    return pymysql.connect(host=os.getenv('DB_HOST') or os.getenv('HOST') or '127.0.0.1',
        port=int(os.getenv('DB_PORT','3306')),
        user=os.getenv('DB_USER') or os.getenv('USER') or 'aquacore_web',
        password=os.getenv('DB_PASSWORD') if os.getenv('DB_PASSWORD') is not None else os.getenv('PASSWORD',''),
        database=os.getenv('DB_NAME') or os.getenv('DATABASE') or '_AquaCore_', charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,connect_timeout=5,read_timeout=10,write_timeout=10,
        autocommit=False)

def query(sql, params=(), one=False):
    with db() as con:
        with con.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone() if one else cur.fetchall()

def mutate(sql, params):
    with db() as con:
        with con.cursor() as cur: cur.execute(sql, params)
        con.commit()

def csrf_token():
    if 'csrf' not in session: session['csrf'] = secrets.token_hex(24)
    return session['csrf']
app.jinja_env.globals['csrf_token'] = csrf_token

@app.before_request
def verify_csrf():
    if request.method in ('POST','PUT','PATCH','DELETE') and not secrets.compare_digest(
        str(session.get('csrf','')), str(request.form.get('csrf') or request.headers.get('X-CSRF-Token') or '!')):
        abort(400, description='Invalid CSRF token')

def logged_in(fn):
    @wraps(fn)
    def wrapper(*args,**kwargs):
        if not session.get('user'): return redirect(url_for('login'))
        return fn(*args,**kwargs)
    return wrapper

@app.route('/')
def home(): return redirect(url_for('dashboard') if session.get('user') else url_for('login'))

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        username=request.form.get('user','').strip()[:50]
        password=request.form.get('password','')
        account=query('SELECT Username, UserPassword, Role FROM users WHERE Username=%s LIMIT 1',(username,),True)
        hashed=account['UserPassword'] if account else ''
        # Only modern hashes are allowed. Old MD5 accounts require reset.
        if account and hashed.startswith(('scrypt:', 'pbkdf2:')) and check_password_hash(hashed,password):
            session.clear(); session['user']=account['Username']; session['role']=int(account['Role']); csrf_token()
            return redirect(url_for('dashboard'))
        flash('Incorrect credentials or password reset required.', 'error')
    return render_template('login.html')

@app.post('/logout')
@logged_in
def logout(): session.clear(); return redirect(url_for('login'))

@app.get('/aquarium')
@logged_in
def dashboard():
    # Compare consecutive measurements, ordered chronologically (not just by ID).
    recent=query('SELECT Id,Datetime,temp,ph,tds FROM data ORDER BY Datetime DESC, Id DESC LIMIT 2')
    latest=recent[0] if recent else None
    previous=recent[1] if len(recent)>1 else None
    points=query('SELECT Datetime,temp,ph,tds FROM data ORDER BY Datetime DESC, Id DESC LIMIT 48')
    options=query('SELECT * FROM options LIMIT 1',one=True) or {}
    statuses=query('SELECT * FROM status LIMIT 1',one=True) or {}
    overrides=query('SELECT device,until_at FROM manual_overrides WHERE until_at > NOW()')
    manual={r['device']: r['until_at'] for r in overrides}
    return render_template('dashboard.html', latest=latest, previous=previous, points=list(reversed(points)),
                           options=options, statuses=statuses, metrics=METRICS, devices=DEVICES, manual=manual)

# Existing status flags are software requests, NOT verified relay feedback.
# Automation in the legacy service may subsequently overwrite these flags.
CONTROL_FIELDS = {d[0] for d in DEVICES}

@app.get('/api/equipment')
@logged_in
def equipment_status():
    row=query('SELECT * FROM `status` LIMIT 1', one=True) or {}
    overrides=query('SELECT device, until_at FROM manual_overrides WHERE until_at > NOW()')
    manual={r['device']:r['until_at'].isoformat(sep=' ') for r in overrides}
    data={key: {'enabled':row.get(key)=='checked',
                'mode':'Manual' if key in manual else 'Schedule',
                'until':manual.get(key)} for key in CONTROL_FIELDS}
    response=jsonify(data); response.headers['Cache-Control']='no-store'
    return response

@app.post('/api/equipment/<field>')
@logged_in
def set_equipment(field):
    if int(session.get('role',0)) != 1: abort(403)
    if field not in CONTROL_FIELDS: abort(404)
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict) or type(payload.get('enabled')) is not bool:
        abort(400,description='Expected JSON: {"enabled": true/false}')
    desired='checked' if payload['enabled'] else 'unchecked'
    with db() as con:
        try:
            with con.cursor() as cur:
                cur.execute('SELECT NOW() AS t')
                t=cur.fetchone()['t']
                cur.execute('SELECT * FROM `options` LIMIT 1')
                opts=cur.fetchone() or {}
                try: until=next_transition(field,opts,t)
                except ValueError as exc: abort(409,description=str(exc))
                if until is None: abort(409,description='No valid ON/OFF schedule set for device')
                cur.execute('SELECT COUNT(*) AS n FROM `status`')
                if cur.fetchone()['n'] != 1: abort(409,description='Expected exactly one status row')
                cur.execute('INSERT INTO manual_overrides (device,desired,until_at,created_at) '
                            'VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE '
                            'desired=VALUES(desired),until_at=VALUES(until_at),created_at=VALUES(created_at)',
                            (field,desired,until,t))
                cur.execute('UPDATE `status` SET `'+field+'`=%s',(desired,))
                cur.execute('INSERT INTO loging (`User`,`Event`,`Datetime`) VALUES (%s,%s,%s)',
                            (session['user'],f'Manual {field} = {desired} until {until}',t))
            con.commit()
        except Exception:
            con.rollback(); raise
    result=jsonify({'field':field,'enabled':payload['enabled'],'mode':'Manual',
                    'until':until.isoformat(sep=' '),'note':'Software request only; relay not verified'})
    result.headers['Cache-Control']='no-store'
    return result

@app.get('/api/readings')
@logged_in
def readings():
    rows=query('SELECT Id,Datetime,temp,ph,tds FROM data ORDER BY Datetime DESC, Id DESC LIMIT 2')
    r=rows[0] if rows else None
    prev=rows[1] if len(rows)>1 else None
    if not r: return jsonify({})
    result={k:(v.isoformat() if isinstance(v,datetime) else v) for k,v in r.items() if k!='Id'}
    result['previous']={k:prev[k] for k in ('temp','ph','tds')} if prev else {}
    return jsonify(result)

@app.get('/api/history')
@logged_in
def history():
    """Bounded, aggregated historical measurements for mobile-friendly charts."""
    periods = {'24h': (1, 300), '7d': (7, 300), '30d': (30, 300), '90d': (90, 300)}
    period = request.args.get('period', '24h')
    if period not in periods:
        abort(400, description='Invalid history period')
    days, buckets = periods[period]
    # Server-side aggregation caps the response at ~300 points, even for large databases.
    seconds = max(60, days * 86400 // buckets)
    rows = query("""
        SELECT FROM_UNIXTIME(FLOOR(UNIX_TIMESTAMP(`Datetime`) / %s) * %s) AS time,
               ROUND(AVG(temp), 2) AS temp,
               ROUND(AVG(ph), 3) AS ph,
               ROUND(AVG(tds), 2) AS tds,
               COUNT(*) AS samples
          FROM data
         WHERE `Datetime` >= NOW() - INTERVAL %s DAY
           AND `Datetime` <= NOW()
         GROUP BY FLOOR(UNIX_TIMESTAMP(`Datetime`) / %s)
         ORDER BY time ASC
    """, (seconds, seconds, days, seconds))
    # Use the existing options row as the source of acceptable ranges.
    settings = query('SELECT min_temp, max_temp, min_ph, max_ph, min_tds, max_tds FROM options LIMIT 1', one=True) or {}
    limits = {key: (float(settings[key]) if settings.get(key) is not None else None)
              for key in ('min_temp', 'max_temp', 'min_ph', 'max_ph', 'min_tds', 'max_tds')}
    response = jsonify({
        'period': period,
        'limits': limits,
        'points': [{'time': r['time'].isoformat() if r['time'] else None,
                    'temp': float(r['temp']) if r['temp'] is not None else None,
                    'ph': float(r['ph']) if r['ph'] is not None else None,
                    'tds': float(r['tds']) if r['tds'] is not None else None,
                    'samples': r['samples']} for r in rows]
    })
    response.headers['Cache-Control'] = 'no-store'
    return response

@app.post('/api/options/field')
@logged_in
def save_option_field():
    """Save one field without resubmitting unrelated settings."""
    if int(session.get('role', 0)) != 1:
        abort(403)
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict):
        return jsonify(error='Expected JSON object'),400
    field=payload.get('field')
    if not isinstance(field,str) or field not in SETTINGS and field not in TIME_FIELDS:
        return jsonify(error='Unknown setting'),400
    raw=str(payload.get('value') if payload.get('value') is not None else '').strip()
    if not raw:
        return jsonify(error='A value is required'),400
    try:
        if field in SETTINGS:
            cast,low,high=SETTINGS[field]
            parsed=cast(raw)
            if not __import__('math').isfinite(parsed) or not low<=parsed<=high:
                raise ValueError('Outside permitted range')
            if field in ('min_temp','max_temp','min_ph','max_ph','min_tds','max_tds'):
                existing=query('SELECT min_temp,max_temp,min_ph,max_ph,min_tds,max_tds FROM options LIMIT 1',one=True)
                if not existing:
                    return jsonify(error='Missing options row'),409
                other={'min_temp':'max_temp','max_temp':'min_temp',
                       'min_ph':'max_ph','max_ph':'min_ph',
                       'min_tds':'max_tds','max_tds':'min_tds'}[field]
                current=existing[other]
                if current is not None and ((field.startswith('min_') and parsed>=current) or
                                            (field.startswith('max_') and parsed<=current)):
                    return jsonify(error='Minimum must be below maximum'),400
        else:
            parsed=datetime.strptime(raw,'%H:%M').strftime('%H:%M:%S')
    except (ValueError,OverflowError,TypeError):
        return jsonify(error='Invalid value'),400
    mutate('UPDATE options SET `'+field+'`=%s LIMIT 1',(parsed,))
    response=jsonify(ok=True,field=field,value=parsed)
    response.headers['Cache-Control']='no-store'
    return response

@app.route('/options',methods=['GET','POST'])
@logged_in
def options():
    current=query('SELECT * FROM options LIMIT 1',one=True) or {}
    if request.method=='POST':
        if int(session.get('role',0)) != 1: abort(403)
        changes={}
        try:
            for key,(cast,lo,hi) in SETTINGS.items():
                raw=request.form.get(key,'').strip()
                if raw:
                    value=cast(raw)
                    if not lo<=value<=hi: raise ValueError(key)
                    changes[key]=value
            if changes.get('min_temp',current.get('min_temp') or 0) >= changes.get('max_temp',current.get('max_temp') or 99):
                raise ValueError('Temperature minimum must be less than maximum')
            if changes.get('min_ph',current.get('min_ph') or 0) >= changes.get('max_ph',current.get('max_ph') or 14):
                raise ValueError('pH minimum must be less than maximum')
            if changes.get('min_tds',current.get('min_tds') if current.get('min_tds') is not None else 0) >= changes.get('max_tds',current.get('max_tds') if current.get('max_tds') is not None else 10000):
                raise ValueError('TDS minimum must be less than maximum')
            for key in TIME_FIELDS:
                raw=request.form.get(key,'').strip()
                if raw:
                    datetime.strptime(raw,'%H:%M'); changes[key]=raw+':00'
        except (ValueError,OverflowError):
            flash('Invalid settings; no changes saved.', 'error')
            return redirect(url_for('options'))
        if changes:
            # Keys are from hard-coded allowlists, never user input.
            sql='UPDATE options SET '+', '.join('`'+k+'`=%s' for k in changes)+' LIMIT 1'
            mutate(sql,tuple(changes.values()))
            flash('Settings saved. Existing hardware automation will read these values.', 'success')
        return redirect(url_for('options'))
    statuses=query('SELECT * FROM `status` LIMIT 1',one=True) or {}
    overrides=query('SELECT device,until_at FROM manual_overrides WHERE until_at > NOW()')
    manual={r['device']:r['until_at'] for r in overrides}
    return render_template('options.html', options=current,devices=DEVICES,settings=SETTINGS,
                           statuses=statuses,manual=manual)

@app.get('/loging')
@logged_in
def logs():
    rows=query('SELECT `User`,`Event`,`Datetime` FROM loging ORDER BY Id DESC LIMIT 100')
    return render_template('logs.html',rows=rows)

@app.get('/core_dashboard')
@logged_in
def core():
    latest=query('SELECT Id,RAM_percent,cpu_thermal_cur,disk_usage_percent,RAM_available FROM psutil ORDER BY Id DESC LIMIT 1',one=True)
    return render_template('core.html',row=latest)

@app.get('/api/system/history')
@logged_in
def system_history():
    """Recent system measurements in chronological sample order (bounded to 120)."""
    rows=query('SELECT Id,RAM_percent,cpu_thermal_cur,disk_usage_percent,RAM_available '
               'FROM psutil ORDER BY Id DESC LIMIT 120')
    result=[]
    for row in reversed(rows):
        result.append({key: (float(row[key]) if row.get(key) is not None else None)
                       for key in ('RAM_percent','cpu_thermal_cur','disk_usage_percent','RAM_available')})
    response=jsonify({'points':result})
    response.headers['Cache-Control']='no-store'
    return response

@app.cli.command('set-password')
def set_password():
    """Run with: flask --app app set-password (requires AQUACORE_ADMIN_USER/PASSWORD env)."""
    username=os.environ['AQUACORE_ADMIN_USER']
    password=os.environ['AQUACORE_ADMIN_PASSWORD']
    if len(password)<12: raise RuntimeError('Use a password of at least 12 characters')
    hashed=generate_password_hash(password)
    with db() as con:
        with con.cursor() as cur:
            cur.execute('SELECT U_Id FROM users WHERE Username=%s LIMIT 1',(username,))
            if cur.fetchone():
                cur.execute('UPDATE users SET UserPassword=%s WHERE Username=%s',(hashed,username))
            else:
                cur.execute('INSERT INTO users (Username,UserPassword,Role) VALUES (%s,%s,1)',(username,hashed))
        con.commit()
    print('Administrator credentials configured.')

if __name__=='__main__':
    app.run(host='127.0.0.1',port=5001,debug=False)
