-- 006_create_cases.sql
-- A case is the investigative record opened against a crime report.
-- One report opens at most one case (a report that turns out to be
-- unfounded may never get one), enforced via the UNIQUE on report_id.

CREATE TABLE cases (
    case_id              SERIAL PRIMARY KEY,
    report_id            INT NOT NULL UNIQUE
        REFERENCES crime_reports (report_id) ON DELETE RESTRICT,
    assigned_officer_id  INT NOT NULL
        REFERENCES officers (officer_id) ON DELETE RESTRICT,
    opened_date          DATE NOT NULL,
    closed_date          DATE,
    case_status          VARCHAR(20) NOT NULL DEFAULT 'Open'
        CHECK (case_status IN ('Open', 'Under Investigation', 'Closed', 'Cold Case')),
    CONSTRAINT chk_cases_dates CHECK (closed_date IS NULL OR closed_date >= opened_date)
);

-- Case-load dashboards filter/join on the assigned officer.
CREATE INDEX idx_cases_assigned_officer_id ON cases (assigned_officer_id);

-- "Open cases" / status-board views filter on case_status.
CREATE INDEX idx_cases_case_status ON cases (case_status);
