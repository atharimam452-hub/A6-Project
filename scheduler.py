"""
Core timetable scheduling engine (pure Python, no database / web code).

DSA concepts used
-----------------
* Graph (conflict graph)      : vertex = class session, edge = two sessions that
                                share a faculty member or a student batch and
                                therefore can never be in the same time slot.
* Graph coloring (DSATUR)     : colours = time slots. Vertices are coloured in
                                order of "saturation degree" using a priority queue.
* Backtracking + recursion    : exact search with MRV (most-constrained-variable)
                                ordering and forward checking (constraint
                                satisfaction problem, CSP).
* Greedy + priority queue     : fast heuristic, most constrained sessions first.
* Hash sets / hash maps       : O(1) conflict look-ups (faculty/batch/room busy
                                sets, subject-per-day counters).

Complexity (n = sessions, S = slots, R = rooms, E = conflict edges)
--------------------------------------------------------------------
Conflict-graph build : O(sum of group^2) <= O(n^2) time, O(n + E) space
Greedy               : O(n log n + n*S*R) time, O(n) space
DSATUR               : O((n + E) log n + n*S*R) time, O(n + E) space
Backtracking (MRV+FC): worst case O((S*R)^n) (NP-hard problem); in practice far
                       smaller because of pruning. Each node costs O(n*S*R).
                       Recursion depth <= n. Bounded by a time limit.
"""
import heapq
import math
import sys
import time
from collections import defaultdict

sys.setrecursionlimit(20000)

METHODS = ("greedy", "dsatur", "backtracking")


