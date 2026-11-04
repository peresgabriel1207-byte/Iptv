#!/usr/bin/env python3
"""Servidor Xtream Codes minimo (stdlib) que le as listas .m3u8 do repositorio.

- Indexa os *.m3u8 da raiz de DATA_DIR num SQLite (reindexa sozinho quando mudam).
- Classifica: /movie/ -> filmes, /series/ -> episodios (agrupados em series por "Nome SxxExx"),
  o resto -> canais ao vivo.
- Reproducao redireciona (302) para a URL original: o servidor nao gasta banda de video.
- Se DATA_DIR for um repositorio git, faz `git pull` periodico.
"""
import glob
import hashlib
import hmac
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_DIR = os.environ.get("DB_DIR", "/db")
PORT = int(os.environ.get("PORT", "8080"))
USER = os.environ.get("XTREAM_USER", "")
PASS = os.environ.get("XTREAM_PASS", "")
PULL_MIN = int(os.environ.get("GIT_PULL_INTERVAL_MIN", "360"))
CHECK_SEC = int(os.environ.get("REINDEX_CHECK_SEC", "600"))
SCHEMA_VERSION = "1"

EP_RE = re.compile(r"^(.*?)[\s\-_]*[Ss](\d{1,2})\s*[Ee](\d{1,3})")
ATTR_RE = re.compile(r'([A-Za-z0-9_-]+)="([^"]*)"')
LOCK = threading.Lock()
STATE = {"db": None, "indexing": False}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- indexacao
def source_files():
    return sorted(glob.glob(os.path.join(DATA_DIR, "*.m3u8")) + glob.glob(os.path.join(DATA_DIR, "*.m3u")))


def signature():
    h = hashlib.sha1(SCHEMA_VERSION.encode())
    for f in source_files():
        st = os.stat(f)
        h.update(f"{os.path.basename(f)}:{st.st_size}:{int(st.st_mtime)}".encode())
    return h.hexdigest()


def parse_extinf(line):
    rest = line.split(":", 1)[1] if ":" in line else ""
    attrs = dict(ATTR_RE.findall(rest))
    if '",' in rest:
        name = rest.rsplit('",', 1)[1]
    elif "," in rest:
        name = rest.split(",", 1)[1]
    else:
        name = ""
    name = name.strip() or attrs.get("tvg-name", "").strip()
    return name, attrs


