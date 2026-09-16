-- 001_create_police_stations.sql
-- Police stations are the top-level organizational unit: every officer
-- belongs to one, and every crime report is filed at one.

CREATE TABLE police_stations (
    station_id       SERIAL PRIMARY KEY,
    name              VARCHAR(150) NOT NULL,
    jurisdiction_area VARCHAR(150) NOT NULL,
    contact_no        VARCHAR(20)  NOT NULL,
    CONSTRAINT uq_police_stations_name_area UNIQUE (name, jurisdiction_area)
);

-- Lookups by jurisdiction area (e.g. "which station covers this area?")
-- are common when routing new reports, so index it.
CREATE INDEX idx_police_stations_jurisdiction_area
    ON police_stations (jurisdiction_area);
