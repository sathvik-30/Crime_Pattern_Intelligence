# Crime Pattern Intelligence System

A resume portfolio project modeling and analyzing crime report data. Built in
phases:

1. **Database schema** — normalized PostgreSQL schema, migrations, ERD
2. **Synthetic seed data** — Faker-generated, idempotent, with deliberately
   baked-in patterns for later analytics to find
3. **Advanced SQL layer** — views, window functions, CTEs, triggers,
   stored procedures, an indexing case study
4. **Python analytics layer** — heatmap, time-series/forecasting, DBSCAN
   hotspot clustering, patrol resource allocation
5. **Streamlit dashboard** — 5-page multipage app over the SQL/analytics layers
6. TBD

## Phase 1: Database Schema

### Project structure

```
db/migrations/    Versioned SQL migrations (run in numeric order)
db/seed/          Synthetic data generator (Phase 2)
db/sql_features/  Views, window functions, CTEs, triggers, procedures (Phase 3)
analytics/        Python analytics modules (Phase 4)
dashboard/        5-page Streamlit multipage app (Phase 5)
docs/             Design notes / write-ups (indexing case study, etc.)
docker-compose.yml PostgreSQL 15 for local development
requirements.txt  Dependencies for analytics/ and dashboard/
```

### Entity-relationship diagram

```mermaid
erDiagram
    POLICE_STATIONS ||--o{ OFFICERS : staffs
    POLICE_STATIONS ||--o{ CRIME_REPORTS : files
    OFFICERS ||--o{ CRIME_REPORTS : reports
    OFFICERS ||--o{ CASES : "is assigned"
    OFFICERS ||--o{ EVIDENCE : "has custody of"
    CRIME_REPORTS ||--o| CASES : opens
    CASES ||--o{ CASE_CRIMINALS : names
    CRIMINALS ||--o{ CASE_CRIMINALS : "is named in"
    CASES ||--o{ CASE_VICTIMS : involves
    VICTIMS ||--o{ CASE_VICTIMS : "is involved in"
    CASES ||--o{ EVIDENCE : has
    CASES ||--o{ COURT_STATUS : "goes through"

    POLICE_STATIONS {
        int station_id PK
        varchar name
        varchar jurisdiction_area
        varchar contact_no
    }

    OFFICERS {
        int officer_id PK
        varchar name
        varchar rank
        int station_id FK
        varchar badge_no
        date joining_date
    }

    CRIMINALS {
        int criminal_id PK
        varchar name
        date dob
        varchar gender
        text address
        int prior_convictions_count
    }

    VICTIMS {
        int victim_id PK
        varchar name
        int age
        varchar gender
        varchar contact_no
        text address
    }

    CRIME_REPORTS {
        int report_id PK
        varchar crime_type
        timestamp date_reported
        timestamp date_occurred
        numeric location_lat
        numeric location_lng
        varchar area
        int station_id FK
        int reporting_officer_id FK
        varchar severity
        varchar status
    }

    CASES {
        int case_id PK
        int report_id FK
        int assigned_officer_id FK
        date opened_date
        date closed_date
        varchar case_status
    }

    CASE_CRIMINALS {
        int case_id FK
        int criminal_id FK
    }

    CASE_VICTIMS {
        int case_id FK
        int victim_id FK
    }

    EVIDENCE {
        int evidence_id PK
        int case_id FK
        varchar type
        text description
        date collected_date
        varchar storage_location
        int chain_of_custody_officer FK
    }

    COURT_STATUS {
        int court_id PK
        int case_id FK
        date hearing_date
        varchar verdict
        varchar judge_name
        date next_hearing_date
    }
```

### Design notes

- **3NF**: every non-key column depends only on its table's primary key;
  station/officer identity isn't repeated on `crime_reports` beyond the FK,
  and criminal/victim details aren't duplicated per case (the junction
  tables `case_criminals` / `case_victims` carry only the relationship).
- **Constrained value sets** (severity, statuses, gender, rank, evidence
  type, verdict) use `CHECK` constraints rather than native Postgres
  `ENUM` types, so adding a new allowed value later is a single
  `ALTER TABLE ... DROP/ADD CONSTRAINT` in a new migration instead of the
  more restrictive `ALTER TYPE ... ADD VALUE` (which can't run inside a
  transaction with other changes).
- **`cases.report_id` is `UNIQUE`**: one crime report opens at most one
  investigative case.
- **Foreign keys use `ON DELETE RESTRICT`** for reference-style parents
  (stations, officers, criminals, victims, reports) so a row with
  dependent history can't be silently deleted, and `ON DELETE CASCADE`
  from `cases` down to `case_criminals`, `case_victims`, `evidence`, and
  `court_status`, since those rows have no meaning without their case.
- **Indexes** are added on every foreign key and on the columns Phase 3's
  pattern analysis will filter/group by most (`date_occurred`, `area`,
  `crime_type`); each migration comments why the index exists.

### Running locally

**Option A — Docker:**

```bash
docker compose up -d
psql "postgresql://cpi_user:cpi_password@localhost:5432/crime_pattern_intelligence" \
  -f db/migrations/001_create_police_stations.sql \
  # ...repeat in order, or use a migration runner of your choice
```

**Option B — an existing local PostgreSQL instance:**

