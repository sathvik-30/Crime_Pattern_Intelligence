#!/usr/bin/env python3
"""
Synthetic seed data generator for the Crime Pattern Intelligence System.

Populates all 10 tables from the Phase 1 schema, plus the Phase 3
case_reassignments table, with realistic, internally consistent synthetic
data for a fictional city, including deliberately baked-in patterns for
later analytics phases to discover:

  * a rising trend of reports in one hotspot area over the last 3 months
  * one crime type with strong seasonality (repeats every year in the window)
  * a small group of "star" officers with a noticeably higher case
    resolution rate than everyone else

Idempotent: every run TRUNCATEs all ten tables (RESTART IDENTITY CASCADE)
before reloading, so re-running the script always leaves the database in
the same state rather than appending duplicate data. A fixed random seed
makes the generated dataset deterministic across runs.

Usage:
    python generate_seed_data.py

Connection is configured via environment variables (all optional):
    CPI_DB_HOST      default: localhost
    CPI_DB_PORT      default: 5432
    CPI_DB_NAME      default: crime_pattern_intelligence
    CPI_DB_USER      default: cpi_user
    CPI_DB_PASSWORD  default: cpi_password
"""

import os
import random
from datetime import date, datetime, timedelta

import pg8000.dbapi
from faker import Faker

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RANDOM_SEED = 42

NUM_STATIONS = 15
NUM_OFFICERS = 40
NUM_CRIME_REPORTS = 560
NUM_CRIMINALS = 320
NUM_VICTIMS = 420

MONTHS_BACK = 24          # crime_reports span the last 24 months
RECENT_MONTHS = 3         # "last 3 months" window for the rising-trend hotspot
RESOLVED_TARGET = 0.70    # ~70% of cases get evidence + a final court outcome

RISING_HOTSPOT = "Riverside"          # gets a rising trend in the recent window
SEASONAL_CRIME_TYPE = "Burglary"      # peaks every Nov-Jan across both years
STAR_OFFICER_COUNT = 2                # officers with an outlier resolution rate
STAR_OFFICER_CASE_SHARE = 0.20        # chance a case is steered to a star officer
STAR_OFFICER_RESOLUTION_RATE = 0.93
BASE_OFFICER_RESOLUTION_RATE = 0.65

REASSIGNMENT_CASE_SHARE = 0.15   # fraction of cases that have escalation history
REASSIGNMENT_REASONS = [
    "Escalation", "Workload Rebalance", "Officer Transfer", "Specialist Handoff",
]

DB_CONFIG = {
    "host": os.environ.get("CPI_DB_HOST", "localhost"),
    "port": int(os.environ.get("CPI_DB_PORT", "5432")),
    "database": os.environ.get("CPI_DB_NAME", "crime_pattern_intelligence"),
    "user": os.environ.get("CPI_DB_USER", "cpi_user"),
    "password": os.environ.get("CPI_DB_PASSWORD", "cpi_password"),
}

TODAY = date.today()

fake = Faker()
Faker.seed(RANDOM_SEED)
random.seed(RANDOM_SEED)

# ---------------------------------------------------------------------------
# Fictional city geography
# ---------------------------------------------------------------------------

# (area name, lat, lng, is_hotspot). Hotspots get a tight lat/lng spread and
# a much larger share of report volume; the rest are a long tail.
CITY_CENTER = (41.4500, -87.6200)

AREAS = [
    ("Old Town",        41.4620, -87.6330, True),
    ("Riverside",       41.4410, -87.6470, True),
    ("Harbor District", 41.4700, -87.6050, True),
    ("Ironworks",       41.4300, -87.6150, True),
    ("Uptown Heights",  41.4900, -87.6400, False),
    ("Eastgate",        41.4550, -87.5800, False),
    ("Westfield",       41.4250, -87.6600, False),
    ("Millbrook",       41.4050, -87.6350, False),
    ("Sunnyvale Park",  41.4800, -87.6600, False),
    ("Lakeside",        41.5000, -87.6100, False),
    ("Grand Central",   41.4480, -87.6250, False),
    ("Northgate",       41.5100, -87.6300, False),
    ("Southport",       41.3950, -87.6050, False),
    ("Cedar Hollow",    41.4150, -87.5900, False),
    ("Fairview",        41.4650, -87.5950, False),
]
assert len(AREAS) == NUM_STATIONS

HOTSPOT_AREAS = [name for name, _, __, is_hot in AREAS if is_hot]

