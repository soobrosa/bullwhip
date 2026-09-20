"""people_ingest source — minimal example for examples/incremental_load.

One resource, a declared schema, append disposition: the smallest surface
that still exercises the dlt-ops path (validate, assertions, runs ledger).
Data is inline so the example runs offline — no credentials, no network.
"""

import dlt
from pydantic import BaseModel, ConfigDict


class PersonColumns(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    email: str
    team: str


PEOPLE = [
    {"id": 1, "name": "Ada Lovelace", "email": "ada@example.com", "team": "core"},
    {"id": 2, "name": "Grace Hopper", "email": "grace@example.com", "team": "compiler"},
    {"id": 3, "name": "Edsger Dijkstra", "email": "edsger@example.com", "team": "algorithms"},
]


@dlt.source(name="people_ingest")
def people_ingest():
    """A tiny people table for the incremental_load example."""

    @dlt.resource(primary_key="id", write_disposition="append", columns=PersonColumns)
    def people():
        """Inline people rows — swap for a real API or database cursor."""
        yield from PEOPLE

    return (people,)
