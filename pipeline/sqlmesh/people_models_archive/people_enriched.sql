-- people_enriched.sql — a second model showing the dependency graph.
--
-- SQLMesh resolves model-to-model order itself inside the warehouse.
-- This model depends on people_staging and adds a categorization.

MODEL (
  name my_db.people_enriched,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key id
  ),
  audits [
    not_null(columns := (id, full_name)),
    unique_values(columns := (id))
  ]
);

SELECT
  id,
  full_name,
  date_of_birth,
  birth_year,
  age_days,
  CASE
    WHEN age_days < 6570  THEN 'child'    -- < 18 years
    WHEN age_days < 23725 THEN 'adult'    -- 18-65 years
    ELSE 'senior'
  END AS age_category,
  _loaded_at
FROM my_db.people_staging
