-- 009_create_evidence.sql
-- Physical/digital evidence collected for a case, with a chain-of-
-- custody officer for accountability.

CREATE TABLE evidence (
    evidence_id             SERIAL PRIMARY KEY,
    case_id                 INT NOT NULL
        REFERENCES cases (case_id) ON DELETE CASCADE,
    type                    VARCHAR(50) NOT NULL
        CHECK (type IN (
            'Physical', 'Digital', 'Document', 'Biological',
            'Photographic', 'Testimonial', 'Other'
        )),
    description             TEXT NOT NULL,
    collected_date          DATE NOT NULL
        CHECK (collected_date <= CURRENT_DATE),
    storage_location        VARCHAR(150) NOT NULL,
    chain_of_custody_officer INT NOT NULL
        REFERENCES officers (officer_id) ON DELETE RESTRICT
);

-- "All evidence for this case" is the primary access pattern (case file view).
CREATE INDEX idx_evidence_case_id ON evidence (case_id);

-- Custody audits look up everything a given officer has handled.
CREATE INDEX idx_evidence_chain_of_custody_officer ON evidence (chain_of_custody_officer);
