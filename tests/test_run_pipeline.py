"""Tests for the dlt EL pipeline runner (run_pipeline.py).

dlt is imported at function level, so we inject a MagicMock into sys.modules
to avoid pulling in the real (heavy, optional) dependency.  We never actually
run a dlt pipeline — we only exercise argument parsing and pipeline
construction logic.
"""

import sys
import types
from pathlib import Path
from unittest import mock

import pytest

# Ensure lib is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline" / "lib"))

import run_pipeline  # noqa: E402


@pytest.fixture
def dlt_mock():
    """Inject a fake `dlt` module into sys.modules for the duration of a test."""
    fake = mock.MagicMock(name="dlt")
    sys.modules["dlt"] = fake
    yield fake
    sys.modules.pop("dlt", None)


# ---------------------------------------------------------------------------
# build_sql_database_source
# ---------------------------------------------------------------------------

def test_build_sql_database_source_no_incremental(dlt_mock):
    """A sql_database source is built with credentials and no incremental hook."""
    connector = mock.MagicMock()
    connector.env = {
        "PGUSER": "u",
        "PGPASSWORD": "p",
        "PGHOST": "h",
        "PGPORT": "5432",
        "PGDATABASE": "d",
    }

    table = mock.MagicMock(name="table")
    source = mock.MagicMock(name="source")
    source.return_value = table
    dlt_mock.sources.sql_database.return_value = source

    args = mock.MagicMock()
    args.schema = "public"
    args.table = "people"
    args.incremental = None

    result = run_pipeline.build_sql_database_source(args, connector)

    assert result is table
    # The source factory was called with a postgresql:// credentials string.
    call_kwargs = dlt_mock.sources.sql_database.call_args
    creds = call_kwargs.kwargs["credentials"]
    assert creds == "postgresql://u:p@h:5432/d"
    assert call_kwargs.kwargs["schema"] == "public"
    # The source was called to obtain the table resource.
    source.assert_called_once_with("people", table_adapter_callback=None)
    # No incremental hook attached.
    table.with_incremental.assert_not_called()


def test_build_sql_database_source_with_incremental(dlt_mock):
    """When --incremental is set, with_incremental is called on the table."""
    connector = mock.MagicMock()
    connector.env = {
        "PGUSER": "u",
        "PGPASSWORD": "p",
        "PGHOST": "h",
        "PGPORT": "5432",
        "PGDATABASE": "d",
    }

    table = mock.MagicMock(name="table")
    incremental_table = mock.MagicMock(name="incremental_table")
    table.with_incremental.return_value = incremental_table
    source = mock.MagicMock(name="source")
    source.return_value = table
    dlt_mock.sources.sql_database.return_value = source

    args = mock.MagicMock()
    args.schema = None
    args.table = "people"
    args.incremental = "updated_at"

    result = run_pipeline.build_sql_database_source(args, connector)

    assert result is incremental_table
    table.with_incremental.assert_called_once_with("updated_at", initial_value=None)


def test_build_sql_database_source_defaults_when_env_missing(dlt_mock):
    """Missing env keys fall back to defaults rather than KeyError."""
    connector = mock.MagicMock()
    connector.env = {}

    table = mock.MagicMock(name="table")
    source = mock.MagicMock(name="source")
    source.return_value = table
    dlt_mock.sources.sql_database.return_value = source

    args = mock.MagicMock()
    args.schema = None
    args.table = "people"
    args.incremental = None

    result = run_pipeline.build_sql_database_source(args, connector)
    assert result is table
    creds = dlt_mock.sources.sql_database.call_args.kwargs["credentials"]
    assert creds == "postgresql://:@localhost:5432/"


# ---------------------------------------------------------------------------
# run_pipeline
# ---------------------------------------------------------------------------

def test_run_pipeline_sql_database_path(dlt_mock):
    """The sql_database source path delegates to build_sql_database_source."""
    connector = mock.MagicMock()
    connector.dlt_destination.return_value = "dest"
    connector.database = "mydb"

    pipeline = mock.MagicMock(name="pipeline")
    result = mock.MagicMock(name="result")
    result.metrics.get.return_value = 100
    pipeline.run.return_value = result
    dlt_mock.pipeline.return_value = pipeline

    args = mock.MagicMock()
    args.config = "cfg"
    args.source_type = "sql_database"
    args.pipeline_name = "bullwhip"
    args.table = "people"
    args.source = "sql_database"
    args.write_disposition = "append"

    with mock.patch.object(run_pipeline, "get_connector", return_value=connector):
        with mock.patch.object(
            run_pipeline, "build_sql_database_source", return_value="source"
        ) as build_mock:
            rc = run_pipeline.run_pipeline(args)

    assert rc == 0
    # dlt.pipeline constructed with the connector's destination and database.
    dlt_mock.pipeline.assert_called_once_with(
        pipeline_name="bullwhip", destination="dest", dataset_name="mydb"
    )
    build_mock.assert_called_once_with(args, connector)
    pipeline.run.assert_called_once_with(
        "source", write_disposition="append", table_name="people"
    )