# ---------------------------------------------------------------------------
# Reference value pools (must match the CHECK constraints in the migrations)
# ---------------------------------------------------------------------------

RANK_WEIGHTS = [
    ("Constable", 30),
    ("Head Constable", 20),
    ("Assistant Sub-Inspector", 15),
    ("Sub-Inspector", 12),
    ("Inspector", 10),
    ("Deputy Superintendent", 6),
    ("Superintendent", 4),
    ("Deputy Inspector General", 2),
    ("Inspector General", 0.7),
    ("Director General", 0.3),
]

# (crime_type, relative frequency weight, severity weights {Low,Medium,High,Critical})
CRIME_TYPES = [
    ("Theft",               22, {"Low": 55, "Medium": 35, "High": 10, "Critical": 0}),
    ("Vandalism",           14, {"Low": 70, "Medium": 25, "High": 5,  "Critical": 0}),
    ("Assault",             13, {"Low": 10, "Medium": 45, "High": 35, "Critical": 10}),
    ("Drug Possession",     12, {"Low": 40, "Medium": 45, "High": 15, "Critical": 0}),
    ("Burglary",            10, {"Low": 5,  "Medium": 45, "High": 45, "Critical": 5}),
    ("Motor Vehicle Theft",  9, {"Low": 10, "Medium": 50, "High": 35, "Critical": 5}),
    ("Fraud",                8, {"Low": 35, "Medium": 45, "High": 20, "Critical": 0}),
    ("Domestic Violence",    6, {"Low": 5,  "Medium": 35, "High": 45, "Critical": 15}),
    ("Cybercrime",           4, {"Low": 30, "Medium": 45, "High": 25, "Critical": 0}),
    ("Robbery",              3, {"Low": 0,  "Medium": 15, "High": 55, "Critical": 30}),
    ("Homicide",             1, {"Low": 0,  "Medium": 0,  "High": 20, "Critical": 80}),
]

EVIDENCE_TYPES = [
    "Physical", "Digital", "Document", "Biological", "Photographic", "Testimonial", "Other",
]

VERDICTS_FINAL = [
    ("Guilty", 45), ("Not Guilty", 15), ("Acquitted", 15), ("Dismissed", 12), ("Settled", 13),
]

GENDERS = ["M", "F", "O"]
GENDER_WEIGHTS = [47, 47, 6]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def weighted_choice(pairs):
    """pairs: list of (value, weight) -> a single weighted-random value."""
    values, weights = zip(*pairs)
    return random.choices(values, weights=weights, k=1)[0]


def random_weekday_biased_date(year, month):
    """A random day within (year, month), biased toward Fri/Sat/Sun."""
    if month == 12:
        days_in_month = 31
    else:
        days_in_month = (date(year, month + 1, 1) - date(year, month, 1)).days
    candidates = [date(year, month, d) for d in range(1, days_in_month + 1)]
    weights = [3 if d.weekday() in (4, 5, 6) else 1 for d in candidates]
    return random.choices(candidates, weights=weights, k=1)[0]


def month_offset_to_year_month(months_ago):
    """months_ago=0 -> current month; returns (year, month)."""
    total = TODAY.year * 12 + (TODAY.month - 1) - months_ago
    return divmod(total, 12)[0], divmod(total, 12)[1] + 1


def pick_months_ago(crime_type):
    """Choose how many months back (0..MONTHS_BACK-1) a report occurred,
    applying strong seasonality to SEASONAL_CRIME_TYPE and leaving all
    other types roughly uniform across the window."""
    offsets = list(range(MONTHS_BACK))
    if crime_type == SEASONAL_CRIME_TYPE:
        weights = []
        for m in offsets:
            year, month = month_offset_to_year_month(m)
            weights.append(6 if month in (11, 12, 1) else 1)
    else:
        weights = [1] * MONTHS_BACK
    return random.choices(offsets, weights=weights, k=1)[0]


def pick_area(months_ago):
    """Weighted area choice: hotspots dominate; RISING_HOTSPOT gets an extra
    boost specifically within the last RECENT_MONTHS, to create a real
    month-over-month rising trend an analyst can find."""
    weights = []
    for name, *_ in AREAS:
        is_hot = name in HOTSPOT_AREAS
        w = 12.0 if is_hot else 2.5
        if name == RISING_HOTSPOT and months_ago < RECENT_MONTHS:
            w *= 4.5
        weights.append(w)
    names = [name for name, *_ in AREAS]
    return random.choices(names, weights=weights, k=1)[0]


