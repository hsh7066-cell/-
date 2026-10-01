"""밸브 조작 상태 공유 서버 (인터넷 불필요, 파이썬 기본 기능만 사용).

실행:  python server.py
  - 같은 Wi-Fi/사내망에 연결된 휴대폰에서 화면에 표시되는 주소(http://192.168.x.x:8000)로 접속
  - 처음 실행하면 관리자 계정(admin)과 임시 비밀번호가 화면에 한 번 표시됩니다.
  - 관리자 비밀번호를 잊었을 때:  python server.py --reset-admin

데이터는 같은 폴더의 valve.db(SQLite) 파일 하나에 모두 저장됩니다. 이 파일을 백업하세요.
"""
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import socket
import sqlite3
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "valve.db")
STATIC_DIR = os.path.join(HERE, "static")
SEED_CSV = os.path.join(HERE, "valves.csv")
PORT = int(os.environ.get("VALVE_PORT", "8000"))

SESSION_HOURS = 12            # 로그인 유지 시간
REQUIRE_TWO_PERSON = True     # True: 조작한 사람과 다른 사람이 확인해야 '확인완료'
MAX_LOGIN_FAILS = 5           # 비밀번호 연속 실패 허용 횟수
LOCK_SECONDS = 300            # 초과 시 잠금 시간(초)

STATES = ("OPEN", "CLOSE")
CSV_COLUMNS = ["순번", "구역", "밸브명", "도면번호", "요구상태", "요청사항",
               "작업책임자", "연락처", "개방일시", "투입일시"]