def test_run_pipeline_generic_source_path(dlt_mock):
    """The generic source path imports a dotted module and calls the factory."""
    # Build a fake importable module `my_source` with a `people` factory.
    fake_mod = types.ModuleType("my_source")

    def people():
        return "source_obj"

    fake_mod.people = people
    sys.modules["my_source"] = fake_mod
    try:
        connector = mock.MagicMock()
        connector.dlt_destination.return_value = "dest"
        connector.database = "mydb"

        pipeline = mock.MagicMock(name="pipeline")
        result = mock.MagicMock(name="result")
        result.metrics.get.return_value = 50
        pipeline.run.return_value = result
        dlt_mock.pipeline.return_value = pipeline

        args = mock.MagicMock()
        args.config = "cfg"
        args.source_type = "generic"
        args.source = "my_source.people"
        args.pipeline_name = "bullwhip"
        args.table = None
        args.write_disposition = "merge"

        with mock.patch.object(run_pipeline, "get_connector", return_value=connector):
            rc = run_pipeline.run_pipeline(args)

        assert rc == 0
        pipeline.run.assert_called_once_with(
            "source_obj", write_disposition="merge", table_name=None
        )
    finally:
        sys.modules.pop("my_source", None)


def test_run_pipeline_generic_source_non_callable_attr(dlt_mock):
    """A generic source whose final attribute is not callable is used as-is."""
    fake_mod = types.ModuleType("my_source")
    fake_mod.const_resource = "already_a_resource"
    sys.modules["my_source"] = fake_mod
    try:
        connector = mock.MagicMock()
        connector.dlt_destination.return_value = "dest"
        connector.database = "mydb"

        pipeline = mock.MagicMock(name="pipeline")
        result = mock.MagicMock(name="result")
        result.metrics.get.return_value = 7
        pipeline.run.return_value = result
        dlt_mock.pipeline.return_value = pipeline

        args = mock.MagicMock()
        args.config = "cfg"
        args.source_type = "generic"
        args.source = "my_source.const_resource"
        args.pipeline_name = "bullwhip"
        args.table = None
        args.write_disposition = "append"

        with mock.patch.object(run_pipeline, "get_connector", return_value=connector):
            rc = run_pipeline.run_pipeline(args)

        assert rc == 0
        pipeline.run.assert_called_once_with(
            "already_a_resource", write_disposition="append", table_name=None
        )
    finally:
        sys.modules.pop("my_source", None)


# ---------------------------------------------------------------------------
# main (CLI)
# ---------------------------------------------------------------------------

def test_main_success_exits_zero(monkeypatch, capsys):
    """main() parses argv and exits 0 when run_pipeline succeeds."""
    monkeypatch.setattr(
        sys, "argv", ["run_pipeline.py", "--config", "cfg", "--source", "sql_database"]
    )
    with mock.patch.object(run_pipeline, "run_pipeline", return_value=0) as rp_mock:
        with pytest.raises(SystemExit) as exc:
            run_pipeline.main()
    assert exc.value.code == 0
    rp_mock.assert_called_once()
    # The parsed args reach run_pipeline.
    passed = rp_mock.call_args.args[0]
    assert passed.config == "cfg"
    assert passed.source == "sql_database"
    assert passed.source_type == "sql_database"  # default
    assert passed.write_disposition == "append"  # default
    assert passed.pipeline_name == "bullwhip"  # default


def test_main_failure_exits_one(monkeypatch, capsys):
    """main() prints a FAILED message and exits 1 on exception."""
    monkeypatch.setattr(
        sys, "argv", ["run_pipeline.py", "--config", "cfg", "--source", "sql_database"]
    )
    with mock.patch.object(run_pipeline, "run_pipeline", side_effect=RuntimeError("boom")):
        with pytest.raises(SystemExit) as exc:
            run_pipeline.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "[run_pipeline] FAILED: boom" in err


def test_main_parses_all_options(monkeypatch):
    """All CLI options are parsed and forwarded to run_pipeline."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_pipeline.py",
            "--config", "config/duckdb.sh",
            "--source", "sql_database",
            "--source-type", "sql_database",
            "--table", "people",
            "--schema", "public",
            "--incremental", "updated_at",
            "--write-disposition", "merge",
            "--pipeline-name", "custom",
        ],
    )
    with mock.patch.object(run_pipeline, "run_pipeline", return_value=0) as rp_mock:
        with pytest.raises(SystemExit):
            run_pipeline.main()
    args = rp_mock.call_args.args[0]
    assert args.config == "config/duckdb.sh"
    assert args.source == "sql_database"
    assert args.source_type == "sql_database"
    assert args.table == "people"
    assert args.schema == "public"
    assert args.incremental == "updated_at"
    assert args.write_disposition == "merge"
    assert args.pipeline_name == "custom"


def test_main_requires_config(monkeypatch):
    """Missing required --config causes argparse to exit non-zero."""
    monkeypatch.setattr(sys, "argv", ["run_pipeline.py", "--source", "sql_database"])
    with pytest.raises(SystemExit) as exc:
        run_pipeline.main()
    # argparse exits with code 2 on usage errors.
    assert exc.value.code == 2
