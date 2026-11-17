"""HR Master Portal - local server (Python 3.9+, standard library only).
Serves the web page and a JSON API, and stores everything in one SQLite file (hr_portal.db)."""
import argparse, hashlib, json, os, re, secrets, sqlite3, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
LOCK = threading.Lock()
START_TIME = time.time()
REQUEST_COUNT = 0
REQUEST_LOCK = threading.Lock()

# ─── ผู้ใช้งาน (username: sha256(password)) ───────────────────────────────────
def _h(pw): return hashlib.sha256(pw.encode()).hexdigest()
USERS = {
    'admin': _h('1234'),
    'employee': _h('123456'),
}

# ─── Sessions (token -> {user, expires}) ──────────────────────────────────────
SESSIONS = {}
SESSION_TTL = 8 * 3600   # 8 ชั่วโมง
SESSION_LOCK = threading.Lock()

def _new_session(user):
    token = secrets.token_hex(32)
    with SESSION_LOCK:
        SESSIONS[token] = {'user': user, 'expires': time.time() + SESSION_TTL}
    return token

def _valid_session(token):
    with SESSION_LOCK:
        s = SESSIONS.get(token)
        if not s: return None
        if time.time() > s['expires']:
            del SESSIONS[token]; return None
        s['expires'] = time.time() + SESSION_TTL   # sliding window
        return s['user']

def _del_session(token):
    with SESSION_LOCK:
        SESSIONS.pop(token, None)

# ─── Schema ───────────────────────────────────────────────────────────────────
EMP = ['id','title','name','sex','dob','dept','branch','pos','start','status','resign','marital','spouse','father',
       'fstat','mother','mstat','phone','addr','nas','ncsl','edu','train','bank']
REC = {
 'con':  ('contracts',    ['emp_id','contract_type','effective_date','contract_end_date','type_of_contract','remark']),
 'kids': ('children',     ['emp_id','child_name','sex','date_of_birth','remark']),
 'warn': ('warnings',     ['emp_id','issue_date','warning_type','issue_detail','issued_by','remark']),
 'prom': ('promotions',   ['emp_id','effective_date','old_position','new_position','remark']),
 'cert': ('certificates', ['emp_id','request_date','purpose','issue_date','doc_number','remark']),
 'appr': ('appraisals',   ['emp_id','appraisal_date','appraisal_year','score','appraisal_result','appraised_by','comment']),
}
LISTS = ['dept', 'branch', 'pos']

ACTION_LABEL = {
    'save':'บันทึก/แก้ไขข้อมูล','post':'เพิ่มข้อมูลใหม่','put':'แก้ไขข้อมูล',
    'delete':'ลบข้อมูล','view':'ดูข้อมูล','view_logs':'ดู Log','login':'เข้าสู่ระบบ','logout':'ออกจากระบบ',
}
TABLE_LABEL = {
    'employees':'ข้อมูลพนักงาน','contracts':'สัญญา','children':'บุตร',
    'warnings':'ใบเตือน','promotions':'การเลื่อนตำแหน่ง','certificates':'หนังสือรับรอง',
    'appraisals':'การประเมิน','lists':'รายการตั้งค่า','system':'ระบบ',
}

# ─── DB ───────────────────────────────────────────────────────────────────────
def connect(path):
    db = sqlite3.connect(path, check_same_thread=False)
    db.execute('PRAGMA journal_mode=WAL'); db.execute('PRAGMA foreign_keys=ON')
    db.execute('CREATE TABLE IF NOT EXISTS employees(' + ','.join(c + (' TEXT PRIMARY KEY' if c == 'id' else " TEXT NOT NULL DEFAULT ''") for c in EMP) + ',updated_at TEXT)')
    for t, cols in REC.values():
        db.execute(f'CREATE TABLE IF NOT EXISTS {t}(rid INTEGER PRIMARY KEY AUTOINCREMENT,' + ','.join(c + " TEXT NOT NULL DEFAULT ''" for c in cols) + ',updated_at TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS lists(kind TEXT,value TEXT,sort INTEGER,PRIMARY KEY(kind,value))')
    db.execute('''CREATE TABLE IF NOT EXISTS audit_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT, client_ip TEXT, action TEXT, table_name TEXT, record_key TEXT, detail TEXT DEFAULT '', user TEXT DEFAULT ''
    )''')
    seed = os.path.join(BASE, 'seed.json')
    if os.path.exists(seed) and db.execute('SELECT COUNT(*) FROM employees').fetchone()[0] == 0:
        d = json.load(open(seed, encoding='utf-8')); now = time.strftime('%Y-%m-%d %H:%M:%S')
        seen, rows = set(), []
        for r in d['emp']:
            if r[0] in seen: print('WARNING: duplicate Emp ID skipped:', r[0]); continue
            seen.add(r[0]); rows.append(r)
        for r in reversed(rows):
            db.execute('INSERT OR IGNORE INTO employees VALUES(' + ','.join('?' * 25) + ')', [str(x) for x in r] + [now])
        for k, (t, cols) in REC.items():
            for r in d.get(k, []):
                db.execute(f'INSERT INTO {t}({",".join(cols)},updated_at) VALUES({",".join("?" * (len(cols)+1))})', [str(x) for x in r] + [now])
        for k in LISTS:
            for i, v in enumerate(d[k]): db.execute('INSERT OR IGNORE INTO lists VALUES(?,?,?)', (k, v, i))
        print('Database created and imported from seed.json')
    db.commit(); return db

