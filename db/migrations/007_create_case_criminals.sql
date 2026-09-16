-- 007_create_case_criminals.sql
-- Junction table for the many-to-many relationship between cases and
-- criminals (a case can name multiple suspects; a criminal can be
-- named in multiple cases).

CREATE TABLE case_criminals (
    case_id     INT NOT NULL
        REFERENCES cases (case_id) ON DELETE CASCADE,
    criminal_id INT NOT NULL
        REFERENCES criminals (criminal_id) ON DELETE RESTRICT,
    PRIMARY KEY (case_id, criminal_id)
);

-- The PK above already indexes case_id first; add the reverse index so
-- "all cases involving this criminal" (recidivism analysis) doesn't scan.
CREATE INDEX idx_case_criminals_criminal_id ON case_criminals (criminal_id);
