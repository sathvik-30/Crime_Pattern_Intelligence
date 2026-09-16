# SQL Features — Interview Prep

Every feature below lives in `db/sql_features/` as runnable SQL, verified
against the seeded database with real inserts/updates (not just checked
for syntax). This document explains **what** each one does and **why**
it was built that way, so you can walk through the reasoning out loud
without re-deriving it live in an interview.

---

## Views (`db/sql_features/views.sql`)

### `vw_officer_workload`

**What it does:** one row per officer, with an `open_case_count` (cases
not yet `Closed`) and a `total_case_count`, joined up to their station.

**Why built this way:**
- It's a `LEFT JOIN` from `officers`, not an `INNER JOIN`. An inner join
  would silently drop any officer with zero assigned cases — exactly the
  officers a workload-balancing view most needs to surface, since
  they're the ones with room to take on more.
- The two counts come from **one aggregate pass** using
  `COUNT(c.case_id) FILTER (WHERE c.case_status <> 'Closed')` alongside a
  plain `COUNT(c.case_id)`, rather than either a `CASE WHEN` inside a
  `SUM()` or two separate correlated subqueries. `FILTER` is standard SQL
  and reads as "count these rows, filtered" — one join, one scan of
  `cases` for both numbers.

**If asked "why not just use a subquery for open case count":** a
correlated subquery per officer would mean N extra scans of `cases` (one
per officer); the `FILTER` clause computes both numbers in the same
grouped aggregation Postgres already has to do for the join.

### `vw_monthly_crime_summary`

**What it does:** crime counts bucketed by month × area × crime_type,
plus a `high_severity_count` for the same grain.

**Why built this way:**
- `DATE_TRUNC('month', date_occurred)::date` instead of
  `TO_CHAR(date_occurred, 'YYYY-MM')`. The result is a real `date`, so
  consumers can still do date comparisons and `ORDER BY` chronologically
  — a string like `'2025-03'` would sort correctly by coincidence for
  this format, but a date type doesn't rely on that coincidence, and
  supports date arithmetic (e.g. "last 3 months") directly.
- `high_severity_count` is one more `FILTER` on the same `GROUP BY`
  rather than a second view — cheaper to maintain than two near-duplicate
  view definitions, and callers who don't need the column just don't
  select it.

### `vw_unsolved_cases_aging`

**What it does:** every case open more than 90 days, oldest first.

**Why built this way:**
- Filters `case_status <> 'Closed'`, not `= 'Open'`. The schema has
  **three** non-closed statuses (`Open`, `Under Investigation`,
  `Cold Case`); all three belong on an aging report. Excluding only
  `'Closed'` is both simpler to write and correct-by-construction if a
  new non-closed status is ever added later — no risk of the view
  quietly missing a new status value.
- `CURRENT_DATE - c.opened_date` rather than `AGE(...)`. Subtracting two
  `DATE`s in Postgres returns a plain integer number of days — exactly
  what "how long has this been open" means, and it sorts/filters as a
  number. `AGE()` returns an interval (years/months/days), which is
  nicer for *display* but awkward for arithmetic or `ORDER BY`.

---

## Window Functions (`db/sql_features/window_functions.sql`)

### 1. `RANK() OVER (PARTITION BY month ORDER BY cases_resolved DESC)`

**What it does:** ranks officers by cases resolved, independently within
each month.

**Why `RANK()` and not `ROW_NUMBER()` or `DENSE_RANK()`:** ties matter
here — two officers resolving the same count in the same month should
show the *same* rank, which rules out `ROW_NUMBER()` (which would
arbitrarily break the tie and assign 1 and 2). `RANK()` also leaves a
gap after a tie (`1, 1, 3`, not `1, 1, 2` like `DENSE_RANK()` would give)
— correctly reflecting that if two people are tied for 1st, nobody is
really in 2nd place.

**Why a CTE runs the aggregation first:** window functions logically run
*after* `GROUP BY`, but you can't reliably reference an aggregate
alias inside the same `SELECT`'s window clause. The monthly aggregation
(`monthly_resolutions`) is computed once in a CTE, and the window
function is applied to that already-aggregated result.

### 2. `SUM(...) OVER (ORDER BY month ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)`

**What it does:** a running (cumulative) total of crimes reported,
month over month.

