"""Exercise the nightly export, site assembly, and CLI reader together."""

import json
import shutil
import subprocess
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import duckdb
import pytest

from bullwhip import cli, daily


FIRST = "2026-11-25"
SECOND = "2026-11-26"
MISSING = "2026-11-27"
PROJECT = "pipeline/examples/github-health"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def test_daily_export_and_cli(tmp_path, monkeypatch, capsys):
    warehouse = tmp_path / "warehouse.duckdb"
    with duckdb.connect(str(warehouse)) as con:
        con.execute("CREATE SCHEMA my_db")
        con.execute("""
            CREATE TABLE my_db.trending_repos AS SELECT * FROM (VALUES
                ('2026-11-25', 1, 'demo/first-day', 250, 30, 'Python', '1'),
                ('2026-11-26', 1, 'demo/prior-attempt', 800, 75, 'Rust', '2'),
                ('2026-11-26', 2, 'demo/second', 600, 50, NULL, '3'),
                ('2026-11-26', 1, 'demo/first', 100, 10, 'Go', '3')
            ) t(snapshot_date, rank, full_name, total_stars, stars_today, language, _dlt_load_id)
        """)
    checkout = tmp_path / "checkout"
    source = Path(__file__).resolve().parents[1]
    (checkout / "web").mkdir(parents=True)
    builder = checkout / "web/build_site.sh"
    shutil.copyfile(source / "web/build_site.sh", builder)
    for file in ("index.html", "shared.js"):
        shutil.copyfile(source / "web" / file, checkout / "web" / file)
    logs = checkout / PROJECT / "logs"
    for day in (FIRST, SECOND, MISSING):
        result = subprocess.run(
            [
                sys.executable, "-m", "bullwhip.daily", "--warehouse", str(warehouse),
                "--date", day, "--output", str(logs / day / "trending.json"),
            ],
            cwd=source, capture_output=True, text=True, timeout=15,
        )
        if day == MISSING:
            assert result.returncode == 1
            assert "no trending rankings" in result.stderr
            assert not (logs / day / "trending.json").exists()
        else:
            assert result.returncode == 0, result.stderr
    (logs / MISSING).mkdir()
    (logs / "index.json").write_text(json.dumps([MISSING, SECOND, FIRST]))

    subprocess.run(["bash", str(builder), PROJECT], check=True, timeout=15)
    site = checkout / "site"
    published = site / PROJECT / "logs"
    assert not (logs / "trending-latest.json").exists()
    assert (published / "trending-latest.json").read_bytes() == (
        published / SECOND / "trending.json"
    ).read_bytes()

    with ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=site)) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            monkeypatch.setattr(daily, "PUBLISHED_LOGS", f"http://127.0.0.1:{server.server_port}/{PROJECT}/logs")

            def invoke(*args):
                monkeypatch.setattr(sys, "argv", ["bullwhip", "daily", *args])
                code = cli.main()
                output = capsys.readouterr()
                return code, output.out, output.err

            code, out, err = invoke()
            assert code == 0 and not err
            assert json.loads(out) == {
                "date": SECOND, "source": "https://github.com/trending",
                "repos": [
                    {"rank": 1, "full_name": "demo/first", "total_stars": 100, "stars_today": 10, "language": "Go"},
                    {"rank": 2, "full_name": "demo/second", "total_stars": 600, "stars_today": 50, "language": None},
                ],
            }

            code, out, err = invoke("--date", FIRST)
            assert code == 0 and not err
            assert json.loads(out)["repos"][0]["full_name"] == "demo/first-day"

            code, out, err = invoke("--date", MISSING)
            assert code == 1 and not out
            assert f"no daily snapshot published for {MISSING}" in err

            (published / SECOND / "trending.json").write_text("{}")
            code, out, err = invoke("--date", SECOND)
            assert code == 1 and not out
            assert "unexpected format or date" in err
        finally:
            server.shutdown()
            thread.join(timeout=5)


@pytest.mark.parametrize("value", ["20261126", "2026-02-30", "../2026-11-26"])
def test_daily_rejects_invalid_date(value, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["bullwhip", "daily", "--date", value])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert "date must be YYYY-MM-DD" in capsys.readouterr().err
