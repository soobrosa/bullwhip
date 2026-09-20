"""people_ingest source — the dlt source for the incremental_load example.

dlt-ops discovers sources from pipeline directories.  This module defines
a dlt source that extracts the people table from a source Postgres with
an incremental cursor on updated_at.
"""

import dlt
from dlt.sources.sql_database import sql_database


@dlt.source
def people_ingest():
    """Extract the people table from source Postgres with incremental cursor."""
    db = sql_database(
        credentials=dlt.config["sources.people_ingest.credentials"],
        schema="public",
    )

    @dlt.resource(primary_key="id", write_disposition={"disposition": "merge"})
    def people():
        yield db.table("people").with_incremental("updated_at")

    return people
