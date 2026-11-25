"""Opt-in end-to-end test of the packaged CLI, including uvx installation."""

import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.getenv("BULLWHIP_TEST_UVX") != "1", reason="requires uvx and dependency access")
@pytest.mark.parametrize("directory", [None, "demo with spaces"])
def test_uvx_demo(tmp_path, directory):
    source = Path(__file__).resolve().parents[1]
    command = ["uvx", "--python", "3.12", "--from", str(source), "bullwhip"]
    outside_db = tmp_path / "outside.duckdb"
    env = {
        **os.environ,
        "TMPDIR": str(tmp_path),
        "MAKEFLAGS": "--invalid-test-flag",
        "GITHUB_HEALTH_FIXTURE": "0",
        "DESTINATION__DUCKDB__CREDENTIALS": str(outside_db),
    }

    def invoke(*args):
        return subprocess.run(
            [*command, *args], cwd=tmp_path, env=env, text=True,
            capture_output=True, timeout=120,
        )

    args = ["demo", "--json"]
    if directory is not None:
        args += ["--directory", directory]
    demo = invoke(*args)
    assert demo.returncode == 0, demo.stderr
    result = json.loads(demo.stdout)
    root = Path(result["directory"])
    assert root.parent == tmp_path.resolve()
    if directory is not None:
        assert root.name == directory
    assert result["ledger"]["records_loaded"] == 27
    assert result["ledger"]["errors"] == []
    assert result["ledger"]["tables"]["github_health"] == 6
    assert [repo["full_name"] for repo in result["repos"]] == [
        "huggingface/transformers", "fastapi/fastapi", "pallets/flask",
        "duckdb/duckdb", "tikv/tikv", "ibis-project/ibis",
    ]
    nodes = {target["id"]: target["deps"] for target in result["dag"]["targets"]}
    assert "../../warehouse.duckdb" in nodes
    assert f"intermediate/{result['date']}/sqlmesh.done" in nodes["imports"]
    assert not outside_db.exists()
    assert not (root / ".dlt/secrets.toml").exists()
    assert (root / "data/contributors.parquet").is_file()

    attempt = Path(result["logs"]) / "attempt-00.log"
    timing = Path(result["logs"]) / "timing_env.log"
    timings = [json.loads(line) for line in timing.read_text().splitlines()]
    assert any(
        row["tag"] == "END" and row["target"].endswith("/sqlmesh.done")
        and row["exit_code"] == 0
        for row in timings
    )

    files = [attempt, timing, Path(result["warehouse"])]
    mtimes = [file.stat().st_mtime_ns for file in files]
    inspected = invoke("inspect", str(root), "--json")
    assert inspected.returncode == 0, inspected.stderr
    assert json.loads(inspected.stdout) == result
    rejected = invoke("demo", "--directory", str(root), "--json")
    assert rejected.returncode != 0
    assert rejected.stdout == ""
    assert "File exists" in rejected.stderr
    assert [file.stat().st_mtime_ns for file in files] == mtimes
