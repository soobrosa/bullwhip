# Bullwhip kickoff prompt

Paste the prompt below into a coding agent in an empty Git repository. Use the
[build specification](build-spec.md) for the full requirements and acceptance
checks. Use [AGENTS.md](../AGENTS.md) when changing the existing repository.

> Build Bullwhip, a standalone CLI for an inspectable nightly data pipeline.
> It should run from a Git URL with `uvx`, without a manual clone or a PyPI
> release.
>
> Every day at 03:00 UTC, fetch the real GitHub Trending rankings and publish a
> dated JSON snapshot. `bullwhip daily` reads the latest successful snapshot;
> `--date` reads a specific day. Keep the last good snapshot if a run fails.
>
> Make `bullwhip demo --json` run the same pipeline on bundled data without
> credentials, and make `bullwhip inspect <directory> --json` read the results
> without rerunning it. Use GNU Make, dlt-ops, SQLMesh, and DuckDB. Put the quick
> start in the README and write an LLM-readable `llms.txt`. Test the CLI from
> outside the checkout.
