# Crime Pattern Intelligence System

A resume portfolio project modeling and analyzing crime report data. Built in
phases:

1. **Database schema** (this phase) — normalized PostgreSQL schema, migrations, ERD
2. Data seeding / ingestion
3. Pattern analysis (SQL / analytics)
4. Dashboard
5. TBD
6. TBD

## Phase 1: Database Schema

### Project structure

```
db/migrations/   Versioned SQL migrations (run in numeric order)
analytics/        Reserved for Phase 3 analysis scripts/notebooks
dashboard/        Reserved for Phase 4 dashboard app
docs/             Reserved for design notes / write-ups
docker-compose.yml PostgreSQL 15 for local development
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
