-- 008_create_case_victims.sql
-- Junction table for the many-to-many relationship between cases and
-- victims (a case can involve multiple victims; a person could be a
-- victim in more than one case).

CREATE TABLE case_victims (
    case_id   INT NOT NULL
        REFERENCES cases (case_id) ON DELETE CASCADE,
    victim_id INT NOT NULL
        REFERENCES victims (victim_id) ON DELETE RESTRICT,
    PRIMARY KEY (case_id, victim_id)
);

-- The PK above already indexes case_id first; add the reverse index so
-- "all cases involving this victim" doesn't scan.
CREATE INDEX idx_case_victims_victim_id ON case_victims (victim_id);
