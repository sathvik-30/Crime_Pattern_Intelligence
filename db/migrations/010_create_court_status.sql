-- 010_create_court_status.sql
-- Tracks court proceedings for a case. A case can have multiple hearing
-- rows over time (adjournments, multiple hearing dates), so this is a
-- one-to-many relationship from cases to court_status.

CREATE TABLE court_status (
    court_id          SERIAL PRIMARY KEY,
    case_id           INT NOT NULL
        REFERENCES cases (case_id) ON DELETE CASCADE,
    hearing_date      DATE NOT NULL,
    verdict           VARCHAR(20)
        CHECK (verdict IS NULL OR verdict IN (
            'Pending', 'Guilty', 'Not Guilty', 'Acquitted', 'Dismissed', 'Settled'
        )),
    judge_name        VARCHAR(150) NOT NULL,
    next_hearing_date DATE,
    CONSTRAINT chk_court_status_next_hearing CHECK (next_hearing_date IS NULL OR next_hearing_date > hearing_date)
);

-- "Court calendar" / case-history views join on case_id.
CREATE INDEX idx_court_status_case_id ON court_status (case_id);

-- Docket/scheduling views filter on upcoming hearing dates.
CREATE INDEX idx_court_status_hearing_date ON court_status (hearing_date);
