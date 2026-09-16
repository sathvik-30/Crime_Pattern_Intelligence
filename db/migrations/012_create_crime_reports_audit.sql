-- 012_create_crime_reports_audit.sql
-- Backing table for the audit trigger in db/sql_features/triggers.sql,
-- which logs every UPDATE on crime_reports.
--
-- old_value/new_value are stored as JSONB snapshots of the whole row
-- (via to_jsonb(OLD)/to_jsonb(NEW)) rather than one audit row per changed
-- column. That keeps the trigger function generic -- if crime_reports
-- gains or loses a column later, the trigger doesn't need to change -- and
-- JSONB lets you diff old vs new with ordinary Postgres JSON operators
-- when investigating a change.
--
-- report_id is intentionally NOT a foreign key: an audit log is a
-- historical record and must survive independently of the row it
-- describes (including across a dev reseed that truncates crime_reports
-- and restarts its identity sequence).

CREATE TABLE crime_reports_audit (
    audit_id    BIGSERIAL PRIMARY KEY,
    report_id   INT NOT NULL,
    old_value   JSONB NOT NULL,
    new_value   JSONB NOT NULL,
    changed_at  TIMESTAMP NOT NULL DEFAULT now(),
    changed_by  TEXT NOT NULL DEFAULT current_user
);

-- "Show me the audit history for this report" is the primary access
-- pattern for investigating a disputed change.
CREATE INDEX idx_crime_reports_audit_report_id ON crime_reports_audit (report_id);
