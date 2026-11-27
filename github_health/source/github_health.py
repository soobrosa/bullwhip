"""github_health source — track the health of GitHub's daily trending repos.

Every night it scrapes https://github.com/trending (stdlib HTML parsing, no
extra deps), then pulls repo metadata, contributors, and releases from the
GitHub REST API for the day's trending repos.  dlt-ops wraps it with
pre-load assertions, a runs ledger, and schema-drift reconciliation.

The daily ranking is the interesting grain: repos appear and drop off, so
`star_growth` and the dashboards get real day-over-day movement (the static
three-repo list never did).  There is no official trending API, which makes
the parser the fragile part — it skips blocks it does not recognise, and the
fixture mode exists partly to keep the tutorial running when it breaks.

GitHub token comes from .dlt/secrets.toml [sources.github_health.credentials]
or the environment.  A fixture fallback (GITHUB_HEALTH_FIXTURE=1) returns
inline data so the tutorial runs without a token or network.
"""

import os
import re
import html as html_lib
import datetime
import json
import urllib.request
from typing import Optional

import dlt
from pydantic import BaseModel, ConfigDict

TRENDING_URL = "https://github.com/trending"


# --- Column models (dlt-ops `columns=` rule) -------------------------------
# Declaring the schema lets dlt enforce it (canonical contract) and lets the
# dlt-ops validator check the resource declares its shape.  `extra="forbid"`
# makes dlt fail (not silently drop) on unknown columns.

class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrendingColumns(_StrictModel):
    snapshot_date: str
    rank: int
    full_name: str
    total_stars: int
    stars_today: int
    language: Optional[str] = None
    description: Optional[str] = None


class ReposMetadataColumns(_StrictModel):
    full_name: str
    name: str
    stargazers_count: int
    forks_count: int
    open_issues_count: int
    language: Optional[str] = None
    topics: list[str] = []
    created_at: datetime.datetime
    updated_at: datetime.datetime
    pushed_at: datetime.datetime
    description: Optional[str] = None


class ContributorColumns(_StrictModel):
    full_name: str
    login: str
    contributions: int


class ReleaseColumns(_StrictModel):
    full_name: str
    tag_name: str
    published_at: Optional[datetime.datetime] = None


class StarSnapshotColumns(_StrictModel):
    full_name: str
    stars: int
    snapshot_date: str