db_lock = threading.Lock()
login_fails = {}  # login -> (count, locked_until)


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hash_pw(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()


def connect():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


DB = None


def init_db():
    global DB
    DB = connect()
    DB.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, login TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
        dept TEXT DEFAULT '', role TEXT NOT NULL DEFAULT 'user',
        salt TEXT NOT NULL, pw_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
        must_change_pw INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
        expires REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS valves (
        id INTEGER PRIMARY KEY, seq INTEGER, area TEXT, tag TEXT NOT NULL, pid TEXT,
        target TEXT, note TEXT, owner TEXT, phone TEXT, work_start TEXT, work_end TEXT,
        current TEXT NOT NULL DEFAULT '미확인',
        status TEXT NOT NULL DEFAULT '미조작',
        operated_by TEXT DEFAULT '', operated_by_id INTEGER, operated_at TEXT DEFAULT '',
        verified_by TEXT DEFAULT '', verified_at TEXT DEFAULT '',
        rev INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY, valve_id INTEGER REFERENCES valves(id), ts TEXT NOT NULL,
        user_id INTEGER, user_name TEXT, kind TEXT NOT NULL,
        from_state TEXT, to_state TEXT, memo TEXT DEFAULT '');
    """)
    DB.commit()
    if DB.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        pw = create_or_reset_admin()
        print("=" * 60)
        print(" 최초 관리자 계정이 만들어졌습니다.")
        print(f"   아이디: admin   임시 비밀번호: {pw}")
        print(" 첫 로그인 후 비밀번호를 바꾸라는 화면이 나옵니다.")
        print("=" * 60)
    if DB.execute("SELECT COUNT(*) FROM valves").fetchone()[0] == 0 and os.path.exists(SEED_CSV):
        with open(SEED_CSV, encoding="utf-8-sig") as f:
            n = import_valves(f.read(), None, "최초 등록")
        print(f" valves.csv 에서 밸브 {n}개를 등록했습니다.")


def create_or_reset_admin():
    pw = secrets.token_urlsafe(6)
    salt = secrets.token_hex(16)
    row = DB.execute("SELECT id FROM users WHERE login='admin'").fetchone()
    if row:
        DB.execute("UPDATE users SET salt=?, pw_hash=?, active=1, role='admin', must_change_pw=1 "
                   "WHERE id=?", (salt, hash_pw(pw, salt), row["id"]))
        DB.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
    else:
        DB.execute("INSERT INTO users(login,name,dept,role,salt,pw_hash,created_at) "
                   "VALUES('admin','관리자','','admin',?,?,?)", (salt, hash_pw(pw, salt), now()))
    DB.commit()
    return pw


def norm_state(s):
    s = (s or "").strip().upper().replace(" ", "")
    if s in ("OPEN", "열림", "개방") or s.startswith("OP"):
        return "OPEN"
    if s in ("CLOSE", "CLOSED", "닫힘", "폐쇄") or s.startswith("CLO"):
        return "CLOSE"
    return ""


def import_valves(csv_text, user, memo):
    """CSV 내용으로 밸브 목록을 교체. 기존 밸브는 숨김(active=0) 처리되어 이력은 남습니다."""
    rows = [r for r in csv.DictReader(io.StringIO(csv_text)) if (r.get("밸브명") or "").strip()]
    if not rows:
        raise ValueError("CSV에 밸브가 없습니다. 첫 줄 제목에 '밸브명' 열이 있어야 합니다.")
    ts = now()
    DB.execute("UPDATE valves SET active=0 WHERE active=1")
    for i, r in enumerate(rows, start=1):
        g = lambda k: (r.get(k) or "").strip()
        seq = int(g("순번")) if g("순번").isdigit() else i
        cur = DB.execute(
            "INSERT INTO valves(seq,area,tag,pid,target,note,owner,phone,work_start,work_end) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (seq, g("구역"), g("밸브명"), g("도면번호"), norm_state(g("요구상태")), g("요청사항"),
             g("작업책임자"), g("연락처"), g("개방일시"), g("투입일시")))
        DB.execute("INSERT INTO events(valve_id,ts,user_id,user_name,kind,to_state,memo) "
                   "VALUES(?,?,?,?,?,?,?)",
                   (cur.lastrowid, ts, user["id"] if user else None,
                    user["name"] if user else "시스템", "등록", norm_state(g("요구상태")), memo))
    DB.commit()
    return len(rows)


def valve_dict(r):
    d = dict(r)
    d.pop("operated_by_id", None)
    return d


def user_public(u):
    return {k: u[k] for k in ("id", "login", "name", "dept", "role", "active", "must_change_pw",
                              "created_at")}


class Handler(BaseHTTPRequestHandler):
    server_version = "ValveServer/1.0"

    # ---------- 공통 ----------
    def log_message(self, fmt, *args):
        if "/api/valves" in (args[0] if args else "") and self.command == "GET":
            return  # 5초마다 오는 새로고침 요청은 화면에 찍지 않음
        sys.stderr.write("%s [%s] %s\n" % (self.client_address[0], now(), fmt % args))

    def send_json(self, obj, code=200, headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def err(self, msg, code=400):
        self.send_json({"error": msg}, code)

    def body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 5_000_000:
            raise ValueError("요청이 너무 큽니다")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def current_user(self):
        cookie = self.headers.get("Cookie") or ""
        m = re.search(r"(?:^|;\s*)vs_token=([A-Za-z0-9_\-]+)", cookie)
        if not m:
            return None
        row = DB.execute(
            "SELECT u.*, s.token FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.token=? AND s.expires>? AND u.active=1", (m.group(1), time.time())).fetchone()
        return dict(row) if row else None

    def send_file(self, path, ctype):
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_csv(self, filename, header, rows):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)
        w.writerows(rows)
        data = ("﻿" + buf.getvalue()).encode("utf-8")  # 엑셀 한글 깨짐 방지
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition",
                         f"attachment; filename*=UTF-8''{quote(filename)}")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ---------- GET ----------
    def do_GET(self):
        url = urlparse(self.path)
        p = url.path
        static = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/manifest.json": ("manifest.json", "application/manifest+json"),
                  "/icon.svg": ("icon.svg", "image/svg+xml")}
        if p in static:
            name, ctype = static[p]
            return self.send_file(os.path.join(STATIC_DIR, name), ctype)

        with db_lock:
            user = self.current_user()
            if not user:
                return self.err("로그인이 필요합니다", 401)
            q = parse_qs(url.query)
            if p == "/api/me":
                return self.send_json(user_public(user))
            if p == "/api/valves":
                rows = DB.execute("SELECT * FROM valves WHERE active=1 ORDER BY seq, id").fetchall()
                ver = DB.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]
                return self.send_json({"version": ver, "server_time": now(),
                                       "valves": [valve_dict(r) for r in rows]})
            if p == "/api/history":
                vid = q.get("valve", [None])[0]
                if vid:
                    rows = DB.execute("SELECT * FROM events WHERE valve_id=? ORDER BY id DESC",
                                      (vid,)).fetchall()
                else:
                    rows = DB.execute(
                        "SELECT e.*, v.tag, v.area FROM events e LEFT JOIN valves v ON v.id=e.valve_id "
                        "WHERE e.kind!='등록' ORDER BY e.id DESC LIMIT 200").fetchall()
                return self.send_json([dict(r) for r in rows])
            if p == "/api/export/history.csv":
                rows = DB.execute(
                    "SELECT e.ts, v.area, v.tag, e.kind, e.from_state, e.to_state, e.user_name, e.memo "
                    "FROM events e LEFT JOIN valves v ON v.id=e.valve_id ORDER BY e.id").fetchall()
                return self.send_csv("밸브조작이력.csv",
                                     ["일시", "구역", "밸브명", "구분", "변경전", "변경후", "작업자", "메모"],
                                     [list(r) for r in rows])
            if p == "/api/export/status.csv":
                rows = DB.execute(
                    "SELECT seq, area, tag, pid, target, current, status, operated_by, operated_at, "
                    "verified_by, verified_at, note FROM valves WHERE active=1 ORDER BY seq, id").fetchall()
                return self.send_csv("밸브현재상태.csv",
                                     ["순번", "구역", "밸브명", "도면번호", "요구상태", "현재상태", "검증",
                                      "조작자", "조작일시", "확인자", "확인일시", "요청사항"],
                                     [list(r) for r in rows])
            if p == "/api/users":
                if user["role"] != "admin":
                    return self.err("관리자만 볼 수 있습니다", 403)
                rows = DB.execute("SELECT * FROM users ORDER BY id").fetchall()
                return self.send_json([user_public(r) for r in rows])
        self.err("없는 주소입니다", 404)

    # ---------- POST ----------
    def do_POST(self):
        p = urlparse(self.path).path
        try:
            data = self.body_json()
        except (ValueError, UnicodeDecodeError):
            return self.err("잘못된 요청입니다")
        with db_lock:
            try:
                return self.route_post(p, data)
            except sqlite3.IntegrityError as e:
                DB.rollback()
                return self.err("이미 있는 값입니다: " + str(e))
            except ValueError as e:
                DB.rollback()
                return self.err(str(e))

    def route_post(self, p, data):
        if p == "/api/login":
            return self.login(data)
        user = self.current_user()
        if not user:
            return self.err("로그인이 필요합니다", 401)
        if p == "/api/logout":
            DB.execute("DELETE FROM sessions WHERE token=?", (user["token"],))
            DB.commit()
            return self.send_json({"ok": True},
                                  headers={"Set-Cookie": "vs_token=; Path=/; Max-Age=0"})
        if p == "/api/password":
            return self.change_password(user, data)
        if user["must_change_pw"]:
            return self.err("먼저 비밀번호를 변경하세요", 403)

        m = re.fullmatch(r"/api/valves/(\d+)/(operate|verify)", p)
        if m:
            vid = int(m.group(1))
            return self.operate(user, vid, data) if m.group(2) == "operate" \
                else self.verify(user, vid, data)

        if user["role"] != "admin":
            return self.err("관리자만 할 수 있습니다", 403)
        if p == "/api/users":
            return self.create_user(data)
        m = re.fullmatch(r"/api/users/(\d+)", p)
        if m:
            return self.update_user(user, int(m.group(1)), data)
        if p == "/api/valves/import":
            n = import_valves(data.get("csv") or "", user, data.get("memo") or "목록 불러오기")
            return self.send_json({"ok": True, "count": n})
        m = re.fullmatch(r"/api/valves/(\d+)/edit", p)
        if m:
            return self.edit_valve(user, int(m.group(1)), data)
        return self.err("없는 주소입니다", 404)

    def login(self, data):
        login = (data.get("login") or "").strip()
        pw = data.get("password") or ""
        cnt, until = login_fails.get(login, (0, 0))
        if until > time.time():
            return self.err(f"비밀번호를 여러 번 틀려 잠겼습니다. {int(until - time.time())}초 후 다시 시도하세요.", 429)
        u = DB.execute("SELECT * FROM users WHERE login=? AND active=1", (login,)).fetchone()
        if not u or not hmac.compare_digest(u["pw_hash"], hash_pw(pw, u["salt"])):
            cnt += 1
            login_fails[login] = (0, time.time() + LOCK_SECONDS) if cnt >= MAX_LOGIN_FAILS else (cnt, 0)
            return self.err("아이디 또는 비밀번호가 틀렸습니다", 401)
        login_fails.pop(login, None)
        token = secrets.token_urlsafe(32)
        DB.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
        DB.execute("INSERT INTO sessions VALUES(?,?,?)",
                   (token, u["id"], time.time() + SESSION_HOURS * 3600))
        DB.commit()
        return self.send_json(user_public(u), headers={
            "Set-Cookie": f"vs_token={token}; Path=/; HttpOnly; SameSite=Strict; "
                          f"Max-Age={SESSION_HOURS * 3600}"})

    def change_password(self, user, data):
        old, new = data.get("old") or "", data.get("new") or ""
        if not hmac.compare_digest(user["pw_hash"], hash_pw(old, user["salt"])):
            return self.err("현재 비밀번호가 틀렸습니다")
        if len(new) < 6:
            return self.err("새 비밀번호는 6자 이상이어야 합니다")
        salt = secrets.token_hex(16)
        DB.execute("UPDATE users SET salt=?, pw_hash=?, must_change_pw=0 WHERE id=?",
                   (salt, hash_pw(new, salt), user["id"]))
        DB.commit()
        return self.send_json({"ok": True})

    def get_valve(self, vid):
        v = DB.execute("SELECT * FROM valves WHERE id=? AND active=1", (vid,)).fetchone()
        if not v:
            raise ValueError("밸브를 찾을 수 없습니다")
        return v

    def check_rev(self, v, data):
        # 두 사람이 거의 동시에 같은 밸브를 바꾸는 것을 막음
        if int(data.get("rev", -1)) != v["rev"]:
            self.send_json({"error": "다른 사람이 방금 이 밸브 상태를 바꿨습니다. "
                                     "화면을 새로 보고 다시 확인하세요.",
                            "valve": valve_dict(v)}, 409)
            return False
        return True

    def operate(self, user, vid, data):
        v = self.get_valve(vid)
        state = data.get("state")
        if state not in STATES:
            return self.err("상태는 OPEN 또는 CLOSE 만 가능합니다")
        if not self.check_rev(v, data):
            return
        memo = (data.get("memo") or "").strip()
        ts = now()
        DB.execute("UPDATE valves SET current=?, status='확인대기', operated_by=?, operated_by_id=?, "
                   "operated_at=?, verified_by='', verified_at='', rev=rev+1 WHERE id=?",
                   (state, user["name"], user["id"], ts, vid))
        DB.execute("INSERT INTO events(valve_id,ts,user_id,user_name,kind,from_state,to_state,memo) "
                   "VALUES(?,?,?,?,'조작',?,?,?)", (vid, ts, user["id"], user["name"], v["current"],
                                                   state, memo))
        DB.commit()
        return self.send_json({"ok": True, "valve": valve_dict(self.get_valve(vid))})

    def verify(self, user, vid, data):
        v = self.get_valve(vid)
        if v["status"] not in ("확인대기", "불일치"):
            return self.err("확인할 조작이 없습니다")
        if not self.check_rev(v, data):
            return
        if REQUIRE_TWO_PERSON and v["operated_by_id"] == user["id"]:
            return self.err("본인이 조작한 밸브는 다른 사람이 확인해야 합니다")
        ok = bool(data.get("ok"))
        memo = (data.get("memo") or "").strip()
        if not ok and not memo:
            return self.err("불일치일 때는 실제 상태/사유를 메모에 적어주세요")
        ts = now()
        DB.execute("UPDATE valves SET status=?, verified_by=?, verified_at=?, rev=rev+1 WHERE id=?",
                   ("확인완료" if ok else "불일치", user["name"], ts, vid))
        DB.execute("INSERT INTO events(valve_id,ts,user_id,user_name,kind,from_state,to_state,memo) "
                   "VALUES(?,?,?,?,?,?,?,?)",
                   (vid, ts, user["id"], user["name"], "확인" if ok else "불일치",
                    v["current"], v["current"], memo))
        DB.commit()
        return self.send_json({"ok": True, "valve": valve_dict(self.get_valve(vid))})

    def edit_valve(self, user, vid, data):
        v = self.get_valve(vid)
        fields = {"area": "구역", "tag": "밸브명", "pid": "도면번호", "target": "요구상태",
                  "note": "요청사항", "owner": "작업책임자", "phone": "연락처"}
        changes = []
        for k, label in fields.items():
            if k in data:
                val = norm_state(data[k]) if k == "target" else str(data[k]).strip()
                if k == "tag" and not val:
                    return self.err("밸브명은 비울 수 없습니다")
                if val != (v[k] or ""):
                    DB.execute(f"UPDATE valves SET {k}=? WHERE id=?", (val, vid))
                    changes.append(f"{label}: {v[k] or '-'} → {val or '-'}")
        if data.get("reset"):
            DB.execute("UPDATE valves SET current='미확인', status='미조작', operated_by='', "
                       "operated_at='', verified_by='', verified_at='' WHERE id=?", (vid,))
            changes.append("상태 초기화(미확인)")
        if changes:
            DB.execute("UPDATE valves SET rev=rev+1 WHERE id=?", (vid,))
            DB.execute("INSERT INTO events(valve_id,ts,user_id,user_name,kind,memo) "
                       "VALUES(?,?,?,?,'수정',?)", (vid, now(), user["id"], user["name"],
                                                  "; ".join(changes)))
        DB.commit()
        return self.send_json({"ok": True})

    def create_user(self, data):
        login = (data.get("login") or "").strip()
        name = (data.get("name") or "").strip()
        pw = data.get("password") or ""
        if not re.fullmatch(r"[A-Za-z0-9_.\-]{2,30}", login):
            return self.err("아이디는 영문/숫자 2~30자로 정하세요")
        if not name:
            return self.err("이름을 입력하세요")
        if len(pw) < 6:
            return self.err("비밀번호는 6자 이상이어야 합니다")
        salt = secrets.token_hex(16)
        DB.execute("INSERT INTO users(login,name,dept,role,salt,pw_hash,created_at) "
                   "VALUES(?,?,?,?,?,?,?)",
                   (login, name, (data.get("dept") or "").strip(),
                    "admin" if data.get("role") == "admin" else "user",
                    salt, hash_pw(pw, salt), now()))
        DB.commit()
        return self.send_json({"ok": True})

    def update_user(self, me, uid, data):
        u = DB.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not u:
            return self.err("사용자를 찾을 수 없습니다")
        if uid == me["id"] and (data.get("active") is False or data.get("role") == "user"):
            return self.err("본인 계정은 비활성화하거나 관리자 권한을 뺄 수 없습니다")
        for k in ("name", "dept"):
            if k in data:
                DB.execute(f"UPDATE users SET {k}=? WHERE id=?", (str(data[k]).strip(), uid))
        if "role" in data:
            DB.execute("UPDATE users SET role=? WHERE id=?",
                       ("admin" if data["role"] == "admin" else "user", uid))
        if "active" in data:
            DB.execute("UPDATE users SET active=? WHERE id=?", (1 if data["active"] else 0, uid))
            if not data["active"]:
                DB.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        if data.get("password"):
            if len(data["password"]) < 6:
                return self.err("비밀번호는 6자 이상이어야 합니다")
            salt = secrets.token_hex(16)
            DB.execute("UPDATE users SET salt=?, pw_hash=?, must_change_pw=1 WHERE id=?",
                       (salt, hash_pw(data["password"], salt), uid))
            DB.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        DB.commit()
        return self.send_json({"ok": True})


def lan_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # 실제로 전송하지 않음(인터넷 불필요)
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    ips.discard("127.0.0.1")
    return sorted(ips)


def main():
    init_db()
    if "--reset-admin" in sys.argv:
        pw = create_or_reset_admin()
        print(f"admin 비밀번호를 초기화했습니다. 임시 비밀번호: {pw}")
        return
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("\n밸브 상태 공유 서버가 켜졌습니다. (끄려면 Ctrl+C)")
    print(f"  이 PC에서:   http://localhost:{PORT}")
    for ip in lan_ips():
        print(f"  휴대폰에서:  http://{ip}:{PORT}   (같은 Wi-Fi/사내망)")
    print()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")


if __name__ == "__main__":
    main()
