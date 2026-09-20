# TODO

## Schedulers: GitHub Actions first

Order of support, and what each needs:

1. **GitHub Actions** (`.github/workflows/nightly.yml`) — the primary way.
   Built and verified locally (cold start, real API, fail-fast retries, GNU
   make 4.4, Pages layout). Next steps, in order:
   - [ ] `git init`, push, watch the first scheduled run; enable Pages
   - [ ] after night 2, confirm `star_growth` gained a second row per repo
         (the merge path, fixed 2026-09-17) and the cache round-tripped
2. **Host cron** — the original; `bash lib/run_workflow.sh` in a crontab.
   Works as documented.
3. **Kubernetes CronJob** (`deploy/k8s/cronjob.yaml`) — PVC for warehouse +
   dlt state + logs, `concurrencyPolicy: Forbid`, `backoffLimit: 2` with
   `BULLWHIP_FAIL_FAST=1`, Secret → env, optional dashboard Deployment on
   the same claim. **Not applied to a cluster** (no kubectl here). The image
   is auto-built on push to main by `.github/workflows/docker.yml`; align the
   CronJob's `image:` and Secret name with the repo-derived name.
4. **Docker Compose** — one-shot container, scheduled from outside (host cron
   or the CronJob). cron does not run inside the container. Fixed the volume
   (was a named volume mounted onto the `warehouse.duckdb` *file*; now
   `data:/data` with the relocation env vars). **Not exercised**: Docker is not
   installed on this machine.

Enablers added for 3 and 4 (verified with a relocated warehouse in a scratch
copy): `sqlmesh/config.yaml` reads `BULLWHIP_DUCKDB` via `env_var()`;
`config/bullwhip.sh` no longer overrides it. `BULLWHIP_DUCKDB` and
`DESTINATION__DUCKDB__CREDENTIALS` must point at the same file.

## Known gaps

- [ ] Visually confirm `web/b.html` renders in a browser (the CDN exports are
      verified; the on-page Gantt + ELK DAG layout is not).
- [ ] Redundancy review (the 24-item list) was applied only to E → F, not to
      a/b/c/d.
- [ ] Confirm the dlt-ops upstream handle/link for the README `## Built on`
      row before publishing.
- [ ] Persistence model (2026-09-18): `data/*.parquet` is the durable copy;
      `warehouse.duckdb` is gitignored and rebuilt (restore → idempotent
      re-ingest → model refresh) whenever missing. Verified in a scratch
      copy: cold rebuild, backup skip-on-unchanged, stable row counts across
      re-runs. Confirm the round-trip on the first Actions run.
- [ ] `.github/workflows/nightly.yml` has not run on GitHub yet (repo not
      pushed). Locally verified: cold start, real-API night, fail-fast retries,
      GNU make 4.4, Pages layout under a `/<repo>/` prefix. `actions/cache` is
      the one untested piece; eviction after 7 idle days means a cold warehouse
      and a restarted `star_growth` history.
- [ ] `star_growth` deltas stay null until several nights of snapshots exist.
- [ ] Fixture data gives every repo `bus = 1`; only the real API differentiates.