def jittered_location(area_name):
    lat, lng = next((a[1], a[2]) for a in AREAS if a[0] == area_name)
    spread = 0.010 if area_name in HOTSPOT_AREAS else 0.035
    return (
        round(lat + random.gauss(0, spread), 6),
        round(lng + random.gauss(0, spread), 6),
    )


def random_datetime_in(d: date):
    return datetime(d.year, d.month, d.day, random.randint(0, 23), random.randint(0, 59))


# ---------------------------------------------------------------------------
# Database plumbing
# ---------------------------------------------------------------------------

TABLES_IN_TRUNCATE_ORDER = [
    "crime_reports_audit", "case_reassignments", "court_status", "evidence",
    "case_victims", "case_criminals", "cases", "crime_reports", "victims",
    "criminals", "officers", "police_stations",
]


def connect():
    return pg8000.dbapi.connect(**DB_CONFIG)


def truncate_all(cur):
    tables = ", ".join(TABLES_IN_TRUNCATE_ORDER)
    cur.execute(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE;")


def set_crime_reports_triggers(cur, enabled: bool):
    """Seeding performs its own internal UPDATE on crime_reports (to fix up
    status once a case's outcome is known), which is bulk/administrative
    activity, not a real audit-worthy application change. Disabling
    user triggers for the duration of the seed run -- a standard pattern
    for bulk loaders -- keeps db/sql_features/triggers.sql's audit trigger
    (if it has already been applied) from being populated by the seed
    process itself, so crime_reports_audit only ever reflects genuine
    post-seed activity.

    Uses TRIGGER USER (not ALL): ALL would also disable the internal
    triggers Postgres uses to enforce this table's foreign keys, which
    must stay active even during seeding. USER only affects triggers
    like the audit trigger, and is a no-op if none exist yet (e.g. on a
    fresh database where triggers.sql hasn't been applied).
    """
    cur.execute(
        "ALTER TABLE crime_reports %s TRIGGER USER;" % ("ENABLE" if enabled else "DISABLE")
    )


# ---------------------------------------------------------------------------
# Seed generators
# ---------------------------------------------------------------------------

def seed_police_stations(cur):
    ids = []
    for name, *_ in AREAS:
        cur.execute(
            """
            INSERT INTO police_stations (name, jurisdiction_area, contact_no)
            VALUES (%s, %s, %s) RETURNING station_id
            """,
            (f"{name} Police Station", name, fake.numerify("555-##%%")),
        )
        ids.append(cur.fetchone()[0])
    return ids  # index-aligned with AREAS


def seed_officers(cur, station_ids):
    # Every station gets at least one officer; remaining officers are
    # distributed with hotspot stations weighted to get more staff.
    assignments = list(station_ids)  # one each, guarantees full coverage
    remaining = NUM_OFFICERS - len(station_ids)
    weights = [
        3.0 if AREAS[i][0] in HOTSPOT_AREAS else 1.0
        for i in range(len(station_ids))
    ]
    assignments += random.choices(station_ids, weights=weights, k=remaining)
    random.shuffle(assignments)

    officer_ids = []
    officers_by_station = {sid: [] for sid in station_ids}
    for i, station_id in enumerate(assignments):
        joining_date = TODAY - timedelta(days=random.randint(180, 25 * 365))
        cur.execute(
            """
            INSERT INTO officers (name, rank, station_id, badge_no, joining_date)
            VALUES (%s, %s, %s, %s, %s) RETURNING officer_id
            """,
            (
                fake.name(),
                weighted_choice(RANK_WEIGHTS),
                station_id,
                f"B-{1000 + i}",
                joining_date,
            ),
        )
        officer_id = cur.fetchone()[0]
        officer_ids.append(officer_id)
        officers_by_station[station_id].append(officer_id)

    # Designate the star officers: pick from officers at the largest
    # (hotspot) stations so their outlier resolution rate shows up
    # alongside genuinely high case volume.
    hotspot_station_ids = [
        station_ids[i] for i, (name, *_ ) in enumerate(AREAS) if name in HOTSPOT_AREAS
    ]
    candidate_pool = [oid for sid in hotspot_station_ids for oid in officers_by_station[sid]]
    star_officer_ids = random.sample(candidate_pool, STAR_OFFICER_COUNT)

    return officer_ids, officers_by_station, star_officer_ids


def seed_criminals(cur):
    ids = []
    for _ in range(NUM_CRIMINALS):
        dob = fake.date_of_birth(minimum_age=16, maximum_age=75)
        gender = random.choices(GENDERS, weights=GENDER_WEIGHTS, k=1)[0]
        prior_convictions = random.choices(
            [0, 1, 2, 3, 4, 5, 6], weights=[45, 25, 15, 8, 4, 2, 1], k=1
        )[0]
        cur.execute(
            """
            INSERT INTO criminals (name, dob, gender, address, prior_convictions_count)
            VALUES (%s, %s, %s, %s, %s) RETURNING criminal_id
            """,
            (fake.name(), dob, gender, fake.address().replace("\n", ", "), prior_convictions),
        )
        ids.append(cur.fetchone()[0])
    return ids


def seed_victims(cur):
    ids = []
    for _ in range(NUM_VICTIMS):
        age = random.randint(1, 90)
        gender = random.choices(GENDERS, weights=GENDER_WEIGHTS, k=1)[0]
        cur.execute(
            """
            INSERT INTO victims (name, age, gender, contact_no, address)
            VALUES (%s, %s, %s, %s, %s) RETURNING victim_id
            """,
            (fake.name(), age, gender, fake.phone_number()[:20], fake.address().replace("\n", ", ")),
        )
        ids.append(cur.fetchone()[0])
    return ids


def seed_crime_reports(cur, station_ids, officers_by_station):
    """Returns a list of dicts with everything downstream steps need."""
    area_to_station = {AREAS[i][0]: station_ids[i] for i in range(len(AREAS))}
    reports = []

    for _ in range(NUM_CRIME_REPORTS):
        crime_type, severity_weights = _pick_crime_type()
        months_ago = pick_months_ago(crime_type)
        year, month = month_offset_to_year_month(months_ago)
        occurred_date = random_weekday_biased_date(year, month)
        if occurred_date > TODAY:
            occurred_date = TODAY
        date_occurred = random_datetime_in(occurred_date)

        # Report lag: violent/urgent crimes reported almost immediately,
        # property crimes sometimes reported hours/days later.
        if crime_type in ("Homicide", "Robbery", "Assault", "Domestic Violence"):
            lag = timedelta(minutes=random.randint(5, 240))
        else:
            lag = timedelta(hours=random.randint(1, 72))
        date_reported = date_occurred + lag
        if date_reported.date() > TODAY:
            date_reported = datetime(TODAY.year, TODAY.month, TODAY.day, 23, 59)

        area = pick_area(months_ago)
        station_id = area_to_station[area]
        lat, lng = jittered_location(area)
        severity = weighted_choice(list(severity_weights.items()))
        reporting_officer_id = random.choice(officers_by_station[station_id])

        reports.append(
            {
                "crime_type": crime_type,
                "date_reported": date_reported,
                "date_occurred": date_occurred,
                "location_lat": lat,
                "location_lng": lng,
                "area": area,
                "station_id": station_id,
                "reporting_officer_id": reporting_officer_id,
                "severity": severity,
                "months_ago": months_ago,
            }
        )

    # ~8% of reports never pan out into a case.
    for r in reports:
        r["is_unfounded"] = random.random() < 0.08
        r["status"] = "Unfounded" if r["is_unfounded"] else "Reported"  # refined later

    for r in reports:
        cur.execute(
            """
            INSERT INTO crime_reports
                (crime_type, date_reported, date_occurred, location_lat, location_lng,
                 area, station_id, reporting_officer_id, severity, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING report_id
            """,
            (
                r["crime_type"], r["date_reported"], r["date_occurred"],
                r["location_lat"], r["location_lng"], r["area"], r["station_id"],
                r["reporting_officer_id"], r["severity"], r["status"],
            ),
        )
        r["report_id"] = cur.fetchone()[0]

    return reports


def _pick_crime_type():
    types = [(t, w) for t, w, _ in CRIME_TYPES]
    crime_type = weighted_choice(types)
    severity_weights = next(sw for t, _, sw in CRIME_TYPES if t == crime_type)
    return crime_type, severity_weights


def seed_cases(cur, reports, station_ids, officers_by_station, star_officer_ids):
    """Creates a case for every non-unfounded report. Returns the list of
    case dicts (resolved cases carry opened/closed dates for evidence and
    court_status to build on)."""
    all_officers_by_station = officers_by_station
    cases = []

    for r in reports:
        if r["is_unfounded"]:
            continue

        station_officers = all_officers_by_station[r["station_id"]]
        if random.random() < STAR_OFFICER_CASE_SHARE:
            assigned_officer_id = random.choice(star_officer_ids)
        else:
            assigned_officer_id = random.choice(station_officers)

        opened_date = r["date_reported"].date() + timedelta(days=random.randint(0, 3))
        if opened_date > TODAY:
            opened_date = TODAY

        resolution_rate = (
            STAR_OFFICER_RESOLUTION_RATE
            if assigned_officer_id in star_officer_ids
            else BASE_OFFICER_RESOLUTION_RATE
        )
        resolved = random.random() < resolution_rate

        if resolved:
            case_status = "Closed"
            max_duration = max(1, (TODAY - opened_date).days)
            upper = min(200, max_duration)
            lower = min(5, upper)
            closed_date = opened_date + timedelta(days=random.randint(lower, upper))
            if closed_date > TODAY:
                closed_date = TODAY
            report_status = "Closed"
        else:
            closed_date = None
            case_status = random.choices(
                ["Open", "Under Investigation", "Cold Case"], weights=[45, 40, 15], k=1
            )[0]
            report_status = "Verified" if case_status == "Open" else "Under Investigation"

        cur.execute(
            """
            UPDATE crime_reports SET status = %s WHERE report_id = %s
            """,
            (report_status, r["report_id"]),
        )

        cur.execute(
            """
            INSERT INTO cases (report_id, assigned_officer_id, opened_date, closed_date, case_status)
            VALUES (%s, %s, %s, %s, %s) RETURNING case_id
            """,
            (r["report_id"], assigned_officer_id, opened_date, closed_date, case_status),
        )
        case_id = cur.fetchone()[0]

        cases.append(
            {
                "case_id": case_id,
                "report_id": r["report_id"],
                "station_id": r["station_id"],
                "assigned_officer_id": assigned_officer_id,
                "opened_date": opened_date,
                "closed_date": closed_date,
                "resolved": resolved,
            }
        )

    return cases


def seed_case_links(cur, cases, criminal_ids, victim_ids):
    criminal_rows, victim_rows = [], []
    for c in cases:
        n_criminals = random.choices([1, 2, 3], weights=[70, 25, 5], k=1)[0]
        for cid in random.sample(criminal_ids, n_criminals):
            criminal_rows.append((c["case_id"], cid))

        n_victims = random.choices([0, 1, 2, 3], weights=[10, 55, 25, 10], k=1)[0]
        for vid in random.sample(victim_ids, n_victims):
            victim_rows.append((c["case_id"], vid))

    if criminal_rows:
        cur.executemany(
            "INSERT INTO case_criminals (case_id, criminal_id) VALUES (%s, %s)",
            criminal_rows,
        )
    if victim_rows:
        cur.executemany(
            "INSERT INTO case_victims (case_id, victim_id) VALUES (%s, %s)",
            victim_rows,
        )


def seed_evidence_and_court(cur, cases, officers_by_station):
    """Only resolved (~70%) cases get evidence + a final court outcome;
    everything else is left genuinely open with no such records."""
    for c in cases:
        if not c["resolved"]:
            continue

        station_officers = officers_by_station[c["station_id"]]
        n_evidence = random.choices([1, 2, 3, 4], weights=[35, 35, 20, 10], k=1)[0]
        span_days = max(1, (c["closed_date"] - c["opened_date"]).days)
        for _ in range(n_evidence):
            collected_date = c["opened_date"] + timedelta(days=random.randint(0, span_days))
            if collected_date > TODAY:
                collected_date = TODAY
            cur.execute(
                """
                INSERT INTO evidence
                    (case_id, type, description, collected_date, storage_location, chain_of_custody_officer)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    c["case_id"],
                    random.choice(EVIDENCE_TYPES),
                    fake.sentence(nb_words=10),
                    collected_date,
                    f"Locker {random.randint(1, 40)}, Evidence Room {random.randint(1, 3)}",
                    random.choice(station_officers),
                ),
            )

        num_hearings = random.choices([1, 2, 3], weights=[50, 35, 15], k=1)[0]
        earliest = c["opened_date"] + timedelta(days=14)
        latest = max(earliest, c["closed_date"])
        span = max(1, (latest - earliest).days)
        hearing_dates = sorted(
            earliest + timedelta(days=int(span * (i + 1) / (num_hearings + 1)))
            for i in range(num_hearings)
        )
        # de-duplicate while preserving order, then ensure strictly increasing
        hearing_dates = sorted(set(hearing_dates))
        while len(hearing_dates) < num_hearings:
            hearing_dates.append(hearing_dates[-1] + timedelta(days=7))

        for i, hearing_date in enumerate(hearing_dates):
            is_last = i == len(hearing_dates) - 1
            if is_last:
                verdict = weighted_choice(VERDICTS_FINAL)
                next_hearing_date = None
            else:
                verdict = "Pending"
                next_hearing_date = hearing_dates[i + 1]
            cur.execute(
                """
                INSERT INTO court_status (case_id, hearing_date, verdict, judge_name, next_hearing_date)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (c["case_id"], hearing_date, verdict, f"Hon. {fake.last_name()}", next_hearing_date),
            )


def seed_case_reassignments(cur, cases, officers_by_station, officer_ids):
    """Gives ~15% of cases a multi-step escalation/reassignment history for
    the recursive CTE demo (db/sql_features/ctes.sql).

    The chain is built backwards from the officer already recorded on the
    case (cases.assigned_officer_id, set in seed_cases()) so that column
    never needs to change here -- the last step in every chain simply
    reproduces the case's current officer, and earlier steps invent
    plausible prior officers who held it before. This keeps the resolution-
    rate pattern already verified in Phase 2 (which is keyed off
    assigned_officer_id) completely unaffected by adding this history.
    """
    reassigned_cases = random.sample(cases, int(len(cases) * REASSIGNMENT_CASE_SHARE))

    for c in reassigned_cases:
        final_officer = c["assigned_officer_id"]
        station_officers = officers_by_station[c["station_id"]]

        num_steps = random.choices([2, 3, 4], weights=[60, 30, 10], k=1)[0]
        prior_pool = [o for o in station_officers if o != final_officer]
        if len(prior_pool) < num_steps - 1:
            prior_pool = [o for o in officer_ids if o != final_officer]
        prior_officers = random.sample(prior_pool, min(num_steps - 1, len(prior_pool)))
        chain_officers = prior_officers + [final_officer]

        end = c["closed_date"] or TODAY
        span_days = max(len(chain_officers), (end - c["opened_date"]).days)
        step_offsets = sorted(
            random.sample(range(span_days), len(chain_officers))
            if span_days >= len(chain_officers)
            else range(len(chain_officers))
        )

        previous_reassignment_id = None
        for i, officer_id in enumerate(chain_officers):
            reassigned_at = random_datetime_in(c["opened_date"] + timedelta(days=step_offsets[i]))
            reason = "Initial Assignment" if i == 0 else random.choice(REASSIGNMENT_REASONS)
            cur.execute(
                """
                INSERT INTO case_reassignments
                    (case_id, previous_reassignment_id, officer_id, reassigned_at, reason)
                VALUES (%s, %s, %s, %s, %s) RETURNING case_reassignment_id
                """,
                (c["case_id"], previous_reassignment_id, officer_id, reassigned_at, reason),
            )
            previous_reassignment_id = cur.fetchone()[0]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    conn = connect()
    try:
        cur = conn.cursor()

        print("Truncating existing data...")
        truncate_all(cur)
        set_crime_reports_triggers(cur, enabled=False)

        print(f"Seeding {NUM_STATIONS} police stations...")
        station_ids = seed_police_stations(cur)

        print(f"Seeding {NUM_OFFICERS} officers...")
        officer_ids, officers_by_station, star_officer_ids = seed_officers(cur, station_ids)
        print(f"  Star officers (higher resolution rate): {star_officer_ids}")

        print(f"Seeding {NUM_CRIMINALS} criminals...")
        criminal_ids = seed_criminals(cur)

        print(f"Seeding {NUM_VICTIMS} victims...")
        victim_ids = seed_victims(cur)

        print(f"Seeding {NUM_CRIME_REPORTS} crime reports...")
        reports = seed_crime_reports(cur, station_ids, officers_by_station)

        print("Seeding cases...")
        cases = seed_cases(cur, reports, station_ids, officers_by_station, star_officer_ids)

        print("Linking cases to criminals and victims...")
        seed_case_links(cur, cases, criminal_ids, victim_ids)

        print("Seeding evidence and court outcomes for resolved cases...")
        seed_evidence_and_court(cur, cases, officers_by_station)

        print("Seeding case reassignment history...")
        seed_case_reassignments(cur, cases, officers_by_station, officer_ids)

        set_crime_reports_triggers(cur, enabled=True)
        conn.commit()
        print("Done. Committed.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