# ─── Handler ──────────────────────────────────────────────────────────────────
class H(BaseHTTPRequestHandler):
    server_version = 'HRPortal'

    def log_message(self, *a):
        global REQUEST_COUNT
        with REQUEST_LOCK: REQUEST_COUNT += 1

    def send(self, code, body, ctype='application/json'):
        b = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype + '; charset=utf-8')
        self.send_header('Content-Length', str(len(b)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers(); self.wfile.write(b)

    def err(self, code, msg): self.send(code, {'error': msg})

    def redirect(self, location):
        self.send_response(302)
        self.send_header('Location', location)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def get_token(self):
        cookie = self.headers.get('Cookie', '')
        for part in cookie.split(';'):
            k, _, v = part.strip().partition('=')
            if k.strip() == 'hr_session': return v.strip()
        return None

    def get_user(self):
        return _valid_session(self.get_token() or '')

    def require_auth(self):
        """Returns user string if authenticated, else sends redirect/401 and returns None."""
        user = self.get_user()
        if user: return user
        # API calls get 401 JSON; page requests get redirect to login
        p = urlparse(self.path).path
        if p.startswith('/api/'):
            self.err(401, 'กรุณาเข้าสู่ระบบก่อน')
        else:
            self.redirect('/login')
        return None

    def set_session_cookie(self, token, clear=False):
        if clear:
            self.send_header('Set-Cookie', 'hr_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0')
        else:
            self.send_header('Set-Cookie', f'hr_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL}')

    def audit(self, action, table, key, detail='', user=''):
        DB.execute('INSERT INTO audit_log(ts,client_ip,action,table_name,record_key,detail,user) VALUES(?,?,?,?,?,?,?)',
                   (time.strftime('%Y-%m-%d %H:%M:%S'), self.client_address[0], action, table, str(key), detail, user))

    def body(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > 1_000_000: raise ValueError('Request too large')
        return json.loads(self.rfile.read(n) or b'{}')

    def row(self, cols):
        r = self.body().get('row')
        if not isinstance(r, list) or len(r) != len(cols): raise ValueError('Row must have %d values' % len(cols))
        return [str(x if x is not None else '').strip() for x in r]

    # ── GET ──────────────────────────────────────────────────────────────────
    def do_GET(self):
        p = urlparse(self.path).path
        p_clean = p.rstrip('/') or '/'
        p_lower = p_clean.lower()

        # Public pages (no auth needed)
        if p_lower in ('/login', '/login.html'):
            if self.get_user():
                return self.redirect('/')  # already logged in
            return self.send(200, open(os.path.join(BASE, 'public', 'login.html'), 'rb').read(), 'text/html')

        if p == '/api/health':
            return self.send(200, {'ok': True})

        # Logout
        if p == '/api/logout':
            token = self.get_token()
            user = _valid_session(token or '')
            if token:
                _del_session(token)
                with LOCK:
                    self.audit('logout', 'system', '-', f'ผู้ใช้ {user} ออกจากระบบ', user or '')
                    DB.commit()
            self.send_response(302)
            self.set_session_cookie('', clear=True)
            self.send_header('Location', '/login')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return

        # ── Protected routes ─────────────────────────────────────────────────
        user = self.require_auth()
        if not user: return

        if p_lower in ('/', '/index.html', '/index', '/hrportal', '/portal', '/home', '/main'):
            return self.send(200, open(os.path.join(BASE, 'public', 'index.html'), 'rb').read(), 'text/html')
        if p_lower in ('/admin', '/admin.html'):
            if user != 'admin':
                return self.redirect('/')
            return self.send(200, open(os.path.join(BASE, 'public', 'admin.html'), 'rb').read(), 'text/html')

        if p == '/api/status':
            if user != 'admin':
                return self.err(403, 'เฉพาะ Admin เท่านั้น')
            uptime_sec = int(time.time() - START_TIME)
            h2, rem = divmod(uptime_sec, 3600); m2, s2 = divmod(rem, 60)
            with LOCK:
                emp_count = DB.execute('SELECT COUNT(*) FROM employees').fetchone()[0]
                today_logs = DB.execute("SELECT COUNT(*) FROM audit_log WHERE ts >= date('now')||' 00:00:00'").fetchone()[0]
                total_logs = DB.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0]
            return self.send(200, {
                'running': True, 'user': user,
                'uptime': f'{h2:02d}:{m2:02d}:{s2:02d}', 'uptime_sec': uptime_sec,
                'start_time': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(START_TIME)),
                'db_path': DB_PATH, 'employees': emp_count,
                'requests_total': REQUEST_COUNT,
                'logs_today': today_logs, 'logs_total': total_logs,
            })

        if p == '/api/logs':
            if user != 'admin':
                return self.err(403, 'เฉพาะ Admin เท่านั้น')
            qs = parse_qs(urlparse(self.path).query)
            limit = min(int(qs.get('limit', ['200'])[0]), 1000)
            offset = int(qs.get('offset', ['0'])[0])
            action_f = qs.get('action', [''])[0]
            table_f  = qs.get('table',  [''])[0]
            with LOCK:
                where, params = [], []
                if action_f: where.append('action=?'); params.append(action_f)
                if table_f:  where.append('table_name=?'); params.append(table_f)
                sql = 'SELECT id,ts,client_ip,action,table_name,record_key,detail,user FROM audit_log'
                if where: sql += ' WHERE ' + ' AND '.join(where)
                sql += ' ORDER BY id DESC LIMIT ? OFFSET ?'
                rows = DB.execute(sql, params + [limit, offset]).fetchall()
                total = DB.execute('SELECT COUNT(*) FROM audit_log' + (' WHERE ' + ' AND '.join(where) if where else ''), params).fetchone()[0]
            self.audit('view_logs', 'system', '-', '', user); DB.commit()
            return self.send(200, {
                'total': total, 'offset': offset, 'limit': limit,
                'action_label': ACTION_LABEL, 'table_label': TABLE_LABEL,
                'rows': [{'id':r[0],'ts':r[1],'ip':r[2],'action':r[3],'table':r[4],'key':r[5],'detail':r[6],'user':r[7]} for r in rows]
            })

        if p == '/api/data':
            with LOCK:
                out = {
                    'user': user,
                    'isAdmin': (user == 'admin'),
                    'emp': [list(r) for r in DB.execute(f'SELECT {",".join(EMP)} FROM employees ORDER BY rowid DESC')]
                }
                for k, (t, cols) in REC.items():
                    out[k] = [{'rid': r[0], 'row': list(r[1:])} for r in DB.execute(f'SELECT rid,{",".join(cols)} FROM {t} ORDER BY rid')]
                for k in LISTS: out[k] = [r[0] for r in DB.execute('SELECT value FROM lists WHERE kind=? ORDER BY sort', (k,))]
            return self.send(200, out)

        if not p.startswith('/api/'):
            return self.redirect('/')
        self.err(404, 'Not found')

    # ── POST / PUT / DELETE ───────────────────────────────────────────────────
    def route(self, method):
        p = urlparse(self.path).path
        parts = [unquote(x) for x in p.strip('/').split('/')]

        # ── Login (public) ────────────────────────────────────────────────────
        if parts[0] == 'api' and parts[1] == 'login' and method == 'POST':
            try:
                b = self.body()
                uname = str(b.get('username', '')).strip().lower()
                pw    = str(b.get('password', ''))
                expected = USERS.get(uname)
                if expected and secrets.compare_digest(expected, _h(pw)):
                    token = _new_session(uname)
                    with LOCK:
                        self.audit('login', 'system', uname, f'เข้าสู่ระบบสำเร็จ จาก {self.client_address[0]}', uname)
                        DB.commit()
                    self.send_response(200)
                    self.set_session_cookie(token)
                    body = json.dumps({'ok': True, 'user': uname}, ensure_ascii=False).encode()
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers(); self.wfile.write(body)
                else:
                    with LOCK:
                        self.audit('login', 'system', uname or '?', f'รหัสผ่านผิด จาก {self.client_address[0]}', '')
                        DB.commit()
                    self.err(401, 'ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง')
            except Exception as e:
                self.err(400, str(e))
            return

        # ── Protected ─────────────────────────────────────────────────────────
        user = self.require_auth()
        if not user: return

        try:
            if parts[0] != 'api': return self.err(404, 'Not found')
            with LOCK:
                if parts[1] == 'employee' and method == 'PUT' and len(parts) == 3:
                    eid, r = parts[2], self.row(EMP)
                    if not re.fullmatch(r'[A-Za-z0-9_-]+', eid) or r[0] != eid: raise ValueError('Invalid Emp ID')
                    if not r[2]: raise ValueError('Name is required')
                    now = time.strftime('%Y-%m-%d %H:%M:%S')
                    is_new = DB.execute('SELECT 1 FROM employees WHERE id=?', (eid,)).fetchone() is None
                    DB.execute('INSERT OR REPLACE INTO employees VALUES(' + ','.join('?'*25) + ')', r + [now])
                    detail = f"{'เพิ่มพนักงานใหม่' if is_new else 'แก้ไขข้อมูล'}: {r[2]} (ID: {eid})"
                    self.audit('save', 'employees', eid, detail, user); DB.commit()
                    return self.send(200, {'ok': True})

                if parts[1] == 'employee' and method == 'DELETE' and len(parts) == 3:
                    if user != 'admin':
                        return self.err(403, 'เฉพาะ Admin เท่านั้นที่สามารถลบข้อมูลพนักงานได้')
                    eid = parts[2]
                    en = DB.execute('SELECT name FROM employees WHERE id=?', (eid,)).fetchone()
                    if not en: raise ValueError('Employee not found')
                    emp_name = en[0]
                    DB.execute('DELETE FROM employees WHERE id=?', (eid,))
                    for t, _ in REC.values():
                        DB.execute(f'DELETE FROM {t} WHERE emp_id=?', (eid,))
                    detail = f"ลบข้อมูลพนักงาน: {emp_name} (ID: {eid})"
                    self.audit('delete', 'employees', eid, detail, user); DB.commit()
                    return self.send(200, {'ok': True})

                if parts[1] == 'lists' and method == 'PUT':
                    b = self.body(); DB.execute('DELETE FROM lists')
                    for k in LISTS:
                        for i, v in enumerate(dict.fromkeys(str(x).strip() for x in b[k] if str(x).strip())):
                            DB.execute('INSERT INTO lists VALUES(?,?,?)', (k, v, i))
                    self.audit('save', 'lists', '-', 'แก้ไขรายการตั้งค่า', user); DB.commit()
                    return self.send(200, {'ok': True})

                if parts[1] in REC:
                    t, cols = REC[parts[1]]; now = time.strftime('%Y-%m-%d %H:%M:%S')
                    if method in ('POST', 'PUT'):
                        r = self.row(cols)
                        if not DB.execute('SELECT 1 FROM employees WHERE id=?', (r[0],)).fetchone(): raise ValueError('EMP ID not found')
                        en = DB.execute('SELECT name FROM employees WHERE id=?', (r[0],)).fetchone()
                        emp_name = en[0] if en else r[0]
                        if method == 'POST':
                            if t == 'children' and DB.execute('SELECT COUNT(*) FROM children WHERE emp_id=?', (r[0],)).fetchone()[0] >= 5:
                                raise ValueError('Maximum 5 children per employee')
                            cur = DB.execute(f'INSERT INTO {t}({",".join(cols)},updated_at) VALUES({",".join("?"*(len(cols)+1))})', r + [now])
                            rid = cur.lastrowid
                            detail = f"เพิ่ม {TABLE_LABEL.get(t,t)} ของ {emp_name}"
                        else:
                            rid = int(parts[2])
                            DB.execute(f'UPDATE {t} SET {",".join(c+"=?" for c in cols)},updated_at=? WHERE rid=?', r + [now, rid])
                            detail = f"แก้ไข {TABLE_LABEL.get(t,t)} ของ {emp_name}"
                        self.audit(method.lower(), t, rid, detail, user); DB.commit()
                        return self.send(200, {'ok': True, 'rid': rid})
                    if method == 'DELETE':
                        row_data = DB.execute(f'SELECT emp_id FROM {t} WHERE rid=?', (int(parts[2]),)).fetchone()
                        emp_name = ''
                        if row_data:
                            en = DB.execute('SELECT name FROM employees WHERE id=?', (row_data[0],)).fetchone()
                            emp_name = en[0] if en else row_data[0]
                        DB.execute(f'DELETE FROM {t} WHERE rid=?', (int(parts[2]),))
                        self.audit('delete', t, parts[2], f"ลบ {TABLE_LABEL.get(t,t)} ของ {emp_name}", user); DB.commit()
                        return self.send(200, {'ok': True})
            self.err(404, 'Not found')
        except (ValueError, KeyError, IndexError, json.JSONDecodeError) as e:
            DB.rollback(); self.err(400, str(e))
        except Exception as e:
            DB.rollback(); self.err(500, 'Server error: %s' % e)

    do_POST = lambda s: s.route('POST')
    do_PUT  = lambda s: s.route('PUT')
    do_DELETE = lambda s: s.route('DELETE')

# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='0.0.0.0')
    ap.add_argument('--port', type=int, default=8080)
    ap.add_argument('--db', default=os.path.join(BASE, 'hr_portal.db'))
    a = ap.parse_args(); DB_PATH = a.db; DB = connect(a.db)
    print(f'HR Master Portal running on http://{a.host}:{a.port}  (database: {a.db})  Ctrl+C to stop')
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()
