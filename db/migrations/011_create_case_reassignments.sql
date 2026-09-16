-- 011_create_case_reassignments.sql
-- Supports Phase 3's recursive CTE (db/sql_features/ctes.sql), which walks
-- a case's escalation/reassignment history from its initial assignment to
-- its current officer.
--
-- Each row is one step in a case's assignment history. Rather than relying
-- on ORDER BY reassigned_at to reconstruct the sequence (fragile if two
-- reassignments land in the same second, and not "recursive" in spirit),
-- previous_reassignment_id self-references the prior step, forming an
-- explicit linked list per case. The first step in a case's chain has
-- previous_reassignment_id = NULL.

CREATE TABLE case_reassignments (
    case_reassignment_id     SERIAL PRIMARY KEY,
    case_id                   INT NOT NULL
        REFERENCES cases (case_id) ON DELETE CASCADE,
    previous_reassignment_id  INT
        REFERENCES case_reassignments (case_reassignment_id) ON DELETE CASCADE,
    officer_id                INT NOT NULL
        REFERENCES officers (officer_id) ON DELETE RESTRICT,
    reassigned_at             TIMESTAMP NOT NULL DEFAULT now(),
    reason                    VARCHAR(50) NOT NULL
        CHECK (reason IN (
            'Initial Assignment', 'Escalation', 'Workload Rebalance',
            'Officer Transfer', 'Specialist Handoff'
        ))
);

-- The recursive CTE always starts from "all cases" or "one case", then
-- walks forward, so both directions need an index: case_id for the anchor
-- lookup, previous_reassignment_id for the recursive join's ON clause.
CREATE INDEX idx_case_reassignments_case_id ON case_reassignments (case_id);
CREATE INDEX idx_case_reassignments_previous_reassignment_id
    ON case_reassignments (previous_reassignment_id);