# --------------------------------------------------------------------------- #
# Problem definition + conflict graph
# --------------------------------------------------------------------------- #
class Problem:
    """Turns plain dict data into sessions, candidate domains and a conflict graph."""

    def __init__(self, days, periods, faculty, batches, rooms, subjects):
        self.days = list(days)
        self.D = len(self.days)
        self.P = int(periods)
        self.n_slots = self.D * self.P
        self.faculty = {f["id"]: f for f in faculty}
        self.batches = {b["id"]: b for b in batches}
        self.rooms = {r["id"]: r for r in rooms}

        # one session per weekly hour of every subject
        self.sessions = []
        for s in subjects:
            fac = self.faculty.get(s["faculty_id"])
            bat = self.batches.get(s["batch_id"])
            if fac is None or bat is None:
                continue
            cap = max(1, math.ceil(s["hours"] / max(1, self.D)))  # max per day
            for k in range(int(s["hours"])):
                self.sessions.append({
                    "id": "%s-%d" % (s["id"], k),
                    "subject_id": s["id"],
                    "code": s["code"],
                    "name": s["name"],
                    "faculty_id": s["faculty_id"],
                    "batch_id": s["batch_id"],
                    "room_type": s["room_type"],
                    "size": bat["size"],
                    "day_cap": cap,
                })
        self.index = {s["id"]: i for i, s in enumerate(self.sessions)}

        # candidate slots / rooms for each session
        self.avail = []
        self.cand_rooms = []
        all_slots = set(range(self.n_slots))
        for s in self.sessions:
            a = self.faculty[s["faculty_id"]].get("available")
            slots = all_slots if a is None else (set(a) & all_slots)
            self.avail.append(sorted(slots))
            rs = [r for r in self.rooms.values()
                  if r["type"] == s["room_type"] and r["capacity"] >= s["size"]]
            rs.sort(key=lambda r: r["capacity"])  # best fit first
            self.cand_rooms.append([r["id"] for r in rs])

        # conflict graph (adjacency sets)
        n = len(self.sessions)
        self.adj = [set() for _ in range(n)]
        groups = defaultdict(list)
        for i, s in enumerate(self.sessions):
            groups[("f", s["faculty_id"])].append(i)
            groups[("b", s["batch_id"])].append(i)
        for g in groups.values():
            for a in g:
                for b in g:
                    if a != b:
                        self.adj[a].add(b)

    def day(self, slot):
        return slot // self.P

    def slot_name(self, slot):
        return "%s P%d" % (self.days[slot // self.P], slot % self.P + 1)


# --------------------------------------------------------------------------- #
# Mutable search state (hash sets / maps => O(1) checks)
# --------------------------------------------------------------------------- #
class State:
    def __init__(self, p):
        self.p = p
        self.fac_busy = set()
        self.bat_busy = set()
        self.room_busy = set()
        self.subj_day = defaultdict(int)
        self.bat_day = defaultdict(int)
        self.fac_day = defaultdict(int)
        self.assign = {}  # session idx -> (slot, room_id)

    def free_room(self, i, slot):
        for r in self.p.cand_rooms[i]:
            if (r, slot) not in self.room_busy:
                return r
        return None

    def slot_ok(self, i, slot):
        s = self.p.sessions[i]
        if (s["faculty_id"], slot) in self.fac_busy:
            return False
        if (s["batch_id"], slot) in self.bat_busy:
            return False
        if self.subj_day[(s["subject_id"], self.p.day(slot))] >= s["day_cap"]:
            return False
        return self.free_room(i, slot) is not None

    def feasible(self, i):
        return [sl for sl in self.p.avail[i] if self.slot_ok(i, sl)]

    def ordered(self, i, slots):
        """Value ordering: spread classes over the week (least loaded day first)."""
        s = self.p.sessions[i]
        return sorted(slots, key=lambda sl: (
            self.bat_day[(s["batch_id"], self.p.day(sl))],
            self.fac_day[(s["faculty_id"], self.p.day(sl))],
            sl))

    def place(self, i, slot, room):
        s = self.p.sessions[i]
        d = self.p.day(slot)
        self.fac_busy.add((s["faculty_id"], slot))
        self.bat_busy.add((s["batch_id"], slot))
        self.room_busy.add((room, slot))
        self.subj_day[(s["subject_id"], d)] += 1
        self.bat_day[(s["batch_id"], d)] += 1
        self.fac_day[(s["faculty_id"], d)] += 1
        self.assign[i] = (slot, room)

    def remove(self, i):
        slot, room = self.assign.pop(i)
        s = self.p.sessions[i]
        d = self.p.day(slot)
        self.fac_busy.discard((s["faculty_id"], slot))
        self.bat_busy.discard((s["batch_id"], slot))
        self.room_busy.discard((room, slot))
        self.subj_day[(s["subject_id"], d)] -= 1
        self.bat_day[(s["batch_id"], d)] -= 1
        self.fac_day[(s["faculty_id"], d)] -= 1


# --------------------------------------------------------------------------- #
# Algorithm 1: greedy with a priority queue
# --------------------------------------------------------------------------- #
def _fill_greedy(p, st, todo):
    """Place the sessions in `todo` greedily, most constrained first (min-heap)."""
    heap = [(-len(p.adj[i]), len(p.avail[i]), i) for i in todo]
    heapq.heapify(heap)
    placed = 0
    while heap:
        _, _, i = heapq.heappop(heap)
        slots = st.feasible(i)
        if not slots:
            continue
        sl = st.ordered(i, slots)[0]
        st.place(i, sl, st.free_room(i, sl))
        placed += 1
    return placed


def _greedy(p):
    st = State(p)
    _fill_greedy(p, st, range(len(p.sessions)))
    return st.assign, len(p.sessions)


# --------------------------------------------------------------------------- #
# Algorithm 2: DSATUR graph colouring (colour = time slot)
# --------------------------------------------------------------------------- #
def _dsatur(p):
    n = len(p.sessions)
    st = State(p)
    sat = [set() for _ in range(n)]          # colours (slots) used by neighbours
    deg = [len(p.adj[i]) for i in range(n)]
    heap = [(0, -deg[i], i) for i in range(n)]
    heapq.heapify(heap)
    done = set()
    steps = 0
    while heap:
        negsat, _, i = heapq.heappop(heap)
        if i in done or -negsat != len(sat[i]):
            continue                          # stale entry (lazy deletion)
        done.add(i)
        steps += 1
        slots = [sl for sl in st.feasible(i) if sl not in sat[i]]
        if not slots:
            continue                          # could not colour this vertex
        sl = st.ordered(i, slots)[0]
        st.place(i, sl, st.free_room(i, sl))
        for j in p.adj[i]:
            if j not in done and sl not in sat[j]:
                sat[j].add(sl)
                heapq.heappush(heap, (-len(sat[j]), -deg[j], j))
    return st.assign, steps


# --------------------------------------------------------------------------- #
# Algorithm 3: backtracking with MRV + forward checking
# --------------------------------------------------------------------------- #
def _backtracking(p, time_limit):
    n = len(p.sessions)
    st = State(p)
    unassigned = set(range(n))
    t0 = time.perf_counter()
    nodes = 0
    best = {}
    timed_out = False

    def rec():
        nonlocal nodes, best, timed_out
        if not unassigned:
            return True
        nodes += 1
        if time.perf_counter() - t0 > time_limit:
            timed_out = True
            return False
        pick, pick_slots, pick_key = None, None, None
        for i in unassigned:
            f = st.feasible(i)
            if not f:                         # forward check: dead end
                if len(st.assign) > len(best):
                    best = dict(st.assign)
                return False
            key = (len(f), -len(p.adj[i]))    # MRV, tie-break by degree
            if pick_key is None or key < pick_key:
                pick, pick_slots, pick_key = i, f, key
        for sl in st.ordered(pick, pick_slots):
            st.place(pick, sl, st.free_room(pick, sl))
            unassigned.discard(pick)
            if rec():
                return True
            st.remove(pick)
            unassigned.add(pick)
            if timed_out:
                return False
        return False

    if rec():
        return dict(st.assign), nodes

    # No full solution (infeasible data or time-out): keep the best partial
    # schedule found and fill what is still possible greedily.
    st2 = State(p)
    for i, (sl, room) in best.items():
        st2.place(i, sl, room)
    _fill_greedy(p, st2, [i for i in range(n) if i not in st2.assign])
    return st2.assign, nodes


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def reason(p, i):
    s = p.sessions[i]
    if not p.cand_rooms[i]:
        return "No %s room with capacity >= %d" % (s["room_type"], s["size"])
    if not p.avail[i]:
        return "Faculty has no available time slots"
    return "No conflict-free slot/room left (faculty, batch or room clash)"


def quality(p, assign):
    """Number of idle gaps inside a batch's day (lower is better)."""
    per = defaultdict(list)
    for i, (sl, _) in assign.items():
        per[(p.sessions[i]["batch_id"], p.day(sl))].append(sl % p.P)
    gaps = 0
    for periods in per.values():
        gaps += (max(periods) - min(periods) + 1) - len(periods)
    return gaps


def solve(p, method="backtracking", time_limit=10.0):
    if method not in METHODS:
        raise ValueError("unknown method %r" % method)
    t0 = time.perf_counter()
    if method == "greedy":
        assign, nodes = _greedy(p)
    elif method == "dsatur":
        assign, nodes = _dsatur(p)
    else:
        assign, nodes = _backtracking(p, time_limit)
    elapsed = (time.perf_counter() - t0) * 1000.0
    n = len(p.sessions)
    return {
        "method": method,
        "assignments": {p.sessions[i]["id"]: {"slot": sl, "room_id": room}
                        for i, (sl, room) in assign.items()},
        "unscheduled": [{"session_id": p.sessions[i]["id"], "reason": reason(p, i)}
                        for i in range(n) if i not in assign],
        "stats": {
            "method": method,
            "total": n,
            "scheduled": len(assign),
            "time_ms": round(elapsed, 2),
            "nodes": nodes,
            "gaps": quality(p, assign),
            "conflict_edges": sum(len(a) for a in p.adj) // 2,
        },
    }


# --------------------------------------------------------------------------- #
# Conflict detection (used for validation and manual edits)
# --------------------------------------------------------------------------- #
def detect_conflicts(p, assignments):
    """assignments: {session_id: {"slot": int, "room_id": int}} -> list of conflicts."""
    out = []
    fac, bat, room = defaultdict(list), defaultdict(list), defaultdict(list)
    subj_day = defaultdict(list)
    for sid, a in assignments.items():
        if sid not in p.index:
            continue
        i = p.index[sid]
        s = p.sessions[i]
        sl, r = a["slot"], a["room_id"]
        fac[(s["faculty_id"], sl)].append(sid)
        bat[(s["batch_id"], sl)].append(sid)
        room[(r, sl)].append(sid)
        subj_day[(s["subject_id"], p.day(sl))].append(sid)

        f = p.faculty[s["faculty_id"]]
        if f.get("available") is not None and sl not in f["available"]:
            out.append({"type": "availability", "sessions": [sid],
                        "message": "%s is not available at %s" % (f["name"], p.slot_name(sl))})
        rm = p.rooms.get(r)
        if rm is None:
            out.append({"type": "room", "sessions": [sid], "message": "Room does not exist"})
            continue
        if rm["capacity"] < s["size"]:
            out.append({"type": "capacity", "sessions": [sid],
                        "message": "%s (cap %d) is too small for batch of %d" %
                                   (rm["name"], rm["capacity"], s["size"])})
        if rm["type"] != s["room_type"]:
            out.append({"type": "room_type", "sessions": [sid],
                        "message": "%s is a %s room but %s needs a %s room" %
                                   (rm["name"], rm["type"], s["code"], s["room_type"])})

    for (f, sl), ids in fac.items():
        if len(ids) > 1:
            out.append({"type": "faculty", "sessions": ids,
                        "message": "Faculty %s double-booked at %s" %
                                   (p.faculty[f]["name"], p.slot_name(sl))})
    for (b, sl), ids in bat.items():
        if len(ids) > 1:
            out.append({"type": "batch", "sessions": ids,
                        "message": "Batch %s has overlapping classes at %s" %
                                   (p.batches[b]["name"], p.slot_name(sl))})
    for (r, sl), ids in room.items():
        if len(ids) > 1:
            name = p.rooms[r]["name"] if r in p.rooms else str(r)
            out.append({"type": "room", "sessions": ids,
                        "message": "Room %s double-booked at %s" % (name, p.slot_name(sl))})
    for (sub, d), ids in subj_day.items():
        cap = p.sessions[p.index[ids[0]]]["day_cap"]
        if len(ids) > cap:
            s = p.sessions[p.index[ids[0]]]
            out.append({"type": "subject_day", "sessions": ids,
                        "message": "%s has %d classes on %s (max %d)" %
                                   (s["code"], len(ids), p.days[d], cap)})
    return out
