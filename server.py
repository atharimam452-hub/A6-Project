"""
HTTP server + REST API (standard library only).

Run:  python3 server.py            -> http://localhost:8000
Env:  TT_DB=path/to/file.db  PORT=8000
"""
import csv
import io
import json
import mimetypes
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import db
import sample_data
import scheduler

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")
DB_PATH = os.environ.get("TT_DB", os.path.join(BASE, "timetable.db"))
LOCK = threading.Lock()


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- #
def build_problem(conn):
    s = db.get_settings(conn)
    return scheduler.Problem(s["days"], s["periods"], db.list_rows(conn, "faculty"),
                             db.list_rows(conn, "batches"), db.list_rows(conn, "rooms"),
                             db.list_rows(conn, "subjects"))


def current_assignments(conn, p):
    return {sid: a for sid, a in db.get_timetable(conn).items()
            if sid in p.index and a["room_id"] in p.rooms and 0 <= a["slot"] < p.n_slots}


def full_state(conn):
    p = build_problem(conn)
    tt = current_assignments(conn, p)
    return {
        "settings": db.get_settings(conn),
        "faculty": db.list_rows(conn, "faculty"),
        "batches": db.list_rows(conn, "batches"),
        "rooms": db.list_rows(conn, "rooms"),
        "subjects": db.list_rows(conn, "subjects"),
        "sessions": [{k: s[k] for k in ("id", "subject_id", "code", "name", "faculty_id",
                                        "batch_id", "room_type", "size")} for s in p.sessions],
        "timetable": tt,
        "unscheduled": [{"session_id": s["id"], "reason": scheduler.reason(p, i)}
                        for i, s in enumerate(p.sessions) if s["id"] not in tt],
        "conflicts": scheduler.detect_conflicts(p, tt),
    }


def export_csv(conn):
    p = build_problem(conn)
    tt = current_assignments(conn, p)
    labels = db.get_settings(conn)["labels"]
    rows = []
    for sid, a in tt.items():
        s = p.sessions[p.index[sid]]
        rows.append((p.batches[s["batch_id"]]["name"], a["slot"] // p.P, a["slot"] % p.P,
                     s["code"], s["name"], p.faculty[s["faculty_id"]]["name"],
                     p.rooms[a["room_id"]]["name"]))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Batch", "Day", "Period", "Time", "Subject Code", "Subject", "Faculty", "Room"])
    for b, d, per, code, name, fac, room in rows:
        w.writerow([b, p.days[d], per + 1, labels[per] if per < len(labels) else "",
                    code, name, fac, room])
    return out.getvalue()


# --------------------------------------------------------------------------- #
def route(method, path, query, body, conn):
    """Return (status, payload, content_type). Pure function => easy to test."""
    parts = [x for x in path.split("/") if x]
    if not parts or parts[0] != "api":
        raise ApiError("not found", 404)
    parts = parts[1:]

    if method == "GET" and parts == ["state"]:
        return 200, full_state(conn), "json"
    if method == "GET" and parts == ["export.csv"]:
        return 200, export_csv(conn), "csv"

    # ---- CRUD ----
    if parts and parts[0] in db.ENTITIES:
        ent = parts[0]
        try:
            if method == "POST" and len(parts) == 1:
                return 201, {"id": db.insert(conn, ent, body)}, "json"
            if method == "PUT" and len(parts) == 2:
                if not db.update(conn, ent, int(parts[1]), body):
                    raise ApiError("not found", 404)
                return 200, {"ok": True}, "json"
            if method == "DELETE" and len(parts) == 2:
                if not db.delete(conn, ent, int(parts[1])):
                    raise ApiError("not found", 404)
                return 200, {"ok": True}, "json"
        except ValueError as e:
            raise ApiError(str(e))

    if method == "POST" and parts == ["settings"]:
        try:
            days, periods, labels = db.validate_settings(body)
        except ValueError as e:
            raise ApiError(str(e))
        db.set_settings(conn, days, periods, labels)
        db.clear_timetable(conn)  # slot ids change meaning
        return 200, {"ok": True}, "json"

    if method == "POST" and parts == ["generate"]:
        method_name = body.get("method", "backtracking")
        if method_name not in scheduler.METHODS:
            raise ApiError("unknown method")
        p = build_problem(conn)
        if not p.sessions:
            raise ApiError("Add faculty, batches and subjects first")
        res = scheduler.solve(p, method_name, float(body.get("time_limit", 10)))
        db.save_timetable(conn, res["assignments"])
        return 200, {"stats": res["stats"], "unscheduled": res["unscheduled"]}, "json"

    if method == "POST" and parts == ["compare"]:
        p = build_problem(conn)
        if not p.sessions:
            raise ApiError("Add faculty, batches and subjects first")
        results = []
        for m in scheduler.METHODS:
            r = scheduler.solve(p, m, 10)
            r["stats"]["conflicts"] = len(scheduler.detect_conflicts(p, r["assignments"]))
            results.append(r["stats"])
        return 200, {"results": results}, "json"

    if method == "POST" and parts == ["move"]:
        return _move(conn, body)

    if method == "POST" and parts == ["unschedule"]:
        db.remove_placement(conn, str(body.get("session_id", "")))
        return 200, {"ok": True}, "json"

    if method == "POST" and parts == ["clear"]:
        db.clear_timetable(conn)
        return 200, {"ok": True}, "json"

    if method == "POST" and parts == ["seed"]:
        db.seed(conn, sample_data.sample())
        return 200, {"ok": True}, "json"

    raise ApiError("not found", 404)


