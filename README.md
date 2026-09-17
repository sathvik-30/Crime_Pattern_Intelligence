# Crime Pattern Intelligence System

A full-stack crime data platform built as a resume portfolio project: a
normalized PostgreSQL schema, realistic synthetic data with deliberately
engineered patterns, an "advanced SQL" showcase layer (views, window
functions, recursive CTEs, triggers, stored procedures), a Python
analytics layer (geospatial clustering, time-series forecasting), and a
multipage Streamlit dashboard tying it all together.

The goal wasn't just "a CRUD app over a database" — it's meant to
demonstrate the kind of SQL and data-analysis work a law-enforcement
analytics team would actually do: finding hotspots, tracking case
resolution and officer performance, forecasting crime volume, and
recommending patrol allocation, all backed by queries and a schema that
can be explained and defended line by line.

## Key Features

The centerpiece of this project is the **advanced SQL layer**
(`db/sql_features/`) — see [`docs/sql_features.md`](docs/sql_features.md)
for a full what-and-why writeup of every item below:

- **Views** — `vw_officer_workload`, `vw_monthly_crime_summary`,
  `vw_unsolved_cases_aging`
- **Window functions** — `RANK()` for monthly officer leaderboards, a
  running `SUM() OVER (...)` crime total, `LAG()` for month-over-month
  % change per area
- **CTEs** — a 3-step hotspot-ranking pipeline, and a **recursive CTE**
  that walks a self-referencing `case_reassignments` table to reconstruct
  each case's full escalation history
- **Triggers** — auto-closing a case when a court verdict is finalized,
  and a generic JSONB-based audit trigger on every `crime_reports` update
- **Stored procedures** — `sp_assign_case` (enforces a per-officer
  workload cap) and `sp_close_case` (writes a verdict and closes the
  case in one transaction)
- **Indexing case study** — a real before/after `EXPLAIN ANALYZE`
  benchmark (3.58ms → 1.68ms, ~53% faster) for a composite index; see
  [`docs/indexing_case_study.md`](docs/indexing_case_study.md)

Beyond the SQL layer: DBSCAN hotspot detection (chosen deliberately over
k-means — no need to pre-specify cluster count, and it correctly treats
sparse outliers as noise rather than forcing them into a cluster), an
ARIMA crime-volume forecast, and a 5-page Streamlit dashboard where every
filter reaches the underlying SQL rather than just slicing an
already-fetched table.

## Architecture

```mermaid
flowchart TB
    subgraph db["PostgreSQL"]
        schema["10-table schema\n(db/migrations/001-010)"]
        extras["case_reassignments,\ncrime_reports_audit\n(migrations 011-012)"]
        idx["composite index\n(migration 013)"]
        sqlfeatures["views · triggers · procedures\n(db/sql_features)"]
    end

    seed["db/seed/generate_seed_data.py\nFaker + pg8000"] -->|idempotent load| db

    subgraph analytics["/analytics  (SQLAlchemy + psycopg2)"]
        heatmap["heatmap.py"]
        timeseries["time_series.py\n(statsmodels: decomposition + ARIMA)"]
        hotspot["hotspot_clustering.py\n(scikit-learn: DBSCAN)"]
        resource["resource_allocation.py\n(scikit-learn: linear regression)"]
    end

    db -->|queries| analytics

    subgraph dashboard["/dashboard  (Streamlit, 5 pages)"]
        overview["Overview"]
        geo["Geographic"]
        officer["Officer Performance"]
        caseres["Case Resolution"]
        predictive["Predictive"]
    end

    db -->|queries, cached| dashboard
    analytics -->|reused directly| dashboard

    user(("Browser")) --> dashboard
```

## Tech Stack

