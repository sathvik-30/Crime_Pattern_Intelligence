-- 013_add_crime_reports_area_date_index.sql
-- See docs/indexing_case_study.md for the full before/after benchmark.
--
-- crime_reports already has separate single-column indexes on area and on
-- date_occurred (migration 005), so a query filtering on both can already
-- use them via a BitmapAnd of the two. A composite index lets the planner
-- satisfy the same predicate with one direct index scan instead of
-- building and intersecting two bitmaps, which matters once the table is
-- large enough for that intersection step to show up in the timing.
--
-- WHY the column order is (area, date_occurred) and not the reverse:
-- area is the equality predicate in the target query pattern
-- ("crimes in this area, in this date range") and date_occurred is a
-- range predicate. A btree index is most useful when the equality
-- column(s) come first -- Postgres can jump straight to the "Riverside"
-- section of the index and then scan a contiguous range of dates within
-- it, rather than the reverse (jump to a date, then filter by area within
-- a much wider slice of the index).
CREATE INDEX idx_crime_reports_area_date_occurred
    ON crime_reports (area, date_occurred);
