-- window_functions.sql
-- Three standalone analytical queries demonstrating window functions.
-- These are queries, not views, because each is meant to be read and run
-- on its own for the portfolio write-up/interview walkthrough.

-- ---------------------------------------------------------------------------
-- 1. Rank officers by cases resolved per month
--
-- RANK() OVER (PARTITION BY month ORDER BY cases_resolved DESC) gives each
-- officer their standing within their own month, independent of every
-- other month -- exactly what "who was #1 in March" needs.
--
-- WHY RANK() and not ROW_NUMBER() or DENSE_RANK(): ties matter here (two
-- officers resolving the same count in the same month should show the same
-- rank), and RANK() -- unlike DENSE_RANK() -- also leaves a gap after a
-- tie (1,1,3 not 1,1,2), which correctly reflects that two people in 1st
-- means nobody is really in 2nd.
--
-- WHY the CTE first: window functions run after GROUP BY logically, but
-- you can't reference an aggregate alias inside the same SELECT's window
-- clause reliably across engines, so the monthly aggregation is computed
-- once in monthly_resolutions and the window function is applied to that
-- already-aggregated result.
-- ---------------------------------------------------------------------------
WITH monthly_resolutions AS (
    SELECT
        assigned_officer_id,
        DATE_TRUNC('month', closed_date)::date AS month,
        COUNT(*)                               AS cases_resolved
    FROM cases
    WHERE case_status = 'Closed'
    GROUP BY assigned_officer_id, DATE_TRUNC('month', closed_date)::date
)
SELECT
    o.officer_id,
    o.name  AS officer_name,
    mr.month,
    mr.cases_resolved,
    RANK() OVER (PARTITION BY mr.month ORDER BY mr.cases_resolved DESC) AS rank_in_month
FROM monthly_resolutions mr
JOIN officers o ON o.officer_id = mr.assigned_officer_id
ORDER BY mr.month, rank_in_month, officer_name;


-- ---------------------------------------------------------------------------
-- 2. Running monthly crime total
--
-- SUM(crime_count) OVER (ORDER BY month ROWS BETWEEN UNBOUNDED PRECEDING
-- AND CURRENT ROW) is a cumulative sum: "how many crimes has the city seen
-- so far, through this month."
--
-- WHY the explicit frame clause instead of relying on the default: with
-- only ORDER BY and no frame, Postgres defaults to RANGE UNBOUNDED
-- PRECEDING AND CURRENT ROW, which is the running total too *unless* two
-- rows tie on the ORDER BY key (here, month is unique per row anyway) --
-- but ROWS instead of the implicit RANGE is spelled out so the intent
-- ("sum every prior row, one at a time") is unambiguous to a future
-- reader regardless of what the ORDER BY column looks like.
-- ---------------------------------------------------------------------------
WITH monthly_counts AS (
    SELECT
        DATE_TRUNC('month', date_occurred)::date AS month,
        COUNT(*)                                 AS crime_count
    FROM crime_reports
    GROUP BY DATE_TRUNC('month', date_occurred)::date
)
SELECT
    month,
    crime_count,
    SUM(crime_count) OVER (
        ORDER BY month
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS running_total
FROM monthly_counts
ORDER BY month;


-- ---------------------------------------------------------------------------
-- 3. Month-over-month % change in crime rate per area
--
-- LAG(crime_count) OVER (PARTITION BY area ORDER BY month) reaches back one
-- row within the same area's timeline to get last month's count, which is
-- what a % change calculation needs and a self-join would otherwise be
-- required for.
--
-- WHY PARTITION BY area: without it, LAG() would pull the previous row in
-- the whole result set regardless of area, comparing e.g. Riverside's
-- January to Old Town's December -- meaningless. Partitioning resets the
-- window per area so each area's trend is computed against its own past.
--
-- WHY NULLIF(..., 0): guards the division against a divide-by-zero error
-- for any area that had zero reports the prior month (turns the result
-- into NULL -- "undefined change" -- instead of crashing the query).
-- ---------------------------------------------------------------------------
WITH monthly_area_counts AS (
    SELECT
        DATE_TRUNC('month', date_occurred)::date AS month,
        area,
        COUNT(*)                                 AS crime_count
    FROM crime_reports
    GROUP BY DATE_TRUNC('month', date_occurred)::date, area
)
SELECT
    area,
    month,
    crime_count,
    LAG(crime_count) OVER (PARTITION BY area ORDER BY month) AS prev_month_count,
    ROUND(
        100.0 * (crime_count - LAG(crime_count) OVER (PARTITION BY area ORDER BY month))
        / NULLIF(LAG(crime_count) OVER (PARTITION BY area ORDER BY month), 0)
    , 1) AS pct_change_vs_prev_month
FROM monthly_area_counts
ORDER BY area, month;