```bash
createdb crime_pattern_intelligence
for f in db/migrations/*.sql; do
  psql -d crime_pattern_intelligence -f "$f"
done
```

Migrations are plain SQL with no runner dependency — apply them in
filename order with any tool (`psql`, a migration framework, CI step, etc.).

## Phase 4: Python Analytics Layer

Four standalone modules under `/analytics`, each runnable on its own and
each returning DataFrames/dicts a Phase 5 Streamlit dashboard can import
directly:

- `heatmap.py` — geographic density heatmap (folium)
- `time_series.py` — monthly/weekly trends, seasonal decomposition, and a
  next-month ARIMA forecast (pandas + statsmodels)
- `hotspot_clustering.py` — DBSCAN hotspot detection on crime lat/lng
  (scikit-learn)
- `resource_allocation.py` — a simple linear-regression estimate of which
  area/shift needs additional patrol coverage next month, plus an officer
  resolution-rate leaderboard

### Setup

```bash
cp .env.example .env   # fill in your local DB credentials
pip install -r requirements.txt
python analytics/heatmap.py
python analytics/time_series.py
python analytics/hotspot_clustering.py
python analytics/resource_allocation.py
```

Each writes its output (an HTML map/chart and/or a CSV) to
`analytics/output/` (gitignored — regenerate by re-running the module).

### Environments

This project uses **two separate Python environments**, not by design but
because of a real constraint worth documenting: the Python available in
this project's original dev shell is an MSYS2/MinGW build (platform tag
`mingw_x86_64_ucrt_gnu`), which cannot install the standard PyPI wheels
that `numpy`/`pandas`/`scikit-learn`/`statsmodels` publish (those target
the `win_amd64` tag) — pip falls back to a source build, which fails
without a full scientific-computing toolchain (BLAS/LAPACK/Fortran). It's
also why `db/seed/generate_seed_data.py` (Phase 2) uses `pg8000` instead
of `psycopg2-binary`, for the identical reason.

- `db/seed/generate_seed_data.py` only needs `faker` + `pg8000` (both
  pure Python) and runs fine under that MSYS2 Python.
- Everything under `/analytics` and `/dashboard` needs the full
  scientific-Python stack and `requirements.txt` here targets a standard
  CPython build (e.g. python.org, Anaconda) with normal `win_amd64` wheel
  support — use a venv built from one of those for this part of the
  project.

## Phase 5: Streamlit Dashboard

A 5-page multipage app under `/dashboard`, built directly on the Phase 3
SQL layer and Phase 4 analytics modules rather than reimplementing their
queries:

1. **Overview** (`dashboard/app.py`) — KPI cards (total cases, resolution
   rate, active cases, avg. time-to-resolution) and a crime trend chart
2. **Geographic** (`pages/2_Geographic.py`) — the heatmap from
   `analytics/heatmap.py` with the DBSCAN cluster overlay from
   `analytics/hotspot_clustering.py`, filterable by date range/crime
   type/area
3. **Officer Performance** (`pages/3_Officer_Performance.py`) — the
   `vw_officer_workload` view and the `RANK() OVER (...)` monthly
   resolution ranking from `db/sql_features/window_functions.sql`
4. **Case Resolution** (`pages/4_Case_Resolution.py`) — a funnel from
   reported → under investigation → reached court → final verdict
5. **Predictive** (`pages/5_Predictive.py`) — the forecast chart from
   `analytics/time_series.py` and the patrol allocation table from
   `analytics/resource_allocation.py`

### Running it

```bash
pip install -r requirements.txt   # same venv as Phase 4 -- see Environments above
streamlit run dashboard/app.py
```

### Design notes

- **Caching**: `dashboard/common.py` wraps the SQLAlchemy engine in
  `st.cache_resource` (one connection resource per session) and every
  query-loading function uses `st.cache_data` (cached return values,
  keyed on the actual filter arguments) with a leading-underscore
  `_engine` parameter — Streamlit's documented convention for excluding
  an argument from the cache key when it isn't itself meaningfully
  hashable data.
- **Filters reach the SQL, not just the display**: every analytics loader
  from Phase 4 that a filterable page uses (`load_crime_locations`,
  `load_locations`, `load_monthly_counts`) was extended with optional
  `date_from`/`date_to`/`crime_types`/`areas` keyword arguments (default
  `None`, so their Phase 4 standalone behavior is unchanged) built via a
  new shared `analytics/db.crime_report_filters()` helper, so a filter
  narrows the WHERE clause of the underlying query instead of slicing an
  already-fetched DataFrame.
- **A real bug this caught**: `crime_report_filters()` originally compared
  the TIMESTAMP `date_occurred` column with `<= date_to`, where `date_to`
  is a plain DATE from `st.date_input`. Postgres casts the DATE to
  midnight for that comparison, which silently excluded almost every
  report on the end date itself. Fixed by comparing
  `< date_to + INTERVAL '1 day'` instead — caught by testing the Overview
  page's "Total Cases" KPI against the known seeded total (508) and
  finding it undercounting.
- **Every page is independently importable**, not just runnable through
  `app.py`: each page file (including `app.py`) searches upward from its
  own location for the directory containing `common.py` and adds it to
  `sys.path` before importing, rather than relying on Python having
  already cached the `common` module from a previous page's import in
  the same process — verified by running each page through
  `streamlit.testing.v1.AppTest` in its own fresh process, not just
  sequentially in one.
