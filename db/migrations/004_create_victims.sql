-- 004_create_victims.sql
-- Victims are linked to cases via the case_victims junction table
-- (a case can have multiple victims, and a person could be a victim
-- across multiple cases).

CREATE TABLE victims (
    victim_id  SERIAL PRIMARY KEY,
    name       VARCHAR(150) NOT NULL,
    age        INT
        CHECK (age IS NULL OR (age >= 0 AND age <= 130)),
    gender     VARCHAR(1) NOT NULL
        CHECK (gender IN ('M', 'F', 'O')),
    contact_no VARCHAR(20),
    address    TEXT
);
