# Automated College Timetable & Resource Scheduling System

DSA project (A6): generates conflict-free college timetables from faculty, subjects,
batches, classrooms and time slots, using graph colouring, backtracking, greedy
algorithms and priority queues.

## Features

- Add / edit / delete **faculty** (with per-slot availability), **batches**, **classrooms** (lecture / lab) and **subjects** (weekly hours)
- Configurable working days, periods per day and period timings
- **Automatic timetable generation** with three selectable algorithms
- **Conflict detection**: faculty clash, batch clash, room clash, faculty availability, room capacity, room type, too many sessions of a subject in one day
- **Manual modification**: select a class, click an empty cell to move it (conflicts are shown and need confirmation to override), change room, unschedule, or place unscheduled sessions
- Timetable views per **batch**, **faculty** or **room**
- **Export** to CSV and Print / Save as PDF
- **Algorithm comparison** page (scheduled count, conflicts, time, search steps, idle gaps)
- Unscheduled sessions are reported with the reason (e.g. no lab room big enough)

## Tech stack

| Layer    | Technology |
|----------|------------|
| Frontend | HTML, CSS, vanilla JavaScript (single page, `static/index.html`) |
| Backend  | Python 3 standard library (`http.server`) REST API, `server.py` |
| Database | SQLite (`db.py`, file `timetable.db`) |
| DSA      | `scheduler.py` (pure Python, no dependencies) |

No packages need to be installed.

## Run

```bash
python3 server.py            # open http://localhost:8000
# optional: PORT=9000 TT_DB=/path/to/file.db python3 server.py
```

On first start (empty database) illustrative **sample data** is loaded. Replace it with
the real college resources from the UI (Faculty / Batches / Rooms / Subjects tabs).
"Load sample data" on the Faculty tab restores the sample.

## Test

```bash
python3 -m unittest discover -s tests -v
```

13 tests cover the algorithms (validity, infeasible inputs, tight instances), conflict
detection, database CRUD / validation / cascades, and the REST API end to end.

## How it works

1. **Sessions**: each subject with *h* hours/week becomes *h* sessions (one class each).
2. **Conflict graph**: vertex = session; edge between two sessions that share a faculty
   member or a student batch (they can never share a time slot).
3. **Domains**: for every session the allowed slots (faculty availability) and rooms
   (right type, enough capacity, smallest first = best fit).
4. **Solve** with one of:
   - **Greedy**: min-heap ordered by most constrained first, take the first feasible slot.
   - **DSATUR graph colouring**: colours = time slots; always colour the vertex with the
     highest saturation degree (distinct slots already used by neighbours) next, via a priority queue with lazy deletion.
   - **Backtracking** (default): recursive CSP search, picks the most constrained session
     (MRV, ties by graph degree), forward checking prunes dead ends immediately,
     value ordering spreads classes across the week. Time-limited; if no full solution
     exists it keeps the best partial timetable and greedily fills the rest.
5. **Validation**: `detect_conflicts` re-checks every hard constraint (used after generation and for manual edits).

### Complexity (n sessions, E conflict edges, S slots, R rooms)

| Part | Time | Space |
|------|------|-------|
| Conflict graph | O(n²) worst case | O(n + E) |
| Greedy | O(n log n + n·S·R) | O(n) |
| DSATUR | O((n + E) log n + n·S·R) | O(n + E) |
| Backtracking + MRV + FC | exponential worst case (NP-hard); each node O(n·S·R) | O(n) depth |
| Conflict detection | O(n) with hash maps | O(n) |

### DSA concepts used

Graph + graph colouring, backtracking, recursion, greedy algorithms, priority queue
(heap), constraint satisfaction, hash sets / hash maps, sorting.

## Project structure

```
server.py        HTTP server + REST API
scheduler.py     DSA engine (graph, DSATUR, backtracking, greedy, conflict detection)
db.py            SQLite schema, CRUD, validation
sample_data.py   illustrative data set
static/index.html   frontend
tests/test_all.py   unit + API tests
```

## REST API (summary)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/state` | all data, timetable, conflicts, unscheduled sessions |
| POST/PUT/DELETE | `/api/{faculty,batches,rooms,subjects}[/id]` | CRUD |
| POST | `/api/settings` | days / periods / labels |
| POST | `/api/generate` `{method}` | generate and save a timetable |
| POST | `/api/compare` | run all algorithms, return statistics |
| POST | `/api/move` `{session_id, slot, room_id?, force?}` | manual edit (409 on conflicts) |
| POST | `/api/unschedule`, `/api/clear`, `/api/seed` | housekeeping |
| GET | `/api/export.csv` | export timetable |

## Limitations

- One session = one period; lab sessions are not forced to be back-to-back blocks.
- Hard constraints only (plus a simple spread-over-the-week preference); no lunch-break or max-hours-per-day rules.
- Sample data is illustrative, not the real college data.
