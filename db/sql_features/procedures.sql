-- procedures.sql
-- Two stored procedures encapsulating multi-statement business operations
-- that would otherwise require an application layer to get right (and
-- keep right) every time: assigning a case respects a workload cap, and
-- closing a case always leaves a court record behind it.

-- ---------------------------------------------------------------------------
-- sp_assign_case(p_report_id, p_officer_id, p_reason)
--
-- Assigns a crime report to an officer -- creating its case if none exists
-- yet, or reassigning an existing one -- while enforcing a simple workload
-- cap and always leaving a case_reassignments audit trail behind.
--
-- WHY a PROCEDURE (not a FUNCTION): this does multiple writes (cases,
-- case_reassignments) as one unit of work with no meaningful single return
-- value; PROCEDUREs are Postgres's construct for "run these statements
-- together," called with CALL rather than embedded in a SELECT.
--
-- WHY check the open-case count and RAISE EXCEPTION before writing
-- anything: this is the workload-cap business rule the task calls for --
-- an officer already carrying v_open_case_threshold or more open cases
-- should not be handed another one. Checking first (rather than writing
-- then validating) means a rejected assignment leaves no partial state.
--
-- WHY p_reason defaults to 'Workload Rebalance' but is ignored for a
-- brand-new case: a case's first-ever assignment is always logged as
-- 'Initial Assignment' regardless of what the caller passes, because that
-- CHECK-constrained value describes a fact (this is step 1), not a
-- caller's opinion; p_reason only matters when there's already a prior
-- step to reassign away from.
--
-- WHY look up the latest case_reassignments row by reassigned_at instead
-- of tracking "the current head" in a separate column: with only tens of
-- reassignments per case at most, the ORDER BY ... LIMIT 1 lookup is cheap
-- and keeps case_reassignments the single source of truth for history,
-- rather than duplicating "current officer" state across two tables.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE sp_assign_case(
    p_report_id INT,
    p_officer_id INT,
    p_reason VARCHAR(50) DEFAULT 'Workload Rebalance'
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_case_id                 INT;
    v_open_case_count         INT;
    v_last_reassignment_id    INT;
    v_open_case_threshold CONSTANT INT := 15;
BEGIN
    SELECT COUNT(*) INTO v_open_case_count
    FROM cases
    WHERE assigned_officer_id = p_officer_id
      AND case_status <> 'Closed';

    IF v_open_case_count >= v_open_case_threshold THEN
        RAISE EXCEPTION
            'Officer % already has % open case(s) (threshold %); cannot assign report %',
            p_officer_id, v_open_case_count, v_open_case_threshold, p_report_id;
    END IF;

    SELECT case_id INTO v_case_id FROM cases WHERE report_id = p_report_id;

    IF v_case_id IS NULL THEN
        INSERT INTO cases (report_id, assigned_officer_id, opened_date, case_status)
        VALUES (p_report_id, p_officer_id, CURRENT_DATE, 'Open')
        RETURNING case_id INTO v_case_id;

        INSERT INTO case_reassignments (case_id, previous_reassignment_id, officer_id, reason)
        VALUES (v_case_id, NULL, p_officer_id, 'Initial Assignment');
    ELSE
        UPDATE cases SET assigned_officer_id = p_officer_id WHERE case_id = v_case_id;

        SELECT case_reassignment_id INTO v_last_reassignment_id
        FROM case_reassignments
        WHERE case_id = v_case_id
        ORDER BY reassigned_at DESC
        LIMIT 1;

        INSERT INTO case_reassignments (case_id, previous_reassignment_id, officer_id, reason)
        VALUES (v_case_id, v_last_reassignment_id, p_officer_id, p_reason);
    END IF;
END;
$$;


-- ---------------------------------------------------------------------------
-- sp_close_case(p_case_id, p_verdict, p_judge_name)
--
-- Records a final court outcome and closes the case in one step.
--
-- WHY validate p_verdict against the *final* outcomes only (excluding
-- 'Pending') here, even though court_status already has a CHECK
-- constraint covering all six legal values: the CHECK constraint enforces
-- "is this a legal value at all"; this procedure additionally enforces
-- "is this an appropriate value for *closing* a case" -- 'Pending' would
-- pass the column CHECK but makes no sense as the reason a case is being
-- closed, so it's rejected with a clearer, purpose-specific error message.
--
-- WHY p_judge_name has a default instead of matching the task's 2-argument
-- description literally: court_status.judge_name is NOT NULL, so some
-- value is required on every insert; a third parameter with a default
-- preserves the simple sp_close_case(case_id, verdict) call shape for the
-- common case while still allowing a real judge's name to be supplied.
--
-- WHY the explicit UPDATE at the end even though inserting a final-verdict
-- row into court_status already fires trg_auto_close_case_on_verdict and
-- closes the case: this makes sp_close_case correct on its own even if
-- that trigger is ever disabled or dropped, at the cost of one redundant
-- (and, thanks to the trigger's own "case_status <> 'Closed'" guard,
-- effectively no-op) UPDATE in the common case. Demonstrates the
-- trigger/procedure interaction deliberately rather than by accident.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE sp_close_case(
    p_case_id INT,
    p_verdict VARCHAR(20),
    p_judge_name VARCHAR(150) DEFAULT 'Presiding Judge'
)
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_verdict NOT IN ('Guilty', 'Not Guilty', 'Acquitted', 'Dismissed', 'Settled') THEN
        RAISE EXCEPTION
            'sp_close_case requires a final verdict (Guilty/Not Guilty/Acquitted/Dismissed/Settled), got: %',
            p_verdict;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM cases WHERE case_id = p_case_id) THEN
        RAISE EXCEPTION 'No such case: %', p_case_id;
    END IF;

    INSERT INTO court_status (case_id, hearing_date, verdict, judge_name)
    VALUES (p_case_id, CURRENT_DATE, p_verdict, p_judge_name);

    UPDATE cases
    SET case_status = 'Closed',
        closed_date = COALESCE(closed_date, CURRENT_DATE)
    WHERE case_id = p_case_id
      AND case_status <> 'Closed';
END;
$$;