def build_index(path):
    t0 = time.time()
    if os.path.exists(path):
        os.remove(path)
    db = sqlite3.connect(path)
    db.executescript(
        """
        PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
        CREATE TABLE cats(id INTEGER PRIMARY KEY, type TEXT, name TEXT, UNIQUE(type,name));
        CREATE TABLE series(id INTEGER PRIMARY KEY, name TEXT, logo TEXT, cat_id INTEGER, UNIQUE(name,cat_id));
        CREATE TABLE streams(id INTEGER PRIMARY KEY, type TEXT, name TEXT, logo TEXT, epg TEXT,
                             cat_id INTEGER, url TEXT UNIQUE, ext TEXT, series_id INTEGER,
                             season INTEGER, episode INTEGER);
        CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);
        """
    )
    cat_cache, ser_cache = {}, {}

    def cat(kind, name):
        key = (kind, name)
        if key not in cat_cache:
            db.execute("INSERT OR IGNORE INTO cats(type,name) VALUES(?,?)", key)
            cat_cache[key] = db.execute("SELECT id FROM cats WHERE type=? AND name=?", key).fetchone()[0]
        return cat_cache[key]

    def serie(name, logo, cid):
        key = (name, cid)
        if key not in ser_cache:
            db.execute("INSERT OR IGNORE INTO series(name,logo,cat_id) VALUES(?,?,?)", (name, logo, cid))
            ser_cache[key] = db.execute("SELECT id FROM series WHERE name=? AND cat_id=?", key).fetchone()[0]
        return ser_cache[key]

    batch, total = [], 0
    for f in source_files():
        pending = None
        with open(f, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if line.startswith("#EXTINF"):
                    pending = parse_extinf(line)
                elif line and not line.startswith("#") and pending:
                    name, a = pending
                    pending = None
                    url = line
                    group = a.get("group-title", "").strip() or "Sem categoria"
                    logo = a.get("tvg-logo", "")
                    ext = url.rsplit(".", 1)[-1].lower() if re.search(r"\.[A-Za-z0-9]{2,4}$", url) else "ts"
                    kind, sid, season, ep = "live", None, None, None
                    if "/series/" in url:
                        m = EP_RE.match(name)
                        if m:
                            kind = "episode"
                            cid = cat("series", group)
                            sid = serie(m.group(1).strip() or name, logo, cid)
                            season, ep = int(m.group(2)), int(m.group(3))
                        else:
                            kind = "movie"
                    elif "/movie/" in url:
                        kind = "movie"
                    if kind == "episode":
                        cid = cat("series", group)
                    else:
                        cid = cat("movie" if kind == "movie" else "live", group)
                    batch.append((kind, name, logo, a.get("tvg-id", ""), cid, url, ext, sid, season, ep))
                    total += 1
                    if len(batch) >= 20000:
                        db.executemany(
                            "INSERT OR IGNORE INTO streams(type,name,logo,epg,cat_id,url,ext,series_id,season,episode)"
                            " VALUES(?,?,?,?,?,?,?,?,?,?)", batch)
                        batch.clear()
        log("indexado", os.path.basename(f), "total parcial", total)
    if batch:
        db.executemany(
            "INSERT OR IGNORE INTO streams(type,name,logo,epg,cat_id,url,ext,series_id,season,episode)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)", batch)
    db.executescript(
        """
        CREATE INDEX i_streams_type_cat ON streams(type,cat_id);
        CREATE INDEX i_streams_series ON streams(series_id);
        CREATE INDEX i_series_cat ON series(cat_id);
        """
    )
    db.execute("INSERT INTO meta VALUES('sig',?)", (signature(),))
    db.commit()
    n = {k: db.execute("SELECT COUNT(*) FROM streams WHERE type=?", (k,)).fetchone()[0] for k in ("live", "movie", "episode")}
    n["series"] = db.execute("SELECT COUNT(*) FROM series").fetchone()[0]
    db.close()
    log(f"indice pronto em {time.time() - t0:.0f}s:", n)


def current_sig(path):
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        row = db.execute("SELECT v FROM meta WHERE k='sig'").fetchone()
        db.close()
        return row[0] if row else None
    except sqlite3.Error:
        return None


def ensure_index():
    os.makedirs(DB_DIR, exist_ok=True)
    live = os.path.join(DB_DIR, "index.sqlite")
    sig = signature()
    if current_sig(live) == sig:
        STATE["db"] = live
        return False
    tmp = os.path.join(DB_DIR, "index.building.sqlite")
    STATE["indexing"] = True
    try:
        build_index(tmp)
        os.replace(tmp, live)
        STATE["db"] = live
    finally:
        STATE["indexing"] = False
    return True


def git_pull():
    if not os.path.isdir(os.path.join(DATA_DIR, ".git")):
        return
    cmd = ["git", "-c", "safe.directory=*", "-C", DATA_DIR, "pull", "--ff-only", "--quiet"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    log("git pull:", "ok" if r.returncode == 0 else "falhou: " + r.stderr.strip()[:300])


def background():
    last_pull = 0
    while True:
        time.sleep(CHECK_SEC)
        try:
            if PULL_MIN > 0 and time.time() - last_pull > PULL_MIN * 60:
                last_pull = time.time()
                git_pull()
            with LOCK:
                ensure_index()
        except Exception as e:  # noqa
            log("erro no ciclo de atualizacao:", e)


# ---------------------------------------------------------------------- API
def db_conn():
    return sqlite3.connect(f"file:{STATE['db']}?mode=ro", uri=True)


def ok_auth(u, p):
    return hmac.compare_digest(u or "", USER) and hmac.compare_digest(p or "", PASS)


def auth_info(host):
    now = int(time.time())
    hostname, _, port = host.partition(":")
    return {
        "user_info": {"username": USER, "password": PASS, "message": "", "auth": 1, "status": "Active",
                      "exp_date": None, "is_trial": "0", "active_cons": "0", "created_at": str(now),
                      "max_connections": "5", "allowed_output_formats": ["m3u8", "ts"]},
        "server_info": {"url": hostname, "port": port or "80", "https_port": "", "server_protocol": "http",
                        "rtmp_port": "", "timezone": "UTC", "timestamp_now": now,
                        "time_now": time.strftime("%Y-%m-%d %H:%M:%S")},
    }


def stream_json(handler, rows, fn):
    """Escreve um array JSON sem montar tudo na memoria (com gzip se o app aceitar)."""
    gz = "gzip" in handler.headers.get("Accept-Encoding", "")
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    if gz:
        handler.send_header("Content-Encoding", "gzip")
    handler.send_header("Connection", "close")
    handler.end_headers()
    comp = zlib.compressobj(6, zlib.DEFLATED, 31) if gz else None
    buf = []

    def flush(final=False):
        data = "".join(buf).encode()
        buf.clear()
        if comp:
            data = comp.compress(data) + (comp.flush() if final else b"")
        if data:
            handler.wfile.write(data)

    buf.append("[")
    for i, r in enumerate(rows, 1):
        buf.append(("" if i == 1 else ",") + json.dumps(fn(i, r), ensure_ascii=False))
        if i % 500 == 0:
            flush()
    buf.append("]")
    flush(True)


class H(BaseHTTPRequestHandler):
    server_version = "xtream-m3u/1.0"

    def log_message(self, fmt, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _text(self, txt, code=200, ctype="text/plain; charset=utf-8"):
        b = txt.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        path = u.path
        try:
            if path == "/health":
                return self._json({"ok": STATE["db"] is not None, "indexing": STATE["indexing"]})
            if STATE["db"] is None:
                return self._text("Indexando as listas, tente de novo em alguns minutos.", 503)
            if path in ("/player_api.php", "/panel_api.php"):
                return self.api(q)
            if path == "/get.php":
                return self.get_m3u(q)
            if path == "/xmltv.php":
                if not ok_auth(q.get("username"), q.get("password")):
                    return self._text("Unauthorized", 401)
                return self._text('<?xml version="1.0" encoding="UTF-8"?><tv generator-info-name="xtream-m3u"></tv>',
                                  ctype="application/xml")
            m = re.match(r"^/(?:(live|movie|series)/)?([^/]+)/([^/]+)/(\d+)(?:\.[A-Za-z0-9]+)?$", path)
            if m:
                return self.play(m.group(2), m.group(3), int(m.group(4)))
            return self._text("Not found", 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # noqa
            log("erro:", path, e)
            try:
                self._text("Internal error", 500)
            except Exception:
                pass

    def play(self, u, p, sid):
        if not ok_auth(u, p):
            return self._text("Unauthorized", 401)
        db = db_conn()
        row = db.execute("SELECT url FROM streams WHERE id=?", (sid,)).fetchone()
        db.close()
        if not row:
            return self._text("Not found", 404)
        self.send_response(302)
        self.send_header("Location", row[0])
        self.send_header("Content-Length", "0")
        self.end_headers()

    def api(self, q):
        if not ok_auth(q.get("username"), q.get("password")):
            return self._json({"user_info": {"auth": 0}}, 401)
        act = q.get("action")
        host = self.headers.get("Host", "localhost")
        if not act:
            return self._json(auth_info(host))
        db = db_conn()
        cid = q.get("category_id")
        try:
            if act in ("get_live_categories", "get_vod_categories", "get_series_categories"):
                kind = {"get_live_categories": "live", "get_vod_categories": "movie", "get_series_categories": "series"}[act]
                rows = db.execute("SELECT id,name FROM cats WHERE type=? ORDER BY name", (kind,)).fetchall()
                return self._json([{"category_id": str(i), "category_name": n, "parent_id": 0} for i, n in rows])
            if act == "get_live_streams":
                sql, args = "SELECT id,name,logo,epg,cat_id FROM streams WHERE type='live'", []
                if cid:
                    sql += " AND cat_id=?"; args.append(cid)
                return stream_json(self, db.execute(sql, args), lambda i, r: {
                    "num": i, "name": r[1], "stream_type": "live", "stream_id": r[0], "stream_icon": r[2],
                    "epg_channel_id": r[3], "added": "0", "category_id": str(r[4]), "custom_sid": "",
                    "tv_archive": 0, "direct_source": "", "tv_archive_duration": 0})
            if act == "get_vod_streams":
                sql, args = "SELECT id,name,logo,cat_id,ext FROM streams WHERE type='movie'", []
                if cid:
                    sql += " AND cat_id=?"; args.append(cid)
                return stream_json(self, db.execute(sql, args), lambda i, r: {
                    "num": i, "name": r[1], "stream_type": "movie", "stream_id": r[0], "stream_icon": r[2],
                    "rating": "0", "rating_5based": 0, "added": "0", "category_id": str(r[3]),
                    "container_extension": r[4], "custom_sid": "", "direct_source": ""})
            if act == "get_vod_info":
                r = db.execute("SELECT id,name,logo,cat_id,ext FROM streams WHERE id=?", (q.get("vod_id"),)).fetchone()
                if not r:
                    return self._json({"info": {}, "movie_data": {}})
                return self._json({"info": {"name": r[1], "movie_image": r[2], "cover_big": r[2]},
                                   "movie_data": {"stream_id": r[0], "name": r[1], "added": "0",
                                                  "category_id": str(r[3]), "container_extension": r[4],
                                                  "direct_source": ""}})
            if act == "get_series":
                sql, args = "SELECT id,name,logo,cat_id FROM series", []
                if cid:
                    sql += " WHERE cat_id=?"; args.append(cid)
                return stream_json(self, db.execute(sql + " ORDER BY name", args), lambda i, r: {
                    "num": i, "name": r[1], "series_id": r[0], "cover": r[2], "plot": "", "cast": "",
                    "director": "", "genre": "", "releaseDate": "", "last_modified": "0", "rating": "0",
                    "rating_5based": 0, "backdrop_path": [], "youtube_trailer": "", "episode_run_time": "0",
                    "category_id": str(r[3])})
            if act == "get_series_info":
                s = db.execute("SELECT id,name,logo,cat_id FROM series WHERE id=?", (q.get("series_id"),)).fetchone()
                if not s:
                    return self._json({"seasons": [], "info": {}, "episodes": {}})
                eps = db.execute("SELECT id,name,logo,ext,season,episode FROM streams WHERE series_id=?"
                                 " ORDER BY season,episode", (s[0],)).fetchall()
                out, seasons = {}, []
                for sid, name, logo, ext, se, ep in eps:
                    out.setdefault(str(se), []).append({
                        "id": str(sid), "episode_num": ep, "title": name, "container_extension": ext,
                        "info": {"movie_image": logo}, "custom_sid": "", "added": "0", "season": se,
                        "direct_source": ""})
                for se in out:
                    seasons.append({"season_number": int(se), "name": f"Temporada {se}", "episode_count": len(out[se]),
                                    "overview": "", "cover": s[2], "cover_big": s[2]})
                return self._json({"seasons": seasons,
                                   "info": {"name": s[1], "cover": s[2], "category_id": str(s[3])},
                                   "episodes": out})
            return self._json([])
        finally:
            db.close()

    def get_m3u(self, q):
        if not ok_auth(q.get("username"), q.get("password")):
            return self._text("Unauthorized", 401)
        db = db_conn()
        kinds = q.get("type_filter")  # live | movie | episode (opcional)
        sql = ("SELECT s.name,s.logo,s.epg,c.name,s.url FROM streams s JOIN cats c ON c.id=s.cat_id")
        args = []
        where = []
        if kinds:
            where.append("s.type=?"); args.append(kinds)
        if q.get("category"):
            where.append("c.name=?"); args.append(q["category"])
        if where:
            sql += " WHERE " + " AND ".join(where)
        self.send_response(200)
        self.send_header("Content-Type", "audio/x-mpegurl; charset=utf-8")
        self.send_header("Connection", "close")
        self.end_headers()
        w = self.wfile
        w.write(b"#EXTM3U\n")
        for name, logo, epg, grp, url in db.execute(sql, args):
            w.write(f'#EXTINF:-1 tvg-id="{epg}" tvg-name="{name}" tvg-logo="{logo}" group-title="{grp}",{name}\n{url}\n'.encode())
        db.close()


def main():
    if not USER or not PASS:
        sys.exit("Defina XTREAM_USER e XTREAM_PASS (veja .env.example).")
    if PASS in ("troque-esta-senha", "changeme", "123456"):
        sys.exit("Troque XTREAM_PASS por uma senha forte.")
    log("lendo listas de", DATA_DIR, "->", [os.path.basename(f) for f in source_files()])

    def first_index():
        try:
            with LOCK:
                ensure_index()
        except Exception as e:  # noqa
            log("falha ao indexar:", e)
        threading.Thread(target=background, daemon=True).start()

    # se ja existe indice valido, sobe na hora; senao indexa em segundo plano
    live = os.path.join(DB_DIR, "index.sqlite")
    os.makedirs(DB_DIR, exist_ok=True)
    if current_sig(live) == signature():
        STATE["db"] = live
    threading.Thread(target=first_index, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    log(f"servidor Xtream em http://0.0.0.0:{PORT}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
