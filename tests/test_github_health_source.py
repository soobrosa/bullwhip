"""Tests for the github.com/trending parser in github_health/source."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "github_health" / "source"))

from github_health import parse_trending  # noqa: E402

# Minimal block shapes mirroring the trending page's article structure.
REPO_BLOCK = """
<article class="Box-row">
  <h2 class="h3 lh-condensed"><a href="/duckdb/duckdb" data-hydro-click="x">duckdb/duckdb</a></h2>
  <p class="col-9">An in-process SQL OLAP database &amp; more</p>
  <span itemprop="programmingLanguage">C++</span>
  <a href="/duckdb/duckdb/stargazers"><svg/>24,000</a>
  <span>182 stars today</span>
</article>
"""

DEGENERATE_BLOCK = """
<article class="Box-row">
  <h2 class="h3 lh-condensed"><a href="/solo/repo">solo/repo</a></h2>
</article>
"""


def test_parse_trending_full_block():
    repos = parse_trending(f"<html>{REPO_BLOCK}</html>")
    assert len(repos) == 1
    r = repos[0]
    assert r["rank"] == 1
    assert r["full_name"] == "duckdb/duckdb"
    assert r["total_stars"] == 24000  # comma stripped
    assert r["stars_today"] == 182
    assert r["language"] == "C++"
    assert "OLAP" in r["description"] and "&" in r["description"]


def test_parse_trending_ranks_in_order():
    repos = parse_trending(f"<html>{REPO_BLOCK}{REPO_BLOCK}</html>")
    assert [r["rank"] for r in repos] == [1, 2]


def test_parse_trending_skips_unrecognised_blocks():
    """A block missing stars data is skipped, not guessed into existence."""
    repos = parse_trending(f"<html>{DEGENERATE_BLOCK}{REPO_BLOCK}</html>")
    assert len(repos) == 1
    assert repos[0]["full_name"] == "duckdb/duckdb"


def test_parse_trending_empty_on_unfamiliar_layout():
    assert parse_trending("<html><body>moved to app.example.com</body></html>") == []
