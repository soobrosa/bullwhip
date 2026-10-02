# TODO

## Schedulers: GitHub Actions first

Order of support, and what each needs:

1. **GitHub Actions** (`.github/workflows/nightly.yml`) — the primary way.
   Repo is live at `github.com/soobrosa/bullwhip` (public, pushed 2026-09-20).
   First dispatch run: green — cold-runner persistence round-trip verified
   from the attempt log (parquet restore → strict validate → 4/4 model
   batches → fingerprinted backup re-export). `docker.yml` built and pushed
   the GHCR image; the build-if-missing check re-verified on push 2.
   Remaining, in order:
   - [ ] Enable Pages: Settings → Pages → Source: "GitHub Actions"
         (without it every nightly skips the dashboard deploy)
   - [ ] Make the GHCR package public: Settings → Packages → `bullwhip` →
         change visibility (packages pushed via GITHUB_TOKEN land private;
         the K8s CronJob expects an anonymous pull)
   - [ ] Watch the first *scheduled* run (03:00 UTC cron) end to end
   - [ ] After night 2, confirm `star_growth` gained a second row per repo
         (the merge path, fixed 2026-09-17)
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
      row before publicizing.
- [ ] Persistence model (2026-09-18): `data/*.parquet` is the durable copy;
      `warehouse.duckdb` is gitignored and rebuilt (restore → idempotent
      re-ingest → model refresh) whenever missing. Verified in scratch and on
      the first Actions run (2026-09-20). `nightly.yml` no longer caches the
      warehouse file (would mask a broken restore); dlt state + past nights'
      logs are cached, so `actions/cache` eviction after 7 idle days means a
      cold dlt state and a restarted ledger history.
- [ ] `star_growth` deltas stay null until several nights of snapshots exist.
- [ ] Fixture data gives every repo `bus = 1`; only the real API differentiates.
