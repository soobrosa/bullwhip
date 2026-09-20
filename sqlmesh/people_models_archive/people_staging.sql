-- people_staging.sql — SQLMesh model that replaces the old ERB loader templates.
--
-- The old incremental_load example had three ERB templates:
--   1. dump_people.erb.sql   → replaced by dlt ingestion (EL worker)
--   2. schema_people.erb.sql  → replaced by this model's schema definition
--   3. update_table.erb.sql   → replaced by dlt's write_disposition: merge
--
-- This model reads from the `people` table that dlt loaded into DuckDB
-- and projects it into a staging view with derived/cleaned columns.
-- dlt's merge disposition already handles the upsert; SQLMesh handles the T.

MODEL (
  name my_db.people_staging,
  kind FULL,
  audits [
    not_null(columns := (id, full_name)),
    unique_values(columns := (id))
  ]
);

SELECT
  id,
  full_name,
  date_of_birth,
  updated_at,
  -- Derived columns
  EXTRACT(YEAR FROM date_of_birth) AS birth_year,
  DATE_DIFF('day', date_of_birth, CURRENT_DATE) AS age_days,
  updated_at AS _loaded_at
FROM my_db.people
WHERE id IS NOT NULL
  AND full_name IS NOT NULL
