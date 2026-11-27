-- trending_moves.sql — day-over-day movement of the trending ranking.
--
-- Consumes trending_repos (the daily github.com/trending snapshot) and
-- computes, per repo per day: yesterday's rank, how far it climbed, and the
-- movement kind.  Repos in yesterday's list but not today's get a
-- 'dropped_off' row, so "what changed last night" is a single query.
--
-- movement:
--   entered     first time ever on the list
--   re-entered  back after a gap (was seen before, but not yesterday)
--   up / down   moved vs yesterday
--   flat        same rank as yesterday
--   dropped_off was on the list yesterday, not today (rank is NULL)

MODEL (
  name my_db.trending_moves,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (snapshot_date, full_name)
  ),
  audits [
    not_null(columns := (snapshot_date, full_name, movement))
  ]
);

WITH days AS (
  SELECT DISTINCT CAST(snapshot_date AS DATE) AS d
  FROM my_db.trending_repos
),
pairs AS (
  SELECT
    d AS snapshot_date,
    LAG(d) OVER (ORDER BY d) AS prev_date
  FROM days
),
ranked AS (
  SELECT
    CAST(t.snapshot_date AS DATE) AS snapshot_date,
    t.full_name,
    t.rank,
    t.total_stars,
    t.stars_today,
    p.prev_date,
    LAG(t.rank) OVER (
      PARTITION BY t.full_name ORDER BY CAST(t.snapshot_date AS DATE)
    ) AS prev_rank
  FROM my_db.trending_repos t
  JOIN pairs p ON p.snapshot_date = CAST(t.snapshot_date AS DATE)
),
moves AS (
  SELECT
    r.snapshot_date,
    r.full_name,
    r.rank,
    r.prev_rank,
    r.prev_rank - r.rank AS rank_delta,
    CASE
      WHEN r.prev_rank IS NULL THEN 'entered'
      WHEN NOT EXISTS (
        SELECT 1 FROM my_db.trending_repos t2
        WHERE t2.full_name = r.full_name
          AND CAST(t2.snapshot_date AS DATE) = r.prev_date
      ) THEN 're-entered'
      WHEN r.rank < r.prev_rank THEN 'up'
      WHEN r.rank > r.prev_rank THEN 'down'
      ELSE 'flat'
    END AS movement,
    r.total_stars,
    r.stars_today
  FROM ranked r
),
dropped AS (
  SELECT
    p.snapshot_date,
    t.full_name,
    CAST(NULL AS BIGINT) AS rank,
    t.rank AS prev_rank,
    CAST(NULL AS BIGINT) AS rank_delta,
    'dropped_off' AS movement,
    t.total_stars,
    CAST(NULL AS BIGINT) AS stars_today
  FROM pairs p
  JOIN my_db.trending_repos t ON CAST(t.snapshot_date AS DATE) = p.prev_date
  WHERE p.prev_date IS NOT NULL
    AND NOT EXISTS (
      SELECT 1 FROM my_db.trending_repos t2
      WHERE t2.full_name = t.full_name
        AND CAST(t2.snapshot_date AS DATE) = p.snapshot_date
    )
)
SELECT * FROM moves
UNION ALL
SELECT * FROM dropped
