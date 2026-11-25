"""Illustrative sample data. Replace it with the real college resources from the UI."""

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
PERIODS = 6
LABELS = ["09:00-10:00", "10:00-11:00", "11:00-12:00", "12:00-13:00",
          "14:00-15:00", "15:00-16:00"]


def slot(day, period):
    """day 0-based, period 0-based."""
    return day * PERIODS + period


def sample():
    everything = None  # None means "available in every slot"
    no_fri_pm = [s for s in range(len(DAYS) * PERIODS)
                 if s not in (slot(4, 4), slot(4, 5))]
    no_mon_first = [s for s in range(len(DAYS) * PERIODS) if s != slot(0, 0)]
    tue_to_fri = list(range(slot(1, 0), len(DAYS) * PERIODS))

    faculty = [
        (1, "Prof. Mehta (DSA)", everything),
        (2, "Prof. Iyer (DBMS)", no_mon_first),
        (3, "Prof. Khan (OS)", everything),
        (4, "Prof. Verma (CN)", everything),
        (5, "Prof. Singh (Maths)", no_fri_pm),
        (6, "Prof. Joshi (DSA Lab)", everything),
        (7, "Prof. Nair (DBMS Lab)", tue_to_fri),
        (8, "Prof. Gupta (DSA)", everything),
    ]
    batches = [(1, "CSE-A Sem3", 60), (2, "CSE-B Sem3", 55), (3, "AI-A Sem3", 45)]
    rooms = [
        (1, "R101", 70, "lecture"), (2, "R102", 60, "lecture"), (3, "R201", 60, "lecture"),
        (4, "Lab-1", 60, "lab"), (5, "Lab-2", 60, "lab"),
    ]
    specs = [  # code, name, hours, room_type, faculty for each batch
        ("CS201", "Data Structures", 4, "lecture", {1: 1, 2: 1, 3: 8}),
        ("CS202", "DBMS", 3, "lecture", {1: 2, 2: 2, 3: 2}),
        ("CS203", "Operating Systems", 3, "lecture", {1: 3, 2: 3, 3: 3}),
        ("CS204", "Computer Networks", 3, "lecture", {1: 4, 2: 4, 3: 4}),
        ("MA201", "Discrete Mathematics", 3, "lecture", {1: 5, 2: 5, 3: 5}),
        ("CS205L", "DSA Lab", 2, "lab", {1: 6, 2: 6, 3: 6}),
        ("CS206L", "DBMS Lab", 2, "lab", {1: 7, 2: 7, 3: 7}),
    ]
    subjects, sid = [], 1
    for b_id, _, _ in batches:
        for code, name, hours, rtype, facmap in specs:
            subjects.append((sid, code, name, facmap[b_id], b_id, hours, rtype))
            sid += 1

    return {
        "settings": {"days": DAYS, "periods": PERIODS, "labels": LABELS},
        "faculty": [{"id": i, "name": n, "email": "", "available": a} for i, n, a in faculty],
        "batches": [{"id": i, "name": n, "size": s} for i, n, s in batches],
        "rooms": [{"id": i, "name": n, "capacity": c, "type": t} for i, n, c, t in rooms],
        "subjects": [{"id": i, "code": c, "name": n, "faculty_id": f, "batch_id": b,
                      "hours": h, "room_type": t} for i, c, n, f, b, h, t in subjects],
    }
