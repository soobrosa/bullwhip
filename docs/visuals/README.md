# docs/visuals — provenance

Every screenshot here was rendered by headless Chrome from the live dashboard
files (`web/*.html`) while they read artifacts produced by genuine runs of
`bash lib/run_workflow.sh` against `examples/github-health` (fixture mode,
unless noted). No image below was hand-drawn, AI-generated, or edited.

| File | Dashboard | Night | What happened |
|---|---|---|---|
| `a-success.png` | A — Flask port | 2026-09-09 | Full pipeline: validate → ingest → reconcile → sqlmesh, all exit 0 |
| `a-failure.png` | A — Flask port | 2026-09-07 | Real-API mode with a dead proxy: ingest failed (connection refused) |
| `b-success.png` | B — Plot + ELK | 2026-09-09 | Same success night; DAG from `dag.json` |
| `b-failure.png` | B — Plot + ELK | 2026-09-07 | Same failure night |
| `c-success.png` | C — outcome ledger | 2026-09-09 | 21 records loaded, warehouse row counts shown |
| `c-failure.png` | C — outcome ledger | 2026-09-07 | make exit 2 with the dlt-ops ledger showing the failed run |
| `d-success.png` | D — monochrome | 2026-09-09 | Vitals, activity feed, log tree from the success night |
| `d-failure.png` | D — monochrome | 2026-09-07 | FAILED banner (make exit 2), error cell rendered |
| `d-running.png` | D — monochrome | 2026-09-05 | Captured mid-run; DOM probes before/after confirm the live state (`make exit -1` → `0`) |
| `e-success.png` | E — Flask views, monochrome | 2026-09-09 | A's command Gantt in D's language: 10 rows, all solid, DONE banner |
| `e-failure.png` | E — Flask views, monochrome | 2026-09-07 | Outlined bar for the failed ingest, `!` target in log debugging, FAILED banner |
| `e-flow-success.png` | E — log debugging | 2026-09-09 | `?view=flow&open=ingest`: six target blocks, ingest's log expanded |
| `e-flow-failure.png` | E — log debugging | 2026-09-07 | `?view=flow`: the failed ingest block auto-expanded with the dlt traceback |
| `f-success.png` | F — E trimmed | 2026-09-09 | `DONE — 4 targets, 6.97s`; four bars, no time column, no exit codes |
| `f-failure.png` | F — E trimmed | 2026-09-07 | Outlined ingest bar labelled `1.00s exit 1`, the only exit code on the page |
| `f-flow-failure.png` | F — log debugging | 2026-09-07 | Two visible blocks (validate, ingest; reconcile/sqlmesh never ran, intermediate/ and backup folded away); ingest's log open |

Known gap: `b-success.png` / `b-failure.png` show B's chrome only. B's chart
libraries fail to load (wrong ESM import), so its Gantt and DAG sections are
empty in those shots. Left as-is until B is fixed.

The raw artifacts backing these are in `examples/github-health/logs/<date>/`.
Reproduce any shot:

```bash
python -m http.server 8765 -d .
open "http://localhost:8765/web/d.html?project=examples/github-health&date=2026-09-07"
```
