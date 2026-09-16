-- ctes.sql
-- Two CTE-based queries: a multi-step (non-recursive) CTE that builds up
-- a hotspot ranking, and a recursive CTE that walks case_reassignments
-- (see db/migrations/011_create_case_reassignments.sql) to reconstruct
-- each case's escalation history.

-- ---------------------------------------------------------------------------
-- 1. Multi-step CTE: aggregate by area/month, then rank areas as hotspots
--
-- WHY three chained CTEs instead of one query with nested subqueries:
-- each step names an intermediate result (area_month_counts ->
-- area_totals -> ranked_areas), so the query reads top-to-bottom the same
-- way you'd explain the logic out loud: "first bucket by month, then total
-- per area, then rank those totals." A deeply nested subquery version
-- would compute the identical result but hide that narrative.
--
-- WHY rank on total_crimes (not avg_monthly_crimes): an area with a short
-- but severe recent spike should still outrank a chronically low-but-
-- steady area for "hotspot" purposes, and summing preserves that; the
-- average is kept alongside as context, not as the ranking key.
-- ---------------------------------------------------------------------------
WITH area_month_counts AS (
    SELECT
        DATE_TRUNC('month', date_occurred)::date AS month,
        area,
        COUNT(*)                                 AS crime_count
    FROM crime_reports
    GROUP BY DATE_TRUNC('month', date_occurred)::date, area
),
area_totals AS (
    SELECT
        area,
        SUM(crime_count)                    AS total_crimes,
        ROUND(AVG(crime_count), 1)          AS avg_monthly_crimes,
        COUNT(*)                            AS months_with_activity
    FROM area_month_counts
    GROUP BY area
),
ranked_areas AS (
    SELECT
        area,
        total_crimes,
        avg_monthly_crimes,
        months_with_activity,
        RANK() OVER (ORDER BY total_crimes DESC) AS hotspot_rank
    FROM area_totals
)
SELECT *
FROM ranked_areas
ORDER BY hotspot_rank;


-- ---------------------------------------------------------------------------
-- 2. Recursive CTE: case escalation/reassignment history
--
-- case_reassignments forms a linked list per case (each row points at the
-- step before it via previous_reassignment_id, NULL for the first step).
-- A recursive CTE is the natural tool for walking a linked list of
-- unknown length in SQL, since a fixed number of self-joins can't handle
-- a case that was reassigned 2 times *and* one that was reassigned 5
-- times in the same query.
--
-- WHY the anchor is "previous_reassignment_id IS NULL": that's the base
-- case of the recursion -- every case's history starts at exactly one row
-- with no predecessor, so this seeds one row per case with a history.
--
-- WHY the recursive term joins "nxt.previous_reassignment_id =
-- prev.case_reassignment_id": this is the walk-forward step -- for every
-- row already reached, find the row (if any) that names it as its
-- predecessor, and add it to the result. Recursion stops naturally when
-- no row points at the most recently added step.
--
-- escalation_path concatenates officer_id at each step into one string so
-- the full history of a reassigned case reads as a single row instead of
-- requiring the caller to re-assemble N rows in order.
-- ---------------------------------------------------------------------------
WITH RECURSIVE reassignment_chain AS (
    -- Anchor: the first (initial) assignment of every case that has history.
    SELECT
        cre.case_reassignment_id,
        cre.case_id,
        cre.officer_id,
        cre.reassigned_at,
        cre.reason,
        1                            AS step_number,
        cre.officer_id::text         AS escalation_path
    FROM case_reassignments cre
    WHERE cre.previous_reassignment_id IS NULL

    UNION ALL

    -- Recursive step: the row (if any) whose previous_reassignment_id
    -- points at a step already in the result.
    SELECT
        nxt.case_reassignment_id,
        nxt.case_id,
        nxt.officer_id,
        nxt.reassigned_at,
        nxt.reason,
        prev.step_number + 1,
        prev.escalation_path || ' -> ' || nxt.officer_id::text
    FROM case_reassignments nxt
    JOIN reassignment_chain prev ON nxt.previous_reassignment_id = prev.case_reassignment_id
)
SELECT
    case_id,
    step_number,
    officer_id,
    reason,
    reassigned_at,
    escalation_path
FROM reassignment_chain
ORDER BY case_id, step_number;


-- ---------------------------------------------------------------------------
-- 2b. Same recursive CTE, rolled up to one row per case
--
-- Reuses the identical recursive query, then aggregates it, to answer
-- "which cases were escalated the most" -- the practical question the
-- raw step-by-step listing above supports but doesn't directly answer.
-- ---------------------------------------------------------------------------
WITH RECURSIVE reassignment_chain AS (
    SELECT
        cre.case_reassignment_id,
        cre.case_id,
        cre.officer_id,
        cre.reassigned_at,
        1                     AS step_number,
        cre.officer_id::text  AS escalation_path
    FROM case_reassignments cre
    WHERE cre.previous_reassignment_id IS NULL

    UNION ALL

    SELECT
        nxt.case_reassignment_id,
        nxt.case_id,
        nxt.officer_id,
        nxt.reassigned_at,
        prev.step_number + 1,
        prev.escalation_path || ' -> ' || nxt.officer_id::text
    FROM case_reassignments nxt
    JOIN reassignment_chain prev ON nxt.previous_reassignment_id = prev.case_reassignment_id
)
SELECT
    case_id,
    MAX(step_number)                                        AS total_reassignments,
    (ARRAY_AGG(escalation_path ORDER BY step_number DESC))[1] AS final_escalation_path
FROM reassignment_chain
GROUP BY case_id
ORDER BY total_reassignments DESC, case_id;