**Why the explicit `ROWS BETWEEN` frame instead of relying on the
default:** with no frame clause, Postgres defaults to
`RANGE UNBOUNDED PRECEDING AND CURRENT ROW`, which happens to give the
same running-total result *here* since `month` is unique per row — but
spelling out `ROWS` makes the intent ("sum every prior row, one at a
time") unambiguous regardless of what the `ORDER BY` column looks like,
rather than relying on RANGE's tie-handling behavior to coincidentally
do the right thing.

### 3. `LAG(crime_count) OVER (PARTITION BY area ORDER BY month)`

**What it does:** month-over-month % change in crime count, per area.

**Why `PARTITION BY area` is essential:** without it, `LAG()` would pull
the previous row in the *entire* result set regardless of area —
comparing, say, Riverside's January to Old Town's December. Partitioning
resets the window per area so each area's trend is measured against its
own past, not an arbitrary neighbor's.

**Why `NULLIF(..., 0)`:** guards the percentage-change division against
a divide-by-zero for any area that had zero reports the prior month,
turning the result into `NULL` ("undefined change") instead of crashing
the query outright.

---

## CTEs (`db/sql_features/ctes.sql`)

### 1. Multi-step CTE: hotspot ranking

**What it does:** aggregates crimes by area/month, totals by area, then
ranks areas by total volume — a 3-step pipeline
(`area_month_counts` → `area_totals` → `ranked_areas`).

**Why three chained CTEs instead of nested subqueries:** each step
*names* an intermediate result, so the query reads top-to-bottom the
same way you'd explain the logic out loud: "first bucket by month, then
total per area, then rank those totals." A deeply nested subquery
version computes the identical result but hides that narrative from
whoever reads it next.

**Why rank on `total_crimes`, not `avg_monthly_crimes`:** an area with a
short but severe recent spike should still outrank a chronically
low-but-steady area for "hotspot" purposes — summing preserves that
signal, while averaging would dilute a real spike across quiet months.
The average is still reported as context, just not used for ranking.

### 2. Recursive CTE: case escalation history

**What it does:** walks `case_reassignments` (a self-referencing table
added specifically to support this — see `db/migrations/011`) to
reconstruct each reassigned case's full officer-to-officer history as
one row, with a concatenated `escalation_path` like `"31 -> 15"`.

**Why a linked list (`previous_reassignment_id`) instead of just sorting
by `reassigned_at`:** relying on timestamp order to reconstruct sequence
is fragile (two reassignments could land in the same second) and isn't
"recursive" in spirit. `previous_reassignment_id` makes each case's
history an explicit linked list, which is exactly the data shape a
recursive CTE is built to walk.

**Why the anchor is `previous_reassignment_id IS NULL`:** that's the
base case of the recursion — every case's history starts at exactly one
row with no predecessor, seeding one row per case-with-history into the
result.

**Why the recursive term joins `nxt.previous_reassignment_id =
prev.case_reassignment_id`:** this is the walk-forward step. For every
row already reached, find the row (if any) that names it as its
predecessor, and add it. Recursion terminates naturally once no row
points at the most recently added step — no explicit depth limit needed.

**Follow-up rollup (`2b`):** the identical recursive query, then
`GROUP BY case_id` to answer "which cases were escalated the most" —
demonstrates that a recursive CTE's result composes with ordinary
aggregation just like any other subquery.

---

## Triggers (`db/sql_features/triggers.sql`)

### 1. Auto-close a case on final verdict

**What it does:** when a `court_status` row receives a *final* verdict
(`Guilty`/`Not Guilty`/`Acquitted`/`Dismissed`/`Settled` — not
`Pending`), the associated `case` is automatically flipped to
`case_status = 'Closed'`.

**Why a trigger instead of relying on application code:** a
`court_status` row can be written by more than one code path
(`sp_close_case`, a future admin UI, a bulk import). A trigger makes
"a final verdict implies a closed case" a property of the *data itself*
— it can't be forgotten by any one of those callers, present or future.

**Why `AFTER INSERT OR UPDATE OF verdict`:** a verdict can arrive either
as a brand-new final-verdict row (`sp_close_case` inserts one directly)
or as an existing `'Pending'` row later updated once a hearing
concludes — both need to trigger the same close-out behavior.

**Why the `WHEN` clause excludes `'Pending'`:** `'Pending'` is itself a
legal value for `verdict` in this schema (an open hearing, no outcome
yet) — only a truly final outcome should close the case. Filtering in
the trigger's `WHEN` clause (evaluated before the function is even
invoked) is cheaper than checking inside the function body on every row.

**Why the function guards with `case_status <> 'Closed'`:** makes the
`UPDATE` a no-op if the case is already closed (e.g. a second hearing
row also carries a final verdict) — avoiding both a redundant write and,
more importantly, overwriting an earlier `closed_date` with a later one.

### 2. Audit trigger on every `crime_reports` UPDATE