| Layer | Technology |
|---|---|
| Database | PostgreSQL 15+ |
| Schema & migrations | Plain versioned SQL, no ORM/migration framework |
| Seed data | Python, [Faker](https://faker.readthedocs.io/), [pg8000](https://github.com/tlocke/pg8000) |
| Advanced SQL | Views, window functions, CTEs (incl. recursive), triggers, stored procedures |
| Analytics | pandas, NumPy, scikit-learn (DBSCAN, linear regression), statsmodels (seasonal decomposition, ARIMA), SQLAlchemy, psycopg2 |
| Visualization | Plotly, Folium |
| Dashboard | Streamlit (multipage), streamlit-folium |
| Local dev | Docker Compose, python-dotenv |

## Entity-Relationship Diagram

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

`case_reassignments` and `crime_reports_audit` (added in migrations 011
and 012 to support the recursive CTE and the audit trigger) are omitted
from this diagram for readability — see those migration files directly.

## Screenshots

| Overview | Geographic |
|---|---|
| ![Overview](docs/screenshots/01_overview.jpg) | ![Geographic](docs/screenshots/02_geographic.jpg) |

| Officer Performance | Case Resolution |
|---|---|
| ![Officer Performance](docs/screenshots/03_officer_performance.jpg) | ![Case Resolution](docs/screenshots/04_case_resolution.jpg) |

| Predictive |
|---|
| ![Predictive](docs/screenshots/05_predictive.jpg) |

## Setup (from a clean clone)

These steps assume nothing is installed yet beyond Python 3.10+ and
either Docker or an existing PostgreSQL 15+ server.

### 1. Get a PostgreSQL database running

**Option A — Docker (recommended, zero local Postgres install needed):**

```bash
docker compose up -d
```

This starts Postgres 15 on `localhost:5432` with database
`crime_pattern_intelligence`, user `cpi_user`, password `cpi_password`
(see `docker-compose.yml`).

**Option B — an existing local PostgreSQL server:**

```bash
createdb crime_pattern_intelligence
```

On Windows, the PostgreSQL installer doesn't always add `psql`/`createdb`/
`dropdb` to `PATH`. If `createdb: command not found` (or similar), either
add `<PostgreSQL install dir>\bin` (e.g.
`C:\Program Files\PostgreSQL\18\bin`) to `PATH`, or call these tools by
their full path for every `psql`/`createdb`/`dropdb` command below.

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` if you're not using the Docker Compose defaults (different
host/port/user/password/database name).

### 3. Install Python dependencies

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

One `requirements.txt` covers the seed script, the analytics modules,
and the dashboard — see **Troubleshooting** below if `pip install` tries
to *compile* `numpy`/`pandas`/`scikit-learn` instead of installing a
prebuilt wheel.

### 4. Create the schema

With the Docker Compose / `.env.example` defaults:

```bash
for f in db/migrations/*.sql; do
  psql "postgresql://cpi_user:cpi_password@localhost:5432/crime_pattern_intelligence" -v ON_ERROR_STOP=1 -f "$f"
done
```

(Swap in your own user/password/host/port/database if you edited `.env`
to point somewhere else.) Migrations are plain numbered SQL files with
no runner dependency — apply them in filename order with any tool
(`psql`, a migration framework, a CI step).

### 5. Install the SQL feature layer (views, triggers, procedures)

**This step is easy to miss** — it's not part of the numbered
migrations (see *Design Decisions* below for why), but the dashboard's
Officer Performance page and the trigger/procedure demos depend on it:

```bash
psql "postgresql://cpi_user:cpi_password@localhost:5432/crime_pattern_intelligence" -f db/sql_features/views.sql
psql "postgresql://cpi_user:cpi_password@localhost:5432/crime_pattern_intelligence" -f db/sql_features/triggers.sql
psql "postgresql://cpi_user:cpi_password@localhost:5432/crime_pattern_intelligence" -f db/sql_features/procedures.sql
```

(`db/sql_features/window_functions.sql` and `ctes.sql` are standalone
example queries, not schema objects — run them ad hoc in `psql` to
explore, they don't need to be "installed.")

### 6. Load synthetic seed data

```bash
python db/seed/generate_seed_data.py
```

Idempotent — truncates and reloads deterministically every time it's
run, so re-running it is always safe.

### 7. Launch the dashboard

```bash
streamlit run dashboard/app.py
```

Open the printed local URL (default `http://localhost:8501`) — you
should land on the Overview page with populated KPI cards.

### Troubleshooting: pip tries to compile numpy/pandas from source

This means your Python build doesn't have prebuilt wheels available for
it on PyPI — most commonly an MSYS2/MinGW Python (check with
`python -c "import sysconfig; print(sysconfig.get_platform())"`; a
result like `mingw_x86_64_ucrt_gnu` rather than `win-amd64` confirms it).
Install a standard CPython build instead (from
[python.org](https://python.org) or [Anaconda](https://anaconda.com))
and create your venv from that instead.

## Project Structure

```
db/migrations/    Versioned SQL migrations — the core schema (run first)
db/seed/          Synthetic data generator (Faker + pg8000)
db/sql_features/  Views, window functions, CTEs, triggers, procedures
analytics/        Python analytics modules (heatmap, forecasting, clustering, allocation)
dashboard/        5-page Streamlit multipage app
docs/             sql_features.md, indexing_case_study.md, screenshots/
docker-compose.yml   PostgreSQL 15 for local development
requirements.txt     Pinned dependencies for the whole project
.env.example         Template for required environment variables
```

## Design Decisions

<details>
<summary><b>Schema (Phase 1)</b></summary>

- **3NF**: every non-key column depends only on its table's primary key;
  station/officer identity isn't repeated on `crime_reports` beyond the
  FK, and criminal/victim details aren't duplicated per case (the
  junction tables `case_criminals`/`case_victims` carry only the
  relationship).
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
- **Views/triggers/procedures live outside `db/migrations/`
  on purpose**: migrations are the versioned *structural* schema;
  `db/sql_features/` is a separate "SQL showcase" layer built on top of
  it in Phase 3. The tradeoff is the manual install step in Setup #5
  above — worth knowing if you're debugging a fresh setup where a view
  seems to be "missing."

</details>

<details>
<summary><b>Seed data (Phase 2)</b></summary>

- **Deterministic**: a fixed random seed means every fresh run produces
  the same dataset, including which two officers become the
  high-performing "star officers" and which area becomes the fast-rising
  hotspot — useful for grading/demoing against known numbers.
- **Idempotent via `TRUNCATE ... RESTART IDENTITY CASCADE`**, not
  check-before-insert — simpler and correct for a synthetic dataset
  that's meant to be fully regenerated, not incrementally patched.
- **Disables user triggers during its own bulk load**
  (`ALTER TABLE crime_reports DISABLE TRIGGER USER`, not `ALL` — `ALL`
  would also disable FK-enforcement triggers) so the seed script's own
  internal status-fixup `UPDATE` doesn't pollute the audit trigger's
  table with rows that aren't real application activity.

</details>

<details>
<summary><b>Analytics & Dashboard (Phases 4-5)</b></summary>

- **DBSCAN over k-means** for hotspot detection: hotspots are irregularly
  shaped (k-means forces round, convex clusters), the "right" number of
  hotspots isn't known in advance (k-means requires choosing k upfront),
  and DBSCAN explicitly labels sparse points as noise instead of forcing
  every point into the nearest cluster.
- **ARIMA over Prophet** for forecasting (the task allowed either):
  Prophet needs a separate Stan/C++ backend that's a heavy, fragile
  dependency for a small monthly series; ARIMA is pure numpy/scipy via
  statsmodels, a library already used for seasonal decomposition.
- **Dashboard filters reach the SQL, not just the display**: every
  analytics loader a filterable page uses was extended with optional
  `date_from`/`date_to`/`crime_types`/`areas` keyword arguments (default
  `None`, so Phase 4's standalone script behavior is unchanged) via a
  shared `analytics/db.crime_report_filters()` helper.
- **Caching**: `dashboard/common.py` wraps the SQLAlchemy engine in
  `st.cache_resource` and every query function uses `st.cache_data`
  (keyed on the real filter values, with a leading-underscore `_engine`
  parameter — Streamlit's convention for excluding an argument from the
  cache key).

Two real bugs were caught and fixed during Phase 5 verification (not
just claimed to work — verified with `streamlit.testing.v1.AppTest` in
fresh, isolated processes per page, plus a real `streamlit run` smoke
test): a date-range filter that silently dropped the entire last day of
data (comparing a `TIMESTAMP` column `<=` a plain `DATE` casts to
midnight), and every dashboard page depending on Python having already
cached a shared `common` module from a previous page's import rather
than resolving its own path independently.

</details>

## Verifying it all works

Everything in this repo has been run against a real PostgreSQL instance,
not just checked for syntax:

- All 13 migrations apply cleanly to a fresh database (verified again
  from scratch while writing this document, which is how the missing
  Setup #5 step above was caught).
- The seed script has been run repeatedly and reproduces the same
  deterministic dataset every time.
- Every view, trigger, and procedure in `db/sql_features/` was exercised
  with real `INSERT`/`UPDATE` statements, including failure paths
  (workload cap exceeded, invalid verdict rejected) — see
  `docs/sql_features.md`.
- All 4 analytics modules run standalone and their output was checked
  against the seed data's known, deliberately engineered patterns
  (hotspot areas, seasonal crime type, high-performing officers).
- All 5 dashboard pages load without exceptions (via `AppTest`, each in
  its own fresh process) and a live `streamlit run` server returns
  HTTP 200 on every page route, with filters confirmed to actually
  change query results.
- Re-verified end-to-end from a truly clean clone (Docker unavailable, so
  via Option B): `db/seed/generate_seed_data.py` previously ignored
  `.env` entirely (it read `os.environ` directly with no `load_dotenv()`
  call, unlike `analytics/db.py`), so it silently connected with the
  Docker-default credentials no matter what `.env` said — now fixed to
  load `.env` the same way `analytics/db.py` does.
