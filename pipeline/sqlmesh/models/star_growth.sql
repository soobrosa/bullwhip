-- star_growth.sql — daily star count growth tracking.
--
-- Each run appends a daily snapshot of star counts (from star_snapshots).
-- This model computes the growth rate over time: daily delta, weekly delta,
-- and 7-day moving average.

MODEL (
  name my_db.star_growth,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (full_name, snapshot_date)
  ),
  audits [
    not_null(columns := (full_name, snapshot_date, stars))
  ]
);

WITH snapshots AS (
  SELECT
    full_name,
    CAST(snapshot_date AS DATE) AS snapshot_date,
    stars,
    LAG(stars) OVER (
      PARTITION BY full_name
      ORDER BY CAST(snapshot_date AS DATE)
    ) AS prev_stars,
    LAG(stars) OVER (
      PARTITION BY full_name
      ORDER BY CAST(snapshot_date AS DATE)
      ROWS BETWEEN 7 PRECEDING AND 7 PRECEDING
    ) AS week_ago_stars
  FROM my_db.star_snapshots
)
SELECT
  full_name,
  snapshot_date,
  stars,
  stars - COALESCE(prev_stars, stars) AS daily_delta,
  CASE
    WHEN COALESCE(week_ago_stars, 0) > 0
    THEN ROUND((stars - week_ago_stars) * 100.0 / week_ago_stars, 2)
    ELSE 0
  END AS weekly_growth_pct
FROM snapshots
