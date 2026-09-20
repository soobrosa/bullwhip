-- github_health.sql — repo health score model.
--
-- Joins repo metadata with contributors and releases to compute a
-- health snapshot: last commit, releases, open issues, bus factor.
--
-- Bus factor: the minimum number of contributors whose departure would
-- stall the project.  We approximate it as the number of contributors
-- needed to cover 50% of total contributions (a low bus factor = risky).

MODEL (
  name my_db.github_health,
  kind FULL,
  audits [
    not_null(columns := (full_name)),
    unique_values(columns := (full_name))
  ]
);

WITH contrib_totals AS (
  SELECT
    full_name,
    COUNT(*) AS contributor_count,
    SUM(contributions) AS total_contributions
  FROM my_db.contributors
  GROUP BY full_name
),
contrib_running AS (
  SELECT
    c.full_name,
    c.contributions,
    SUM(c.contributions) OVER (
      PARTITION BY c.full_name
      ORDER BY c.contributions DESC
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cum_contrib,
    t.total_contributions
  FROM my_db.contributors c
  JOIN contrib_totals t ON t.full_name = c.full_name
),
bus AS (
  SELECT full_name, MIN(rn) AS bus_factor
  FROM (
    SELECT
      full_name,
      ROW_NUMBER() OVER (
        PARTITION BY full_name ORDER BY contributions DESC
      ) AS rn,
      cum_contrib,
      total_contributions
    FROM contrib_running
  ) x
  WHERE cum_contrib >= total_contributions * 0.5
  GROUP BY full_name
),
latest_release AS (
  SELECT full_name, tag_name AS latest_release, published_at AS release_date
  FROM (
    SELECT
      full_name,
      tag_name,
      published_at,
      ROW_NUMBER() OVER (
        PARTITION BY full_name ORDER BY published_at DESC
      ) AS rn
    FROM my_db.releases
  ) x
  WHERE rn = 1
)
SELECT
  r.full_name,
  r.name,
  r.stargazers_count,
  r.forks_count,
  r.open_issues_count,
  r.language,
  r.topics,
  r.days_since_push,
  r.age_days,
  r.description,
  COALESCE(c.contributor_count, 0) AS contributor_count,
  COALESCE(b.bus_factor, 0) AS bus_factor,
  lr.latest_release,
  CAST(lr.release_date AS DATE) AS latest_release_date,
  CASE
    WHEN r.days_since_push > 365 THEN 'stale'
    WHEN r.days_since_push > 90 THEN 'warning'
    WHEN COALESCE(b.bus_factor, 0) <= 1 THEN 'bus-factor-risk'
    ELSE 'healthy'
  END AS health_status
FROM my_db.github_repos r
LEFT JOIN contrib_totals c ON c.full_name = r.full_name
LEFT JOIN bus b ON b.full_name = r.full_name
LEFT JOIN latest_release lr ON lr.full_name = r.full_name