def _move(conn, body):
    """Manual modification: place/move one session, validating conflicts."""
    p = build_problem(conn)
    sid = str(body.get("session_id", ""))
    if sid not in p.index:
        raise ApiError("unknown session", 404)
    try:
        slot = int(body.get("slot"))
    except (TypeError, ValueError):
        raise ApiError("slot must be a number")
    if not 0 <= slot < p.n_slots:
        raise ApiError("slot out of range")

    tt = current_assignments(conn, p)
    i = p.index[sid]
    room_id = body.get("room_id")
    if room_id is None:  # auto-pick a free compatible room, else keep the current one
        busy = {a["room_id"] for k, a in tt.items() if a["slot"] == slot and k != sid}
        free = [r for r in p.cand_rooms[i] if r not in busy]
        if free:
            room_id = free[0]
        elif sid in tt:
            room_id = tt[sid]["room_id"]
        elif p.cand_rooms[i]:
            room_id = p.cand_rooms[i][0]
        else:
            raise ApiError("No suitable room exists for this session")
    room_id = int(room_id)

    trial = dict(tt)
    trial[sid] = {"slot": slot, "room_id": room_id}
    mine = [c for c in scheduler.detect_conflicts(p, trial) if sid in c["sessions"]]
    if mine and not body.get("force"):
        return 409, {"conflicts": mine}, "json"
    db.set_placement(conn, sid, slot, room_id)
    return 200, {"ok": True, "conflicts": mine}, "json"


# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = "TimetableServer/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, status, payload, kind):
        if kind == "json":
            data = json.dumps(payload).encode()
            ctype = "application/json"
        elif kind == "csv":
            data = payload.encode()
            ctype = "text/csv"
        else:
            data, ctype = payload, kind
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if kind == "csv":
            self.send_header("Content-Disposition", 'attachment; filename="timetable.csv"')
        self.end_headers()
        self.wfile.write(data)

    def _handle(self, method):
        url = urlparse(self.path)
        if not url.path.startswith("/api"):
            return self._static(url.path)
        body = {}
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._send(400, {"error": "invalid JSON"}, "json")
        with LOCK:
            conn = db.connect(DB_PATH)
            try:
                status, payload, kind = route(method, url.path, parse_qs(url.query), body, conn)
            except ApiError as e:
                status, payload, kind = e.status, {"error": str(e)}, "json"
            except Exception as e:  # noqa: BLE001 - report instead of crashing the server
                status, payload, kind = 500, {"error": "server error: %s" % e}, "json"
            finally:
                conn.close()
        self._send(status, payload, kind)

    def _static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC, rel))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            return self._send(404, b"Not found", "text/plain")
        with open(full, "rb") as f:
            self._send(200, f.read(), mimetypes.guess_type(full)[0] or "application/octet-stream")

    def do_GET(self): self._handle("GET")
    def do_POST(self): self._handle("POST")
    def do_PUT(self): self._handle("PUT")
    def do_DELETE(self): self._handle("DELETE")


def main():
    conn = db.connect(DB_PATH)
    db.init(conn)
    if db.is_empty(conn):
        db.seed(conn, sample_data.sample())
        print("Empty database: loaded sample data (edit it from the UI).")
    conn.close()
    port = int(os.environ.get("PORT", "8000"))
    print("Timetable system running at http://localhost:%d  (Ctrl+C to stop)" % port)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