def _gh_client(token: str):
    """Minimal GitHub REST client over stdlib urllib (no extra deps).

    Used only in real mode (GITHUB_HEALTH_FIXTURE unset).  Fixture mode
    never touches the network.
    """
    base = "https://api.github.com"
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    class _Client:
        def get(self, path: str):
            req = urllib.request.Request(base + path, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                return json.loads(resp.read().decode("utf-8"))

    return _Client()


# --- trending.github.com scraper (no official API exists) ------------------

def _int(text: str) -> int:
    return int(text.strip().replace(",", "") or 0)


def parse_trending(page: str) -> list[dict]:
    """Parse the trending.github.com HTML into one dict per repo, in rank
    order.  Tolerant by design: blocks that do not match the expected shape
    are skipped, so a layout change degrades to an empty day, not a crash.
    """
    repos = []
    for block in page.split("<article")[1:]:
        # The repo link is the first href that is exactly /owner/repo.
        m = re.search(r'<h2[^>]*>\s*<a[^>]+href="/([^"/]+/[^"/]+)"', block)
        if not m:
            continue
        full_name = m.group(1).strip("/")
        stars_today = re.search(r"([\d,]+)\s+stars?\s+(today|this week|this month)", block)
        total = re.search(
            rf'href="/{re.escape(full_name)}/stargazers"[^>]*>.*?([\d,]+)\s*<',
            block, re.S,
        )
        if not stars_today or not total:
            continue  # unrecognised block; skip rather than guess
        desc = re.search(r"<p[^>]*>\s*(.*?)\s*</p>", block, re.S)
        lang = re.search(r'itemprop="programmingLanguage">\s*([^<]+?)\s*<', block)
        repos.append({
            "full_name": full_name,
            "total_stars": _int(total.group(1)),
            "stars_today": _int(stars_today.group(1)),
            "language": lang.group(1) if lang else None,
            "description": (
                html_lib.unescape(re.sub(r"<[^>]+>", "", desc.group(1))).strip()
                if desc else None
            ),
        })
    return [{"rank": i + 1, **r} for i, r in enumerate(repos)]


def fetch_trending() -> list[dict]:
    """Fetch and parse today's trending page."""
    req = urllib.request.Request(TRENDING_URL, headers={"Accept": "text/html"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=30) as resp:
        page = resp.read().decode("utf-8")
    return parse_trending(page)


# Fixture data — used when GITHUB_HEALTH_FIXTURE=1 (tutorial mode).
# One list drives every resource: the trending ranking plus enough fields to
# synthesise repos_metadata.  Contributors/releases exist only for the first
# three repos, so bus factor and release recency vary like real data would.

FIXTURE_TODAY = "2026-09-18"

FIXTURE_TRENDING = [
    {"full_name": "duckdb/duckdb", "rank": 1, "total_stars": 24000, "stars_today": 182,
     "language": "C++", "description": "An in-process SQL OLAP database management system.",
     "forks_count": 2100, "open_issues_count": 2400, "topics": ["sql", "olap"],
     "created_at": "2018-05-16T10:00:00Z", "updated_at": "2026-09-18T08:00:00Z",
     "pushed_at": "2026-09-18T06:00:00Z"},
    {"full_name": "pallets/flask", "rank": 2, "total_stars": 67000, "stars_today": 95,
     "language": "Python", "description": "The Python micro framework for building web applications.",
     "forks_count": 16000, "open_issues_count": 12, "topics": ["python", "web", "wsgi"],
     "created_at": "2010-04-06T10:00:00Z", "updated_at": "2026-09-18T07:00:00Z",
     "pushed_at": "2026-09-17T10:00:00Z"},
    {"full_name": "tikv/tikv", "rank": 3, "total_stars": 15000, "stars_today": 41,
     "language": "Rust", "description": "Distributed transactional key-value database.",
     "forks_count": 2100, "open_issues_count": 1800, "topics": ["rust", "kv"],
     "created_at": "2016-04-06T10:00:00Z", "updated_at": "2026-09-18T06:00:00Z",
     "pushed_at": "2026-09-18T02:00:00Z"},
    {"full_name": "fastapi/fastapi", "rank": 4, "total_stars": 78000, "stars_today": 77,
     "language": "Python", "description": "Modern, fast web framework for building APIs.",
     "forks_count": 6600, "open_issues_count": 40, "topics": ["python", "async", "api"],
     "created_at": "2018-12-08T10:00:00Z", "updated_at": "2026-09-18T09:00:00Z",
     "pushed_at": "2026-09-18T05:00:00Z"},
    {"full_name": "huggingface/transformers", "rank": 5, "total_stars": 130000, "stars_today": 63,
     "language": "Python", "description": "State-of-the-art machine learning for JLMs.",
     "forks_count": 26000, "open_issues_count": 500, "topics": ["ml", "nlp"],
     "created_at": "2018-10-31T10:00:00Z", "updated_at": "2026-09-18T09:30:00Z",
     "pushed_at": "2026-09-18T07:30:00Z"},
    {"full_name": "ibis-project/ibis", "rank": 6, "total_stars": 5100, "stars_today": 28,
     "language": "Python", "description": "The portable Python dataframe library.",
     "forks_count": 890, "open_issues_count": 410, "topics": ["dataframe", "sql"],
     "created_at": "2014-10-23T10:00:00Z", "updated_at": "2026-09-18T04:00:00Z",
     "pushed_at": "2026-09-18T01:00:00Z"},
]

FIXTURE_CONTRIBUTORS = {
    "duckdb/duckdb": [
        {"login": "hannes", "contributions": 5000},
        {"login": "mythz", "contributions": 300},
        {"login": "richinseattle", "contributions": 200},
    ],
    "pallets/flask": [
        {"login": "davidism", "contributions": 4200},
        {"login": "untitaker", "contributions": 900},
    ],
    "tikv/tikv": [
        {"login": "busyjay", "contributions": 3100},
    ],
}

FIXTURE_RELEASES = {
    "duckdb/duckdb": [{"tag_name": "v1.2.0", "published_at": "2026-05-30T00:00:00Z"}],
    "pallets/flask": [{"tag_name": "3.0.3", "published_at": "2024-08-10T00:00:00Z"}],
    "tikv/tikv": [{"tag_name": "v8.2.0", "published_at": "2026-06-20T00:00:00Z"}],
}


def _get_token() -> str:
    try:
        return dlt.config["sources.github_health.credentials.token"] or ""
    except Exception:
        return ""


@dlt.source(name="github_health")
def github_health():
    """Track GitHub's daily trending repos: the ranking, and each repo's
    metadata, contributors, releases, and daily star snapshots."""

    use_fixture = os.environ.get("GITHUB_HEALTH_FIXTURE", "") == "1"
    today = datetime.date.today().isoformat()

    if use_fixture:
        trending = [dict(t) for t in FIXTURE_TRENDING]
    else:
        trending = fetch_trending()
        if not trending:
            raise RuntimeError(
                f"trending scrape returned no repos — github.com/trending "
                f"layout changed? (parse_trending in github_health.py)"
            )
    repos = [t["full_name"] for t in trending]
    client = None if use_fixture else _gh_client(_get_token())

    @dlt.resource(primary_key=("snapshot_date", "full_name"), write_disposition="merge", columns=TrendingColumns)
    def trending_repos():
        """Today's trending ranking — the day-over-day delta lives here."""
        for t in trending:
            yield {
                "snapshot_date": today,
                "rank": t["rank"],
                "full_name": t["full_name"],
                "total_stars": t["total_stars"],
                "stars_today": t["stars_today"],
                "language": t["language"],
                "description": t["description"],
            }

    @dlt.resource(primary_key="full_name", write_disposition="merge", columns=ReposMetadataColumns)
    def repos_metadata():
        """Repo metadata: stars, forks, issues, topics, dates."""
        if use_fixture:
            for t in trending:
                yield {
                    "full_name": t["full_name"],
                    "name": t["full_name"].split("/")[-1],
                    "stargazers_count": t["total_stars"],
                    "forks_count": t["forks_count"],
                    "open_issues_count": t["open_issues_count"],
                    "language": t["language"],
                    "topics": t["topics"],
                    "created_at": t["created_at"],
                    "updated_at": t["updated_at"],
                    "pushed_at": t["pushed_at"],
                    "description": t["description"],
                }
            return
        for full_name in repos:
            data = client.get(f"/repos/{full_name}")
            yield {
                "full_name": data["full_name"],
                "name": data["name"],
                "stargazers_count": data["stargazers_count"],
                "forks_count": data["forks_count"],
                "open_issues_count": data["open_issues_count"],
                "language": data.get("language", ""),
                "topics": data.get("topics", []),
                "created_at": data["created_at"],
                "updated_at": data["updated_at"],
                "pushed_at": data["pushed_at"],
                "description": data.get("description", ""),
            }

    @dlt.resource(primary_key=("full_name", "login"), write_disposition="merge", columns=ContributorColumns)
    def contributors():
        """Contributors per repo — for bus factor calculation."""
        if use_fixture:
            for full_name in repos:
                for c in FIXTURE_CONTRIBUTORS.get(full_name, []):
                    yield {"full_name": full_name, **c}
            return
        for full_name in repos:
            for c in client.get(f"/repos/{full_name}/contributors?per_page=10"):
                yield {
                    "full_name": full_name,
                    "login": c["login"],
                    "contributions": c["contributions"],
                }

    @dlt.resource(primary_key=("full_name", "tag_name"), write_disposition="merge", columns=ReleaseColumns)
    def releases():
        """Latest releases per repo."""
        if use_fixture:
            for full_name in repos:
                for r in FIXTURE_RELEASES.get(full_name, []):
                    yield {"full_name": full_name, **r}
            return
        for full_name in repos:
            for r in client.get(f"/repos/{full_name}/releases?per_page=5"):
                yield {
                    "full_name": full_name,
                    "tag_name": r["tag_name"],
                    "published_at": r.get("published_at", ""),
                }

    @dlt.resource(primary_key=("full_name", "snapshot_date"), write_disposition="merge", columns=StarSnapshotColumns)
    def star_snapshots():
        """Daily star count snapshot — for growth tracking.

        Merge-keyed on (full_name, snapshot_date) so re-ingesting after a
        warehouse rebuild (pipeline/data/*.parquet is the durable copy) stays
        idempotent instead of duplicating same-day rows.
        """
        if use_fixture:
            for t in trending:
                yield {
                    "full_name": t["full_name"],
                    "stars": t["total_stars"],
                    "snapshot_date": today,
                }
            return
        for full_name in repos:
            data = client.get(f"/repos/{full_name}")
            yield {
                "full_name": full_name,
                "stars": data["stargazers_count"],
                "snapshot_date": today,
            }

    return trending_repos, repos_metadata, contributors, releases, star_snapshots
