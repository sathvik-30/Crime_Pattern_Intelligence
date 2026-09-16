# Indexing Case Study: `crime_reports` filtered by area + date range

## The query

The single most common analytical query pattern in this system is "show me
crimes in this area, in this date window" -- it's the base of hotspot
detection, station workload reports, and the dashboard phase's map view:

```sql
SELECT report_id, crime_type, severity, date_occurred
FROM crime_reports
WHERE area = 'Riverside'
  AND date_occurred BETWEEN '2024-06-01' AND '2024-08-01';
```

`crime_reports` already had two single-column indexes from Phase 1
(`idx_crime_reports_area`, `idx_crime_reports_date_occurred`), so this
isn't a "no index at all" case study -- it's the more realistic question
of whether two single-column indexes are as good as one composite index
for a query that filters on both columns at once.

## Why the seeded dataset alone wasn't enough

The seeded demo dataset has 560 rows in `crime_reports`. At that size,
Postgres's planner is *correct* to prefer a sequential scan (or a trivial
bitmap scan) regardless of what indexes exist -- the whole table fits in a
handful of pages, so there's nothing for an index to save. Benchmarking
against 560 rows would have produced a "before vs after" difference too
small to be meaningful (sub-millisecond either way) and wouldn't reflect
how this schema behaves once it holds real production-scale data.

To get a genuine before/after comparison, I temporarily bulk-loaded
500,000 synthetic rows directly into `crime_reports` (spread across the
real areas, stations, and officers, with the same date range as the real
seed data), ran the benchmark, and then deleted every bulk-loaded row
afterward. The composite index created during the benchmark was kept --
that part is a real, permanent schema change (see
`db/migrations/013_add_crime_reports_area_date_index.sql`). The seeded
dataset itself (560 rows, and every pattern verified in Phase 2) was
restored to exactly its prior state.

## Before: two single-column indexes, no composite

```
Bitmap Heap Scan on crime_reports  (cost=557.21..2902.94 rows=815 width=29) (actual time=2.176..3.501 rows=816.00 loops=1)
  Recheck Cond: ((date_occurred >= '2024-06-01 00:00:00'::timestamp without time zone) AND (date_occurred <= '2024-08-01 00:00:00'::timestamp without time zone) AND ((area)::text = 'Riverside'::text))
  Heap Blocks: exact=339
  Buffers: shared hit=386
  ->  BitmapAnd  (cost=557.21..557.21 rows=815 width=0) (actual time=2.119..2.120 rows=0.00 loops=1)
        Buffers: shared hit=47
        ->  Bitmap Index Scan on idx_crime_reports_date_occurred  (cost=0.00..195.47 rows=12305 width=0) (actual time=0.418..0.418 rows=12461.00 loops=1)
              Index Cond: ((date_occurred >= '2024-06-01 00:00:00'::timestamp without time zone) AND (date_occurred <= '2024-08-01 00:00:00'::timestamp without time zone))
              Index Searches: 1
              Buffers: shared hit=18
        ->  Bitmap Index Scan on idx_crime_reports_area  (cost=0.00..361.08 rows=33154 width=0) (actual time=1.608..1.608 rows=33456.00 loops=1)
              Index Cond: ((area)::text = 'Riverside'::text)
              Index Searches: 1
              Buffers: shared hit=29
Planning Time: 5.030 ms
Execution Time: 3.583 ms
```

With only single-column indexes, the planner has to work in two passes:
scan `idx_crime_reports_date_occurred` for every row in the date window
(**12,461 candidate rows**), separately scan `idx_crime_reports_area` for
every Riverside row (**33,456 candidate rows**), and then `BitmapAnd` the
two bitmaps together in memory before it even touches the heap. Both
candidate sets are far larger than the 816 rows that actually match both
conditions -- the index can't tell Postgres "these two conditions
together" only "this one condition, ask me again about the other one
separately."

## After: composite index on `(area, date_occurred)`

```sql
CREATE INDEX idx_crime_reports_area_date_occurred
    ON crime_reports (area, date_occurred);
```

```
Bitmap Heap Scan on crime_reports  (cost=14.57..2316.82 rows=796 width=29) (actual time=0.207..1.608 rows=816.00 loops=1)
  Recheck Cond: (((area)::text = 'Riverside'::text) AND (date_occurred >= '2024-06-01 00:00:00'::timestamp without time zone) AND (date_occurred <= '2024-08-01 00:00:00'::timestamp without time zone))
  Heap Blocks: exact=339
  Buffers: shared hit=339 read=4
  ->  Bitmap Index Scan on idx_crime_reports_area_date_occurred  (cost=0.00..14.37 rows=796 width=0) (actual time=0.147..0.147 rows=816.00 loops=1)
        Index Cond: (((area)::text = 'Riverside'::text) AND (date_occurred >= '2024-06-01 00:00:00'::timestamp without time zone) AND (date_occurred <= '2024-08-01 00:00:00'::timestamp without time zone))
        Index Searches: 1
        Buffers: shared read=4
Planning Time: 4.289 ms
Execution Time: 1.682 ms
```

With `(area, date_occurred)` as a composite key, a single index scan can
jump straight to the `'Riverside'` section of the index and then walk a
contiguous range of dates within it. The index scan itself returns
**exactly 816 rows** -- the true match count, with zero wasted candidates
-- instead of two oversized bitmaps that then need to be intersected.

## Before vs. after

| Metric | Before (2 single-column indexes) | After (composite index) | Change |
|---|---|---|---|
| Planner cost estimate | 557.21 .. 2902.94 | 14.57 .. 2316.82 | ~62% lower startup cost |
| Bitmap Index Scan candidate rows | 12,461 + 33,456 = 45,917 (combined) | 816 (exact) | ~56x fewer candidate rows |
| Index scan step count | 2 scans + 1 BitmapAnd merge | 1 scan | halved the index-side work |
| Execution time | 3.583 ms | 1.682 ms | **~53% faster** |

At 500,000 rows the win is already clear-cut and directly attributable to
the composite index doing in one pass what previously took two passes
plus a merge step. The gap between the two plans widens as the table
grows further, since the single-column approach's candidate-set sizes
(and therefore the cost of intersecting them) scale with table size,
while the composite index's cost stays close to the true match count
regardless of table size.

## Column order: why `(area, date_occurred)` and not the reverse

`area` is an equality predicate (`= 'Riverside'`) and `date_occurred` is a
range predicate (`BETWEEN ...`). Putting the equality column first lets
the btree narrow to one contiguous slice of the index (all of
Riverside's entries) and then range-scan the dates *within* that slice.
Reversing the order would force a scan across a much wider portion of the
index (every date in the range, across all 15 areas) before area could be
applied as a filter -- the equality-before-range rule of thumb for
composite btree indexes.

## Why the single-column indexes weren't dropped

`idx_crime_reports_area` and `idx_crime_reports_date_occurred` still earn
their keep for queries that filter on *only* one of the two columns (e.g.
"all crimes in Riverside, regardless of date" or "all crimes this month,
regardless of area") -- the composite index can still serve the
area-only case (it's a leftmost prefix of the index) but not the
date-only case efficiently, since date_occurred is the second column.
Both single-column indexes stay in the schema; the composite index is
additive.