**What it does:** logs every `UPDATE` on `crime_reports` into
`crime_reports_audit`, storing the whole old and new row as JSONB plus
`changed_at`/`changed_by`.

**Why `to_jsonb(OLD)`/`to_jsonb(NEW)` for the whole row, instead of one
audit row per changed column:** it's schema-generic — a later
`ALTER TABLE` on `crime_reports` needs no matching change to the trigger
— and it keeps "what changed" computable later with a single JSONB diff,
rather than needing to reassemble N narrow audit rows per `UPDATE`
statement.

**Why the `WHEN (OLD.* IS DISTINCT FROM NEW.*)` guard:** an `UPDATE`
statement can touch a row without changing any of its values (e.g. part
of a broader batch `SET status = status`). `IS DISTINCT FROM` (unlike
`<>`) also handles `NULL`s correctly. Without this guard, running the
seed script's own internal status-fixup step would flood the audit table
with rows that don't represent a real application change — this was an
actual bug caught during Phase 3/5 verification (see
`db/seed/generate_seed_data.py`'s `set_crime_reports_triggers()`, which
also disables *user* triggers — not `ALL`, which would disable FK
enforcement too — during its own bulk load for the same reason).

**Why `changed_by` defaults to `current_user`:** there's no
application-level auth layer in this project yet, so the Postgres role
executing the statement is the only identity available. A real app tier
would improve on this via a session variable
(`SET LOCAL app.current_user_id = ...`) read here instead.

---

## Stored Procedures (`db/sql_features/procedures.sql`)

### `sp_assign_case(p_report_id, p_officer_id, p_reason)`

**What it does:** assigns a report to an officer — creating a new case
if none exists yet, or reassigning an existing one — while enforcing a
workload cap (default: 15 open cases) and always leaving a
`case_reassignments` history row behind.

**Why a `PROCEDURE`, not a `FUNCTION`:** this does multiple writes
(`cases`, `case_reassignments`) as one unit of work with no single
meaningful return value. `PROCEDURE` is Postgres's construct for "run
these statements together," invoked with `CALL` rather than embedded in
a `SELECT`.

**Why the workload check runs — and can `RAISE EXCEPTION` — *before*
any write:** a rejected assignment should leave zero partial state. If
the check ran after the case was created, a failure partway through
would leave an inconsistent case/reassignment record behind.

**Why the "new case" branch ignores `p_reason` and always logs
`'Initial Assignment'`:** a case's first-ever assignment describes a
*fact* ("this is step 1"), not a caller's stated reason — `p_reason` is
only meaningful once there's a prior step to reassign away from.

**Why the latest `case_reassignments` row is found via
`ORDER BY reassigned_at DESC LIMIT 1` rather than tracking a "current
head" pointer elsewhere:** with realistically small history-per-case
counts, the lookup is cheap, and it keeps `case_reassignments` the
single source of truth for "what officer holds this case now" instead
of duplicating that state in a second column somewhere.

### `sp_close_case(p_case_id, p_verdict, p_judge_name)`

**What it does:** records a final court outcome and closes the case in
one step.

**Why validate `p_verdict` here even though `court_status` already has a
`CHECK` constraint covering all six legal verdict values:** the column
`CHECK` enforces "is this a legal value at all"; this procedure
additionally enforces "is this an appropriate value for *closing* a
case." `'Pending'` passes the column-level `CHECK` but makes no sense as
a reason to close a case — rejecting it here gives a clearer,
purpose-specific error than a generic constraint violation would.

**Why `p_judge_name` has a default instead of the task's literal
2-argument shape:** `court_status.judge_name` is `NOT NULL`, so *some*
value is required on every insert. A third parameter with a default
preserves the simple `sp_close_case(case_id, verdict)` call for the
common case while still allowing a real judge's name when known.

**Why the explicit `UPDATE cases SET case_status = 'Closed' ...` at the
end, even though inserting a final-verdict row into `court_status`
already fires the auto-close trigger above:** this makes `sp_close_case`
correct on its own even if that trigger is ever disabled or dropped, at
the cost of one redundant (and, thanks to the trigger's own
`case_status <> 'Closed'` guard, effectively no-op) `UPDATE` in the
common case — a deliberate demonstration of the trigger/procedure
interaction, not an accident.

---

## Indexing

See [`docs/indexing_case_study.md`](indexing_case_study.md) for the full
before/after `EXPLAIN ANALYZE` write-up on the composite
`(area, date_occurred)` index — kept as a separate document since it's a
benchmark narrative rather than a feature-by-feature explanation.
