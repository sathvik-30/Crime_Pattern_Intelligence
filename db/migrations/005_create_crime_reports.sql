-- 005_create_crime_reports.sql
-- The central fact table: one row per crime reported to a station.
-- Cases, evidence, and court proceedings all trace back to a report.

CREATE TABLE crime_reports (
    report_id           SERIAL PRIMARY KEY,
    crime_type          VARCHAR(100) NOT NULL,
    date_reported        TIMESTAMP NOT NULL,
    date_occurred         TIMESTAMP NOT NULL,
    location_lat         NUMERIC(9, 6)
        CHECK (location_lat IS NULL OR (location_lat BETWEEN -90 AND 90)),
    location_lng         NUMERIC(9, 6)
        CHECK (location_lng IS NULL OR (location_lng BETWEEN -180 AND 180)),
    area                 VARCHAR(150) NOT NULL,
    station_id            INT NOT NULL
        REFERENCES police_stations (station_id) ON DELETE RESTRICT,
    reporting_officer_id  INT NOT NULL
        REFERENCES officers (officer_id) ON DELETE RESTRICT,
    severity              VARCHAR(10) NOT NULL
        CHECK (severity IN ('Low', 'Medium', 'High', 'Critical')),
    status                VARCHAR(20) NOT NULL DEFAULT 'Reported'
        CHECK (status IN ('Reported', 'Verified', 'Under Investigation', 'Closed', 'Unfounded')),
    CONSTRAINT chk_crime_reports_dates CHECK (date_reported >= date_occurred)
);

-- Time-range queries ("crimes that occurred between X and Y") are core
-- to the pattern-analysis phases coming later.
CREATE INDEX idx_crime_reports_date_occurred ON crime_reports (date_occurred);

-- Hotspot/heatmap analysis groups crimes by area.
CREATE INDEX idx_crime_reports_area ON crime_reports (area);

-- Per-station dashboards and workload reports join/filter on station_id.
CREATE INDEX idx_crime_reports_station_id ON crime_reports (station_id);

-- "Reports filed by officer X" lookups join/filter on the reporting officer.
CREATE INDEX idx_crime_reports_reporting_officer_id ON crime_reports (reporting_officer_id);

-- Crime-type breakdowns (another common pattern-analysis dimension).
CREATE INDEX idx_crime_reports_crime_type ON crime_reports (crime_type);
