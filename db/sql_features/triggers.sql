-- triggers.sql
-- Two triggers: one enforces a business rule (a final verdict closes its
-- case), the other is a generic audit log. The tables each trigger writes
-- to (crime_reports_audit) already exist via db/migrations/012; this file
-- only defines behavior (functions + triggers), keeping "what tables
-- exist" and "what fires on them" in separate, clearly-scoped files.

-- ---------------------------------------------------------------------------
-- 1. Auto-close a case when its court proceedings reach a final verdict
--
-- WHY a trigger instead of relying on application code to also update
-- cases.case_status: a court_status row can be inserted or updated by any
-- number of code paths (sp_close_case, a future admin UI, a bulk import).
-- A trigger makes "verdict implies closed" a property of the data itself,
-- so it can't be forgotten by one of those callers.
--
-- WHY the WHEN clause filters out 'Pending' and NULL: 'Pending' is itself
-- a legal value for verdict in this schema (an open hearing with no
-- outcome yet) -- only a *final* outcome (Guilty/Not Guilty/Acquitted/
-- Dismissed/Settled) should close the case. Filtering in the trigger's
-- WHEN clause (evaluated before the function is even invoked) is cheaper
-- than checking inside the function body for every row.
--
-- WHY AFTER INSERT OR UPDATE OF verdict: a verdict can arrive either as a
-- brand-new final-verdict row (sp_close_case inserts one directly) or as
-- an existing 'Pending' row being updated once a hearing concludes -- both
-- need to trigger the same close-out behavior.
--
-- WHY the guard "case_status <> 'Closed'" inside the function: makes the
-- UPDATE a no-op if the case is already closed (e.g. a second hearing row
-- also carries a final verdict), avoiding a redundant write and, more
-- importantly, avoiding overwriting an earlier closed_date with a later
-- one.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_auto_close_case_on_verdict()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE cases
    SET case_status = 'Closed',
        closed_date = COALESCE(closed_date, NEW.hearing_date, CURRENT_DATE)
    WHERE case_id = NEW.case_id
      AND case_status <> 'Closed';

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_auto_close_case_on_verdict ON court_status;

CREATE TRIGGER trg_auto_close_case_on_verdict
AFTER INSERT OR UPDATE OF verdict ON court_status
FOR EACH ROW
WHEN (NEW.verdict IS NOT NULL AND NEW.verdict <> 'Pending')
EXECUTE FUNCTION fn_auto_close_case_on_verdict();


-- ---------------------------------------------------------------------------
-- 2. Audit every UPDATE on crime_reports
--
-- WHY AFTER UPDATE (not BEFORE): the trigger only observes and records the
-- change, it never needs to modify the row being written, so there's no
-- reason to run it before the write completes.
--
-- WHY to_jsonb(OLD)/to_jsonb(NEW) for the whole row instead of one audit
-- row per changed column: it's schema-generic (a later ALTER TABLE on
-- crime_reports needs no matching change here) and keeps "what changed"
-- easy to compute later with a single JSONB diff if ever needed, rather
-- than needing N audit rows reassembled per UPDATE statement.
--
-- WHY the WHEN clause (OLD.* IS DISTINCT FROM NEW.*): an UPDATE statement
-- can touch a row without actually changing any of its values (e.g.
-- "SET status = status" as part of a broader batch update); IS DISTINCT
-- FROM treats NULLs correctly (unlike <>) and skips logging when nothing
-- really changed, keeping the audit trail meaningful.
--
-- WHY changed_by defaults to current_user: the project has no
-- application-level authentication layer yet, so the Postgres role
-- executing the statement is the only identity available. A future
-- app tier could improve on this by SET-ing a session variable (e.g.
-- `SET LOCAL app.current_user_id = ...`) and reading it here instead.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_audit_crime_reports()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO crime_reports_audit (report_id, old_value, new_value, changed_by)
    VALUES (OLD.report_id, to_jsonb(OLD), to_jsonb(NEW), current_user);

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_crime_reports ON crime_reports;

CREATE TRIGGER trg_audit_crime_reports
AFTER UPDATE ON crime_reports
FOR EACH ROW
WHEN (OLD.* IS DISTINCT FROM NEW.*)
EXECUTE FUNCTION fn_audit_crime_reports();
