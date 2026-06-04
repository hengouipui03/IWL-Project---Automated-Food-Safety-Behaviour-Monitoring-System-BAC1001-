"""
Automated Food Safety Behaviour Monitoring System — Dashboard Backend
Covers UC-01 through UC-07 from the requirements specification.
Pure Flask + sqlite3 (no SQLAlchemy) — compatible with Python 3.13.
"""

from flask import Flask, render_template, jsonify, request, session, redirect
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from functools import wraps
import sqlite3
import json
import os

app = Flask(__name__)
app.secret_key = 'food-safety-monitoring-secret-change-in-production'
DB_PATH = 'compliance.db'

# Behaviours the system can monitor (SFR-2.1)
BEHAVIOUR_TYPES = ['handwashing', 'ppe', 'allergen']

# Default data-retention period in days (SR-10 / SFR-10.1)
DEFAULT_RETENTION_DAYS = 90


# ============================================================
# DATABASE
# ============================================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS sites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        location TEXT,
        created_at TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        site_id INTEGER,
        created_at TEXT,
        FOREIGN KEY (site_id) REFERENCES sites(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS cameras (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id TEXT UNIQUE NOT NULL,
        site_id INTEGER NOT NULL,
        location TEXT,
        status TEXT DEFAULT 'inactive',
        last_heartbeat TEXT,
        FOREIGN KEY (site_id) REFERENCES sites(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS incidents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        site_id INTEGER NOT NULL,
        camera_id INTEGER,
        behaviour_type TEXT NOT NULL,
        compliance_status TEXT NOT NULL,
        risk_level TEXT,
        confidence REAL,
        timestamp TEXT NOT NULL,
        details TEXT,
        evidence_url TEXT,
        alerted INTEGER DEFAULT 0,
        validated INTEGER DEFAULT 0,
        validation_status TEXT,
        validation_reason TEXT,
        validation_notes TEXT,
        validated_by INTEGER,
        validated_at TEXT,
        FOREIGN KEY (site_id) REFERENCES sites(id),
        FOREIGN KEY (camera_id) REFERENCES cameras(id),
        FOREIGN KEY (validated_by) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        site_id INTEGER,
        behaviour_type TEXT NOT NULL,
        rule_name TEXT NOT NULL,
        description TEXT,
        alert_threshold REAL DEFAULT 50,
        confidence_threshold REAL DEFAULT 0.5,
        enabled INTEGER DEFAULT 1,
        created_at TEXT,
        updated_at TEXT,
        FOREIGN KEY (site_id) REFERENCES sites(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        action TEXT NOT NULL,
        target_type TEXT,
        target_id INTEGER,
        details TEXT,
        timestamp TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')

    conn.commit()
    conn.close()


def seed_data():
    """Create demo sites, users, cameras and rules if the DB is empty."""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) AS n FROM users')
    if c.fetchone()['n'] > 0:
        conn.close()
        return

    now = datetime.now().isoformat()
    print('\n' + '=' * 60)
    print('First run — seeding demo data...')
    print('=' * 60)

    c.execute('INSERT INTO sites (name, location, created_at) VALUES (?,?,?)',
              ('Central Kitchen', 'Singapore - Jurong', now))
    site1 = c.lastrowid
    c.execute('INSERT INTO sites (name, location, created_at) VALUES (?,?,?)',
              ('North Production Line', 'Singapore - Woodlands', now))
    site2 = c.lastrowid

    users = [
        ('admin',     'password123', 'admin',          None),
        ('manager',   'password123', 'manager',        site1),
        ('quality',   'password123', 'quality_team',   site1),
        ('senior',    'password123', 'senior_manager', None),
        ('auditor',   'password123', 'auditor',        None),
    ]
    for username, pw, role, site_id in users:
        c.execute('INSERT INTO users (username, password_hash, role, site_id, created_at) VALUES (?,?,?,?,?)',
                  (username, generate_password_hash(pw), role, site_id, now))
        print(f'  user: {username:9s} / password123   ({role})')

    for cam, site in [('SINK-001', site1), ('SINK-002', site1), ('SINK-003', site2)]:
        c.execute('INSERT INTO cameras (camera_id, site_id, location, status) VALUES (?,?,?,?)',
                  (cam, site, 'Handwashing station', 'active'))

    for site in [site1, site2]:
        c.execute('''INSERT INTO rules (site_id, behaviour_type, rule_name, description,
                     alert_threshold, confidence_threshold, enabled, created_at, updated_at)
                     VALUES (?,?,?,?,?,?,?,?,?)''',
                  (site, 'handwashing', 'Handwashing - 20s rule',
                   'Full wash (soap, rub >= 20s, rinse, dry) required.',
                   50, 0.5, 1, now, now))

    c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)',
              ('retention_days', str(DEFAULT_RETENTION_DAYS)))

    conn.commit()
    conn.close()
    print('=' * 60)
    print('Login with manager / password123  (or admin, quality, senior, auditor)')
    print('=' * 60 + '\n')


# ============================================================
# AUTH HELPERS  (SFR-8.X role-based access)
# ============================================================

ROLE_ACCESS = {
    'admin':          {'UC01', 'UC02', 'UC03', 'UC04', 'UC05', 'UC06', 'UC07'},
    'manager':        {'UC01', 'UC02', 'UC04'},
    'quality_team':   {'UC01', 'UC02', 'UC03', 'UC04'},
    'senior_manager': {'UC01', 'UC03', 'UC04', 'UC05', 'UC06'},
    'auditor':        {'UC01', 'UC02', 'UC03', 'UC04'},
}

ROLE_LABELS = {
    'admin': 'System Administrator',
    'manager': 'Site / Production Manager',
    'quality_team': 'Quality & Food Safety Team',
    'senior_manager': 'Senior / Regional Manager',
    'auditor': 'Auditor / Inspector',
}


def current_user():
    if 'user_id' not in session:
        return None
    conn = get_db()
    u = conn.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    conn.close()
    return u


def login_required(f):
    @wraps(f)
    def wrapper(*a, **k):
        if 'user_id' not in session:
            return jsonify({'error': 'Not authenticated'}), 401
        return f(*a, **k)
    return wrapper


def can(use_case):
    def deco(f):
        @wraps(f)
        def wrapper(*a, **k):
            u = current_user()
            if not u:
                return jsonify({'error': 'Not authenticated'}), 401
            if use_case not in ROLE_ACCESS.get(u['role'], set()):
                return jsonify({'error': 'Your role does not have access to this function'}), 403
            return f(*a, **k)
        return wrapper
    return deco


def is_auditor():
    u = current_user()
    return u and u['role'] == 'auditor'


def log_action(action, target_type=None, target_id=None, details=None):
    u = current_user()
    conn = get_db()
    conn.execute('''INSERT INTO audit_logs (user_id, username, action, target_type, target_id, details, timestamp)
                    VALUES (?,?,?,?,?,?,?)''',
                 (u['id'] if u else None, u['username'] if u else 'system',
                  action, target_type, target_id, details, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def visible_site_filter(u):
    if u['role'] in ('manager', 'quality_team') and u['site_id']:
        return 'AND i.site_id = ?', [u['site_id']]
    return '', []


# ============================================================
# RISK / ALERT LOGIC  (SFR-2.X, SFR-3.X)
# ============================================================

def derive_status(result, confidence, conf_threshold):
    if confidence is not None and confidence < conf_threshold:
        return 'unable_to_assess', 'low', 0
    if result == 'PASS':
        return 'compliant', 'low', 0
    if result == 'WARNING':
        return 'non_compliant', 'medium', 1
    return 'non_compliant', 'high', 1


# ============================================================
# PAGES
# ============================================================

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect('/login')
    return render_template('dashboard.html')


@app.route('/login')
def login_page():
    return render_template('login.html')


# ============================================================
# AUTH ENDPOINTS
# ============================================================

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    conn = get_db()
    u = conn.execute('SELECT * FROM users WHERE username=?', (data.get('username'),)).fetchone()
    conn.close()
    if u and check_password_hash(u['password_hash'], data.get('password', '')):
        session['user_id'] = u['id']
        log_action('LOGIN', 'user', u['id'])
        return jsonify({'success': True})
    return jsonify({'error': 'Invalid username or password'}), 401


@app.route('/api/logout', methods=['POST'])
@login_required
def api_logout():
    log_action('LOGOUT', 'user', session['user_id'])
    session.clear()
    return jsonify({'success': True})


@app.route('/api/me')
@login_required
def api_me():
    u = current_user()
    conn = get_db()
    site = None
    if u['site_id']:
        s = conn.execute('SELECT name FROM sites WHERE id=?', (u['site_id'],)).fetchone()
        site = s['name'] if s else None
    conn.close()
    return jsonify({
        'username': u['username'],
        'role': u['role'],
        'role_label': ROLE_LABELS.get(u['role'], u['role']),
        'site': site,
        'access': sorted(ROLE_ACCESS.get(u['role'], set())),
        'read_only': u['role'] == 'auditor',
    })


# ============================================================
# INCIDENT INTAKE (from detection.py via integration.py)
# ============================================================

@app.route('/api/incidents', methods=['POST'])
def create_incident():
    data = request.get_json(force=True)
    conn = get_db()
    c = conn.cursor()

    cam_str = str(data.get('camera_id', '')).strip()
    cam = c.execute('SELECT * FROM cameras WHERE camera_id=?', (cam_str,)).fetchone()
    if cam:
        site_id = cam['site_id']
        camera_pk = cam['id']
    else:
        s = c.execute('SELECT id FROM sites ORDER BY id LIMIT 1').fetchone()
        site_id = s['id'] if s else None
        if site_id and cam_str:
            c.execute('INSERT INTO cameras (camera_id, site_id, location, status) VALUES (?,?,?,?)',
                      (cam_str, site_id, 'Auto-registered', 'active'))
            camera_pk = c.lastrowid
        else:
            camera_pk = None

    behaviour = data.get('behaviour_type', 'handwashing')
    result = data.get('result', 'FAIL')
    confidence = data.get('confidence')

    rule = c.execute('''SELECT confidence_threshold FROM rules
                        WHERE behaviour_type=? AND (site_id=? OR site_id IS NULL) AND enabled=1
                        ORDER BY site_id IS NULL LIMIT 1''',
                     (behaviour, site_id)).fetchone()
    conf_threshold = rule['confidence_threshold'] if rule else 0.5

    status, risk, alerted = derive_status(result, confidence, conf_threshold)

    details = {
        'result': result,
        'steps': data.get('steps', []),
        'rub_duration': data.get('rub_duration'),
    }

    c.execute('''INSERT INTO incidents (site_id, camera_id, behaviour_type, compliance_status,
                 risk_level, confidence, timestamp, details, evidence_url, alerted)
                 VALUES (?,?,?,?,?,?,?,?,?,?)''',
              (site_id, camera_pk, behaviour, status, risk, confidence,
               datetime.now().isoformat(), json.dumps(details),
               data.get('evidence_url'), alerted))
    incident_id = c.lastrowid

    if camera_pk:
        c.execute('UPDATE cameras SET last_heartbeat=?, status=? WHERE id=?',
                  (datetime.now().isoformat(), 'active', camera_pk))

    conn.commit()
    conn.close()
    return jsonify({'success': True, 'incident_id': incident_id,
                    'compliance_status': status, 'risk_level': risk}), 201


# ============================================================
# UC-01  DAILY COMPLIANCE DASHBOARD
# ============================================================

@app.route('/api/dashboard')
@can('UC01')
def api_dashboard():
    u = current_user()
    days = request.args.get('days', 1, type=int)
    since = (datetime.now() - timedelta(days=days)).isoformat()
    sfilter, sparams = visible_site_filter(u)

    conn = get_db()
    base = f'FROM incidents i WHERE i.timestamp >= ? {sfilter}'
    params = [since] + sparams

    total = conn.execute(f'SELECT COUNT(*) n {base}', params).fetchone()['n']
    compliant = conn.execute(f"SELECT COUNT(*) n {base} AND compliance_status='compliant'", params).fetchone()['n']
    non_comp = conn.execute(f"SELECT COUNT(*) n {base} AND compliance_status='non_compliant'", params).fetchone()['n']
    unable = conn.execute(f"SELECT COUNT(*) n {base} AND compliance_status='unable_to_assess'", params).fetchone()['n']

    alerts = conn.execute(f'''SELECT i.id, i.behaviour_type, i.risk_level, i.timestamp,
                              s.name AS site, c.camera_id AS camera
                              FROM incidents i
                              JOIN sites s ON s.id = i.site_id
                              LEFT JOIN cameras c ON c.id = i.camera_id
                              WHERE i.alerted = 1 AND i.validated = 0 AND i.timestamp >= ? {sfilter}
                              ORDER BY i.timestamp DESC LIMIT 20''',
                          params).fetchall()

    by_behaviour = conn.execute(f'''SELECT behaviour_type,
                                    SUM(CASE WHEN compliance_status='compliant' THEN 1 ELSE 0 END) compliant,
                                    COUNT(*) total
                                    {base} GROUP BY behaviour_type''', params).fetchall()
    conn.close()

    rate = round(compliant / total * 100, 1) if total else 0
    return jsonify({
        'period_days': days,
        'total_events': total,
        'compliant': compliant,
        'non_compliant': non_comp,
        'unable_to_assess': unable,
        'compliance_rate': rate,
        'normal_status': len(alerts) == 0,
        'alerts': [dict(a) for a in alerts],
        'by_behaviour': [
            {'behaviour': r['behaviour_type'],
             'compliant': r['compliant'], 'total': r['total'],
             'rate': round(r['compliant'] / r['total'] * 100, 1) if r['total'] else 0}
            for r in by_behaviour
        ],
    })


# ============================================================
# UC-02  REVIEW & VALIDATE INCIDENTS
# ============================================================

@app.route('/api/incidents')
@can('UC02')
def list_incidents():
    u = current_user()
    sfilter, sparams = visible_site_filter(u)
    status = request.args.get('status')
    behaviour = request.args.get('behaviour')
    limit = request.args.get('limit', 100, type=int)

    q = f'''SELECT i.*, s.name AS site_name, c.camera_id AS camera_code,
            v.username AS validator_name
            FROM incidents i
            JOIN sites s ON s.id = i.site_id
            LEFT JOIN cameras c ON c.id = i.camera_id
            LEFT JOIN users v ON v.id = i.validated_by
            WHERE 1=1 {sfilter}'''
    params = list(sparams)
    if status:
        q += ' AND i.compliance_status = ?'; params.append(status)
    if behaviour:
        q += ' AND i.behaviour_type = ?'; params.append(behaviour)
    q += ' ORDER BY i.timestamp DESC LIMIT ?'; params.append(limit)

    conn = get_db()
    rows = conn.execute(q, params).fetchall()
    conn.close()

    out = []
    for r in rows:
        d = dict(r)
        d['details'] = json.loads(r['details']) if r['details'] else {}
        d.pop('password_hash', None)
        out.append(d)
    return jsonify(out)


@app.route('/api/incidents/<int:iid>')
@can('UC02')
def incident_detail(iid):
    conn = get_db()
    r = conn.execute('''SELECT i.*, s.name AS site_name, c.camera_id AS camera_code,
                        v.username AS validator_name
                        FROM incidents i
                        JOIN sites s ON s.id=i.site_id
                        LEFT JOIN cameras c ON c.id=i.camera_id
                        LEFT JOIN users v ON v.id=i.validated_by
                        WHERE i.id=?''', (iid,)).fetchone()
    conn.close()
    if not r:
        return jsonify({'error': 'Not found'}), 404
    d = dict(r)
    d['details'] = json.loads(r['details']) if r['details'] else {}
    d.pop('password_hash', None)
    return jsonify(d)


@app.route('/api/incidents/<int:iid>/validate', methods=['POST'])
@can('UC02')
def validate_incident(iid):
    if is_auditor():
        return jsonify({'error': 'Auditors have read-only access'}), 403

    data = request.get_json()
    new_status = data.get('status')
    reason = (data.get('reason') or '').strip()
    notes = data.get('notes', '')

    if not reason:
        return jsonify({'error': 'A reclassification reason is required to finalise validation'}), 400

    u = current_user()
    conn = get_db()
    exists = conn.execute('SELECT id FROM incidents WHERE id=?', (iid,)).fetchone()
    if not exists:
        conn.close()
        return jsonify({'error': 'Not found'}), 404

    conn.execute('''UPDATE incidents SET validated=1, validation_status=?, validation_reason=?,
                    validation_notes=?, validated_by=?, validated_at=?, alerted=0,
                    compliance_status = CASE WHEN ? IN ('compliant','non_compliant') THEN ? ELSE compliance_status END
                    WHERE id=?''',
                 (new_status, reason, notes, u['id'], datetime.now().isoformat(),
                  new_status, new_status, iid))
    conn.commit()
    conn.close()
    log_action('VALIDATE_INCIDENT', 'incident', iid, f'status={new_status}; reason={reason}')
    return jsonify({'success': True})


# ============================================================
# UC-03  BEHAVIOUR TRENDS
# ============================================================

@app.route('/api/trends')
@can('UC03')
def api_trends():
    u = current_user()
    days = request.args.get('days', 30, type=int)
    behaviour = request.args.get('behaviour')
    since = (datetime.now() - timedelta(days=days)).isoformat()
    sfilter, sparams = visible_site_filter(u)

    q = f'''SELECT DATE(i.timestamp) d,
            SUM(CASE WHEN compliance_status='compliant' THEN 1 ELSE 0 END) compliant,
            SUM(CASE WHEN compliance_status='non_compliant' THEN 1 ELSE 0 END) non_compliant
            FROM incidents i WHERE i.timestamp >= ? {sfilter}'''
    params = [since] + sparams
    if behaviour:
        q += ' AND i.behaviour_type = ?'; params.append(behaviour)
    q += ' GROUP BY DATE(i.timestamp) ORDER BY d'

    conn = get_db()
    rows = conn.execute(q, params).fetchall()
    total = conn.execute(f'SELECT COUNT(*) n FROM incidents i WHERE i.timestamp >= ? {sfilter}',
                         [since] + sparams).fetchone()['n']
    conn.close()

    series = [{'date': r['d'], 'compliant': r['compliant'],
               'non_compliant': r['non_compliant'],
               'rate': round(r['compliant'] / (r['compliant'] + r['non_compliant']) * 100, 1)
                       if (r['compliant'] + r['non_compliant']) else 0}
              for r in rows]

    incomplete = total < 5 or len(series) < 2
    rates = [s['rate'] for s in series]
    stable = len(rates) >= 2 and (max(rates) - min(rates) <= 5)

    return jsonify({
        'data': series,
        'total_events': total,
        'incomplete': incomplete,
        'incomplete_msg': 'Insufficient historical data - results may be incomplete.' if incomplete else None,
        'stable': stable,
        'stable_msg': 'Compliance is stable - no significant trend detected.' if stable else None,
    })


# ============================================================
# UC-04  COMPLIANCE REPORTS
# ============================================================

@app.route('/api/reports', methods=['POST'])
@can('UC04')
def api_report():
    u = current_user()
    data = request.get_json()
    start = data.get('start_date')
    end = data.get('end_date')
    behaviour = data.get('behaviour')
    sfilter, sparams = visible_site_filter(u)

    q = f'''SELECT behaviour_type, compliance_status, risk_level, COUNT(*) n
            FROM incidents i WHERE i.timestamp BETWEEN ? AND ? {sfilter}'''
    params = [start, end + 'T23:59:59'] + sparams
    if behaviour:
        q += ' AND behaviour_type = ?'; params.append(behaviour)
    q += ' GROUP BY behaviour_type, compliance_status, risk_level'

    conn = get_db()
    rows = conn.execute(q, params).fetchall()
    conn.close()

    total = sum(r['n'] for r in rows)
    compliant = sum(r['n'] for r in rows if r['compliance_status'] == 'compliant')
    by_behaviour = {}
    risk = {'low': 0, 'medium': 0, 'high': 0}
    for r in rows:
        b = by_behaviour.setdefault(r['behaviour_type'], {'total': 0, 'compliant': 0})
        b['total'] += r['n']
        if r['compliance_status'] == 'compliant':
            b['compliant'] += r['n']
        if r['risk_level'] in risk:
            risk[r['risk_level']] += r['n']

    log_action('GENERATE_REPORT', 'report', None, f'{start}..{end} behaviour={behaviour or "all"}')

    withheld = is_auditor()
    return jsonify({
        'generated_at': datetime.now().isoformat(),
        'generated_by': u['username'],
        'period': f'{start} to {end}',
        'behaviour_filter': behaviour or 'all',
        'total_events': total,
        'compliant': compliant,
        'non_compliant': total - compliant,
        'compliance_rate': round(compliant / total * 100, 1) if total else 0,
        'by_behaviour': by_behaviour,
        'risk_distribution': risk,
        'withheld': withheld,
        'withheld_msg': 'Some operational detail withheld under data-protection policy.' if withheld else None,
    })


# ============================================================
# UC-05  CONFIGURE RULES & ALERTS
# ============================================================

@app.route('/api/rules', methods=['GET'])
@can('UC05')
def list_rules():
    conn = get_db()
    rows = conn.execute('''SELECT r.*, s.name AS site_name FROM rules r
                           LEFT JOIN sites s ON s.id=r.site_id ORDER BY r.id''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/rules', methods=['POST'])
@can('UC05')
def create_rule():
    data = request.get_json()
    try:
        threshold = float(data.get('alert_threshold', 50))
        conf = float(data.get('confidence_threshold', 0.5))
    except (TypeError, ValueError):
        return jsonify({'error': 'Thresholds must be numbers'}), 400
    if not (0 <= threshold <= 100) or not (0 <= conf <= 1):
        return jsonify({'error': 'alert_threshold must be 0-100 and confidence_threshold 0-1'}), 400
    if data.get('behaviour_type') not in BEHAVIOUR_TYPES:
        return jsonify({'error': f'behaviour_type must be one of {BEHAVIOUR_TYPES}'}), 400

    now = datetime.now().isoformat()
    conn = get_db()
    conn.execute('''INSERT INTO rules (site_id, behaviour_type, rule_name, description,
                    alert_threshold, confidence_threshold, enabled, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?)''',
                 (data.get('site_id'), data['behaviour_type'], data['rule_name'],
                  data.get('description', ''), threshold, conf,
                  1 if data.get('enabled', True) else 0, now, now))
    conn.commit()
    conn.close()
    log_action('CREATE_RULE', 'rule', None, data['rule_name'])
    return jsonify({'success': True}), 201


@app.route('/api/rules/<int:rid>', methods=['PUT', 'DELETE'])
@can('UC05')
def modify_rule(rid):
    conn = get_db()
    if request.method == 'DELETE':
        conn.execute('DELETE FROM rules WHERE id=?', (rid,))
        conn.commit(); conn.close()
        log_action('DELETE_RULE', 'rule', rid)
        return jsonify({'success': True})

    data = request.get_json()
    try:
        threshold = float(data.get('alert_threshold', 50))
        conf = float(data.get('confidence_threshold', 0.5))
    except (TypeError, ValueError):
        conn.close()
        return jsonify({'error': 'Thresholds must be numbers'}), 400
    if not (0 <= threshold <= 100) or not (0 <= conf <= 1):
        conn.close()
        return jsonify({'error': 'Invalid threshold ranges'}), 400

    conn.execute('''UPDATE rules SET rule_name=?, description=?, alert_threshold=?,
                    confidence_threshold=?, enabled=?, updated_at=? WHERE id=?''',
                 (data['rule_name'], data.get('description', ''), threshold, conf,
                  1 if data.get('enabled', True) else 0, datetime.now().isoformat(), rid))
    conn.commit(); conn.close()
    log_action('UPDATE_RULE', 'rule', rid, data.get('rule_name'))
    return jsonify({'success': True})


# ============================================================
# UC-06  COMPARE COMPLIANCE ACROSS SITES
# ============================================================

@app.route('/api/compare')
@can('UC06')
def api_compare():
    days = request.args.get('days', 30, type=int)
    behaviour = request.args.get('behaviour')
    since = (datetime.now() - timedelta(days=days)).isoformat()

    q = '''SELECT s.id, s.name, s.location,
           COUNT(i.id) total,
           SUM(CASE WHEN i.compliance_status='compliant' THEN 1 ELSE 0 END) compliant
           FROM sites s
           LEFT JOIN incidents i ON i.site_id=s.id AND i.timestamp >= ?'''
    params = [since]
    if behaviour:
        q += ' AND i.behaviour_type = ?'; params.append(behaviour)
    q += ' GROUP BY s.id ORDER BY s.name'

    conn = get_db()
    rows = conn.execute(q, params).fetchall()
    conn.close()

    sites = [{'site': r['name'], 'location': r['location'],
              'total': r['total'],
              'compliant': r['compliant'] or 0,
              'rate': round((r['compliant'] or 0) / r['total'] * 100, 1) if r['total'] else 0}
             for r in rows]
    incomplete = any(s['total'] < 5 for s in sites)
    return jsonify({
        'sites': sites,
        'incomplete': incomplete,
        'incomplete_msg': 'Some sites have insufficient data - comparison may be incomplete.' if incomplete else None,
    })


# ============================================================
# UC-07  MANAGE USERS
# ============================================================

@app.route('/api/users', methods=['GET'])
@can('UC07')
def list_users():
    conn = get_db()
    rows = conn.execute('''SELECT u.id, u.username, u.role, u.site_id, u.created_at,
                           s.name AS site_name FROM users u
                           LEFT JOIN sites s ON s.id=u.site_id ORDER BY u.id''').fetchall()
    conn.close()
    return jsonify([{**dict(r), 'role_label': ROLE_LABELS.get(r['role'], r['role'])} for r in rows])


@app.route('/api/users', methods=['POST'])
@can('UC07')
def create_user():
    data = request.get_json()
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    role = data.get('role')

    if not username or not password:
        return jsonify({'error': 'Username and password are required'}), 400
    if role not in ROLE_ACCESS:
        return jsonify({'error': f'Role must be one of {list(ROLE_ACCESS)}'}), 400

    conn = get_db()
    if conn.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone():
        conn.close()
        return jsonify({'error': 'Username already exists'}), 400
    conn.execute('INSERT INTO users (username, password_hash, role, site_id, created_at) VALUES (?,?,?,?,?)',
                 (username, generate_password_hash(password), role,
                  data.get('site_id'), datetime.now().isoformat()))
    conn.commit(); conn.close()
    log_action('CREATE_USER', 'user', None, f'{username} ({role})')
    return jsonify({'success': True}), 201


@app.route('/api/users/<int:uid>', methods=['PUT', 'DELETE'])
@can('UC07')
def modify_user(uid):
    conn = get_db()
    target = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if not target:
        conn.close()
        return jsonify({'error': 'Not found'}), 404

    if request.method == 'DELETE':
        if not request.args.get('confirm') == 'true':
            conn.close()
            return jsonify({'error': 'confirmation_required',
                            'message': f'Confirm removal of user "{target["username"]}"'}), 409
        if uid == session['user_id']:
            conn.close()
            return jsonify({'error': 'You cannot delete your own account'}), 400
        conn.execute('DELETE FROM users WHERE id=?', (uid,))
        conn.commit(); conn.close()
        log_action('DELETE_USER', 'user', uid, target['username'])
        return jsonify({'success': True})

    data = request.get_json()
    role = data.get('role', target['role'])
    if role not in ROLE_ACCESS:
        conn.close()
        return jsonify({'error': 'Invalid role'}), 400
    if data.get('password'):
        conn.execute('UPDATE users SET role=?, site_id=?, password_hash=? WHERE id=?',
                     (role, data.get('site_id'), generate_password_hash(data['password']), uid))
    else:
        conn.execute('UPDATE users SET role=?, site_id=? WHERE id=?',
                     (role, data.get('site_id'), uid))
    conn.commit(); conn.close()
    log_action('UPDATE_USER', 'user', uid, target['username'])
    return jsonify({'success': True})


# ============================================================
# SHARED LOOKUPS
# ============================================================

@app.route('/api/sites')
@login_required
def api_sites():
    conn = get_db()
    rows = conn.execute('SELECT * FROM sites ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/audit-logs')
@can('UC07')
def api_audit():
    conn = get_db()
    rows = conn.execute('SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT 100').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/behaviours')
@login_required
def api_behaviours():
    return jsonify(BEHAVIOUR_TYPES)


if __name__ == '__main__':
    init_db()
    seed_data()
    app.run(debug=True, port=5002)
