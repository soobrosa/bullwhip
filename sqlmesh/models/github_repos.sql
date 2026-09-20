-- github_repos.sql — staging model over dlt-ingested repo metadata.
--
-- dlt-ops ingests from the GitHub API (or fixture) into the repos_metadata
-- table.  dlt stores the topics array in a child table (repos_metadata__topics),
-- so we reconstruct it here as a list.  This model projects the raw metadata
-- into a clean staging view with derived health columns.

MODEL (
  name my_db.github_repos,
  kind FULL,
  audits [
    not_null(columns := (full_name, stargazers_count)),
    unique_values(columns := (full_name))
  ]
);

SELECT
  rm.full_name,
  rm.name,
  rm.stargazers_count,
  rm.forks_count,
  rm.open_issues_count,
  rm.language,
  rm.topics,
  rm.created_at,
  rm.updated_at,
  rm.pushed_at,
  rm.description,
  -- Days since last push (health signal)
  DATE_DIFF('day', CAST(rm.pushed_at AS DATE), CURRENT_DATE) AS days_since_push,
  -- Repo age in days
  DATE_DIFF('day', CAST(rm.created_at AS DATE), CURRENT_DATE) AS age_days
FROM my_db.repos_metadata rm
