# SQLMesh macros — Python functions callable from SQL models.
#
# This replaces the old ERB `post_process` Ruby blocks with Python macros.
# The macro's SQL arguments are parsed into SQLGlot AST expressions; the
# returned AST/string is spliced back into the query.

from sqlmesh import macro


@macro()
def age_bucket(evaluator, age_days):
    """Bucket an age-in-days value into child/adult/senior labels."""
    return f"""
    CASE
      WHEN {age_days} < 6570  THEN 'child'
      WHEN {age_days} < 23725 THEN 'adult'
      ELSE 'senior'
    END
    """
