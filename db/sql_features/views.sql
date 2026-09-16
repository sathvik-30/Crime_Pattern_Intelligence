-- views.sql
-- Reusable read models over the base schema. Each view answers a question
-- the dashboard/analytics phases will ask repeatedly, so the logic lives
-- in one place instead of being copy-pasted into every query that needs it.

-- ---------------------------------------------------------------------------
-- vw_officer_workload
--
-- One row per officer with their open (unresolved) and total case counts.
--
-- WHY a LEFT JOIN from officers: an INNER JOIN would silently drop officers
-- with zero assigned cases, which is exactly the group a workload-balancing
-- view needs to surface (they're the ones who can take on more work).
--
-- WHY COUNT(...) FILTER (WHERE ...) instead of a CASE WHEN inside SUM(), or
-- a second correlated subquery: FILTER is standard SQL, reads as "count
-- these rows, filtered", and lets one aggregate pass over the joined rows
-- produce both the open and total counts without scanning cases twice.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_officer_workload AS
SELECT
    o.officer_id,
    o.name                                                  AS officer_name,
    o.rank,
    ps.station_id,
    ps.name                                                  AS station_name,
    COUNT(c.case_id) FILTER (WHERE c.case_status <> 'Closed') AS open_case_count,
    COUNT(c.case_id)                                          AS total_case_count
FROM officers o
JOIN police_stations ps ON ps.station_id = o.station_id
LEFT JOIN cases c ON c.assigned_officer_id = o.officer_id
GROUP BY o.officer_id, o.name, o.rank, ps.station_id, ps.name;


-- ---------------------------------------------------------------------------
-- vw_monthly_crime_summary
--
-- Crime counts bucketed by month/area/crime_type, the grain almost every
-- "trend" or "hotspot" chart in the dashboard phase will pivot on.
--
-- WHY DATE_TRUNC('month', ...) rather than TO_CHAR(...,'YYYY-MM'): it
-- returns a real timestamp/date, so callers can still use date comparisons
-- and ORDER BY chronologically instead of sorting a string.
--
-- WHY a separate high_severity_count column instead of a second view: it's
-- a one-line FILTER on the same GROUP BY, and callers who don't need it
-- just don't select it -- cheaper than maintaining two near-identical views.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_monthly_crime_summary AS
SELECT
    DATE_TRUNC('month', date_occurred)::date AS month,
    area,
    crime_type,
    COUNT(*)                                              AS crime_count,
    COUNT(*) FILTER (WHERE severity IN ('High', 'Critical')) AS high_severity_count
FROM crime_reports
GROUP BY DATE_TRUNC('month', date_occurred)::date, area, crime_type;


-- ---------------------------------------------------------------------------
-- vw_unsolved_cases_aging
--
-- Every case that has been open more than 90 days, oldest first -- the
-- worklist for "what's stalling."
--
-- WHY case_status <> 'Closed' rather than = 'Open': the schema has three
-- non-closed statuses (Open, Under Investigation, Cold Case) and all three
-- belong on an aging report; excluding only 'Closed' is both simpler and
-- correct if a new non-closed status is ever added.
--
-- WHY CURRENT_DATE - opened_date rather than AGE(): subtracting two DATEs
-- in Postgres returns a plain integer number of days, which is exactly
-- what "how many days has this been open" means and sorts/filters cleanly;
-- AGE() returns an interval (years/months/days) that's better for display
-- than for arithmetic or ORDER BY.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_unsolved_cases_aging AS
SELECT
    c.case_id,
    c.report_id,
    cr.crime_type,
    cr.area,
    cr.severity,
    o.officer_id                    AS assigned_officer_id,
    o.name                          AS assigned_officer_name,
    c.case_status,
    c.opened_date,
    (CURRENT_DATE - c.opened_date)  AS days_open
FROM cases c
JOIN crime_reports cr ON cr.report_id = c.report_id
JOIN officers o ON o.officer_id = c.assigned_officer_id
WHERE c.case_status <> 'Closed'
  AND (CURRENT_DATE - c.opened_date) > 90
ORDER BY days_open DESC;
