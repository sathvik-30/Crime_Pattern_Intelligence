-- 002_create_officers.sql
-- Officers are staffed at a station; they later appear as reporting
-- officers on crime reports, assigned officers on cases, and custodians
-- of evidence.

CREATE TABLE officers (
    officer_id    SERIAL PRIMARY KEY,
    name          VARCHAR(150) NOT NULL,
    rank          VARCHAR(50)  NOT NULL
        CHECK (rank IN (
            'Constable', 'Head Constable', 'Assistant Sub-Inspector',
            'Sub-Inspector', 'Inspector', 'Deputy Superintendent',
            'Superintendent', 'Deputy Inspector General',
            'Inspector General', 'Director General'
        )),
    station_id    INT NOT NULL
        REFERENCES police_stations (station_id) ON DELETE RESTRICT,
    badge_no      VARCHAR(20) NOT NULL UNIQUE,
    joining_date  DATE NOT NULL
        CHECK (joining_date <= CURRENT_DATE)
);

-- Every officer roster screen and case-load report filters/joins on
-- the officer's station.
CREATE INDEX idx_officers_station_id ON officers (station_id);
