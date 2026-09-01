# Open Questions — CP rulings

**From:** CP · **Date:** 2026-09-01
**Re:** CW findings against spec v1.1 vs the Phase 1 that already exists in this repo.

CW's document assumed no production system existed. This repo already has a runnable
Phase 1. Rulings below are so CC/Cowork does **not** rebuild from stubs or pick an
embeddings vendor.

---

## Q1 — BLOCKING in the spec, **ruled (d)** in this repo.

The four-way contradiction is real if you read v1.1 in isolation. Anthropic has no
embeddings API; Voyage would bake a dimension into the schema; self-hosting is wrong
for a 256 MB cron; cutting the stage leaves no duplicate metric.

**Ruling: (d) — lexical / payload-aware dedup. No embeddings. No pgvector. No Voyage.**

- Stage 4 exists and runs. It is not a `NotImplementedError` and not a silent pass-through.
- Similarity is content-token Jaccard (template words stripped) against the batch and
  the last 45 days, threshold `DEDUP_THRESHOLD` (default 0.64).
- `Question` has **no** `embedding` field. Adding one later is a migration, not a
  rewrite of history we never stored as vectors.
- Nightly duplicate rate is the count of `status=duplicate` on that run. Footer can
  name it. We did not invent a cosine metric we cannot compute.
- §11's "embeddings-as-a-service" stays deferred. Do not `CREATE EXTENSION vector`.

This is cheap now and reversible: if three keyed weeks show a real near-duplicate
problem lexical miss, *then* pick Voyage and add a nullable vector column.

## Q2 — `Signal` is defined.

`swarm/models.py` → `Signal` (`source`, `title`, `url`, `snippet`, `score`,
`vertical_hints`, `raw`). Adapters implement `fetch() -> list[Signal]`. Do not
re-invent this in `sources/base.py`.

## Q3 — Curator contract is `Question`.

Curator returns the same `Question` objects with `status` (`curated` / `killed` /
`duplicate`), `rank`, `kill_reason`, `lens`, `verticals`, `coverage`, `decay_class`.
Kills persist as those rows. No separate `curator_decisions` table in Phase 1.

## Q4 — Digest JSON is `DigestDoc` / `DigestRow`.

`date`, `title`, `markdown`, `top_ids`, `curated_count`, `killed_count`,
`rejected_intersection_count`, `degraded`, `warnings`. Markdown is the §5 layout.
`GET /digest/{date}.md` renders `markdown`.

## Q5 — Env names.

| Purpose | Canonical | Also accepted |
|---|---|---|
| Dashboard auth | `DASHBOARD_TOKEN` | `ACCESS_TOKEN` |
| Judgment model | `JUDGMENT_MODEL` | — |
| Volume model | `ANTHROPIC_MODEL` | — |
| Budget | `RUN_BUDGET_USD` | `DAILY_BUDGET_USD` |

`generateValue: true` on `DASHBOARD_TOKEN` inside the env group. If Blueprint apply
rejects it, fall back to `sync: false` in `render.yaml` — do not work around in code.

## Q6 — Model values (Operator 2026-09-01).

- `JUDGMENT_MODEL=claude-fable-5` (cross-pollinator + curator)
- `ANTHROPIC_MODEL=claude-sonnet-5` (scouts + smiths)
- `RUN_BUDGET_USD=5.00` (Fable is 2× Opus; the $0.50–1.50 estimate is stale)

## Q7 — Blueprint corrections, adopted.

`0.1c-256mb`, env group for shared secrets, `DATABASE_URL` on each service.
Do not resurrect `basic-256mb` or `envVars: [same as above]`.

---

## What CC/Cowork must not do

- Do not scaffold a second repo.
- Do not stub `run_daily.py` to exit non-zero.
- Do not empty the dashboard down to `/healthz`.
- Do not write `swarm/taste/seed.md` content. Jamie fills that. Until then the
  bundled `data/taste_seed.yaml` is a stand-in so the curator has *a* gate, and it
  is labeled as such.
- Do not add Voyage, sentence-transformers, or pgvector.
