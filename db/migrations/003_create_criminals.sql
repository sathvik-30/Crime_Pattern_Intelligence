-- 003_create_criminals.sql
-- Criminals are linked to cases via the case_criminals junction table
-- (a person can be tied to more than one case, and a case can involve
-- more than one criminal).

CREATE TABLE criminals (
    criminal_id             SERIAL PRIMARY KEY,
    name                    VARCHAR(150) NOT NULL,
    dob                     DATE
        CHECK (dob IS NULL OR dob <= CURRENT_DATE),
    gender                  VARCHAR(1) NOT NULL
        CHECK (gender IN ('M', 'F', 'O')),
    address                 TEXT,
    prior_convictions_count INT NOT NULL DEFAULT 0
        CHECK (prior_convictions_count >= 0)
);

-- Repeat-offender analytics (Phase 3+) will filter on conviction count.
CREATE INDEX idx_criminals_prior_convictions_count
    ON criminals (prior_convictions_count);
