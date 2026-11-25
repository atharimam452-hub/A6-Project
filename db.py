"""SQLite persistence layer."""
import json
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS faculty (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    available TEXT            -- JSON list of slot ids, NULL = always available
);
CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    size INTEGER NOT NULL CHECK (size > 0)
);
CREATE TABLE IF NOT EXISTS rooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    capacity INTEGER NOT NULL CHECK (capacity > 0),
    type TEXT NOT NULL CHECK (type IN ('lecture','lab'))
);
CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    faculty_id INTEGER NOT NULL REFERENCES faculty(id) ON DELETE CASCADE,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    hours INTEGER NOT NULL CHECK (hours BETWEEN 1 AND 20),
    room_type TEXT NOT NULL CHECK (room_type IN ('lecture','lab'))
);
CREATE TABLE IF NOT EXISTS timetable (
    session_id TEXT PRIMARY KEY,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    slot INTEGER NOT NULL,
    room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE
);
"""

ENTITIES = ("faculty", "batches", "rooms", "subjects")
ROOM_TYPES = ("lecture", "lab")

DEFAULT_SETTINGS = {
    "days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
    "periods": 6,
    "labels": ["09:00-10:00", "10:00-11:00", "11:00-12:00", "12:00-13:00",
               "14:00-15:00", "15:00-16:00"],
}


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init(conn):
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0:
        set_settings(conn, DEFAULT_SETTINGS["days"], DEFAULT_SETTINGS["periods"],
                     DEFAULT_SETTINGS["labels"])
    conn.commit()


# ------------------------------- settings -------------------------------- #
def get_settings(conn):
    rows = {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT * FROM settings")}
    return {k: rows.get(k, DEFAULT_SETTINGS[k]) for k in DEFAULT_SETTINGS}


def set_settings(conn, days, periods, labels):
    for k, v in (("days", days), ("periods", periods), ("labels", labels)):
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)", (k, json.dumps(v)))


def validate_settings(data):
    days = [str(d).strip() for d in data.get("days", []) if str(d).strip()]
    try:
        periods = int(data.get("periods"))
    except (TypeError, ValueError):
        raise ValueError("periods must be a number")
    if not days or len(days) > 7:
        raise ValueError("Provide between 1 and 7 days")
    if not 1 <= periods <= 12:
        raise ValueError("periods must be between 1 and 12")
    labels = [str(x).strip() for x in data.get("labels", [])][:periods]
    labels += ["Period %d" % (i + 1) for i in range(len(labels), periods)]
    return days, periods, labels


# ------------------------------- entities -------------------------------- #
def _int(data, key, lo=1, hi=10 ** 6):
    try:
        v = int(data.get(key))
    except (TypeError, ValueError):
        raise ValueError("%s must be a number" % key)
    if not lo <= v <= hi:
        raise ValueError("%s must be between %d and %d" % (key, lo, hi))
    return v


def _str(data, key, required=True):
    v = str(data.get(key, "") or "").strip()
    if required and not v:
        raise ValueError("%s is required" % key)
    return v


def clean(conn, ent, data):
    """Validate and normalise input for one entity -> dict of column values."""
    if ent == "faculty":
        av = data.get("available")
        if av is not None:
            av = sorted({int(x) for x in av})
        return {"name": _str(data, "name"), "email": _str(data, "email", False),
                "available": None if av is None else json.dumps(av)}
    if ent == "batches":
        return {"name": _str(data, "name"), "size": _int(data, "size")}
    if ent == "rooms":
        t = _str(data, "type")
        if t not in ROOM_TYPES:
            raise ValueError("type must be lecture or lab")
        return {"name": _str(data, "name"), "capacity": _int(data, "capacity"), "type": t}
    if ent == "subjects":
        rt = _str(data, "room_type")
        if rt not in ROOM_TYPES:
            raise ValueError("room_type must be lecture or lab")
        out = {"code": _str(data, "code"), "name": _str(data, "name"),
               "faculty_id": _int(data, "faculty_id"), "batch_id": _int(data, "batch_id"),
               "hours": _int(data, "hours", 1, 20), "room_type": rt}
        if not conn.execute("SELECT 1 FROM faculty WHERE id=?", (out["faculty_id"],)).fetchone():
            raise ValueError("faculty does not exist")
        if not conn.execute("SELECT 1 FROM batches WHERE id=?", (out["batch_id"],)).fetchone():
            raise ValueError("batch does not exist")
        return out
    raise ValueError("unknown entity")


def _row(ent, r):
    d = dict(r)
    if ent == "faculty":
        d["available"] = None if d["available"] is None else json.loads(d["available"])
    return d


def list_rows(conn, ent):
    return [_row(ent, r) for r in conn.execute("SELECT * FROM %s ORDER BY id" % ent)]


def insert(conn, ent, data):
    vals = clean(conn, ent, data)
    cols = ",".join(vals)
    cur = conn.execute("INSERT INTO %s(%s) VALUES (%s)" % (ent, cols, ",".join("?" * len(vals))),
                       list(vals.values()))
    conn.commit()
    return cur.lastrowid


def update(conn, ent, row_id, data):
    vals = clean(conn, ent, data)
    sets = ",".join("%s=?" % c for c in vals)
    cur = conn.execute("UPDATE %s SET %s WHERE id=?" % (ent, sets), list(vals.values()) + [row_id])
    conn.commit()
    return cur.rowcount > 0


def delete(conn, ent, row_id):
    cur = conn.execute("DELETE FROM %s WHERE id=?" % ent, (row_id,))
    conn.commit()
    return cur.rowcount > 0


def is_empty(conn):
    return all(conn.execute("SELECT COUNT(*) FROM %s" % e).fetchone()[0] == 0 for e in ENTITIES)


def seed(conn, data):
    """Replace all data with `data` (see sample_data.sample())."""
    for t in ("timetable", "subjects", "rooms", "batches", "faculty"):
        conn.execute("DELETE FROM %s" % t)
    s = data["settings"]
    set_settings(conn, s["days"], s["periods"], s["labels"])
    for f in data["faculty"]:
        conn.execute("INSERT INTO faculty(id,name,email,available) VALUES (?,?,?,?)",
                     (f["id"], f["name"], f["email"],
                      None if f["available"] is None else json.dumps(f["available"])))
    for b in data["batches"]:
        conn.execute("INSERT INTO batches(id,name,size) VALUES (?,?,?)", (b["id"], b["name"], b["size"]))
    for r in data["rooms"]:
        conn.execute("INSERT INTO rooms(id,name,capacity,type) VALUES (?,?,?,?)",
                     (r["id"], r["name"], r["capacity"], r["type"]))
    for s in data["subjects"]:
        conn.execute("INSERT INTO subjects(id,code,name,faculty_id,batch_id,hours,room_type)"
                     " VALUES (?,?,?,?,?,?,?)",
                     (s["id"], s["code"], s["name"], s["faculty_id"], s["batch_id"],
                      s["hours"], s["room_type"]))
    conn.commit()


# ------------------------------- timetable ------------------------------- #
def get_timetable(conn):
    return {r["session_id"]: {"slot": r["slot"], "room_id": r["room_id"]}
            for r in conn.execute("SELECT * FROM timetable")}


def clear_timetable(conn):
    conn.execute("DELETE FROM timetable")
    conn.commit()


def save_timetable(conn, assignments):
    conn.execute("DELETE FROM timetable")
    for sid, a in assignments.items():
        conn.execute("INSERT INTO timetable(session_id,subject_id,slot,room_id) VALUES (?,?,?,?)",
                     (sid, int(sid.split("-")[0]), a["slot"], a["room_id"]))
    conn.commit()


def set_placement(conn, sid, slot, room_id):
    conn.execute("INSERT OR REPLACE INTO timetable(session_id,subject_id,slot,room_id) VALUES (?,?,?,?)",
                 (sid, int(sid.split("-")[0]), slot, room_id))
    conn.commit()


def remove_placement(conn, sid):
    conn.execute("DELETE FROM timetable WHERE session_id=?", (sid,))
    conn.commit()
