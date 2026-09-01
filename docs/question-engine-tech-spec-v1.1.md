# QUESTION ENGINE — Technical Specification v1.1

**An autonomous agentic swarm that monitors emerging trends and formulates novel questions.**

Owner: Jamie · Built in this repo · Hosted on: Render.com · Output: Daily markdown digests + dashboard

Standing design for Phase 1 as of 2026-09-01. Where a section is marked **SUPERSEDED**,
the old text is the record of a prior design; the superseding block is what to build.

---

## 1. Concept

Most trend tools summarize. This system interrogates. Every day it pulls signals across a
thin set of verticals, hunts for non-obvious intersections, and writes questions through
three lenses. A curator kills anything generic. Ratings feed the next day's taste.

## 2. Architecture

```
Render:  cron (question-engine-swarm)  →  Postgres (question-engine-db)  ←  web (question-engine-dashboard)
```

### Render Blueprint — SUPERSEDED IN PLACE 2026-09-01 (Q7)

> **Was (never applied):** `plan: basic-256mb` on Postgres; cron `envVars: [same as above]`;
> `DATABASE_URL` implied shared. Those three lines would have failed Blueprint parse.

**Now:** Postgres plan is `0.1c-256mb`. Shared secrets live in env group
`question-engine-shared`. `DATABASE_URL` is declared on **each** service via
`fromDatabase` (env groups cannot hold service-property references). Auth token is
`DASHBOARD_TOKEN` with `generateValue: true`; fallback if Render rejects that inside a
group is `sync: false`. See `render.yaml`.

`JUDGMENT_MODEL=claude-fable-5`, `ANTHROPIC_MODEL=claude-sonnet-5`, `RUN_BUDGET_USD=5.00`,
`RUN_TOKEN_CAP=400000`.

---

## 3. The swarm

All agents return Pydantic models. Stages checkpoint to Postgres before the next starts.
`--resume` continues from the last finished stage.

### 3.0 Pipeline (Phase 1)

```
[1] Fetch (Brave, HN, Reddit, Wikipedia)
        ▼
[2] Scouts (one pass per enabled vertical)
        ▼
[3] Cross-pollinator  → intersections + coverage + rejection log
        ▼
[4] Question smiths (one lens each)
        ▼
[5] Dedup (lexical — see §3.4)
        ▼
[6] Curator  ← taste seed
        ▼
[7] Archivist → DigestDoc + markdown
```

Verticals Phase 1: AI, Health, Business/Finance. Lenses Phase 1: contrarian, second-order,
opportunity. Phase 2 is a `phase:` field in YAML, not a code change.

`JUDGMENT_MODEL` covers cross-pollinator and curator. `ANTHROPIC_MODEL` covers scouts and
smiths. Never hardcode a model string.

### 3.1 Sources

Adapters implement `fetch() -> list[Signal]`. A dead source **degrades** the run; it does
not abort it. Reddit 403 from a datacenter is expected. The test is that the run
completes and the footer names the source, not that Reddit works.

### 3.2 Coverage

Three-valued: `none` / `thin` / `crowded` (plus `unknown`). Visible. Never promotes a
question past the curator on its own.

### 3.3 Question contract — SUPERSEDED IN PLACE 2026-09-01 (ruling d)

> **Was (v1.1 as first written):**
>
> ```
> class Question:
>     id: str
>     text: str
>     lens: str
>     verticals: list[str]
>     coverage: Coverage
>     decay_class: DecayClass
>     embedding: list[float]   # required
>     ...
> ```
>
> The required `embedding: list[float]` assumed a vector stage that §7 could not name
> and §11 forbade. Ruled (d): that field is **removed**. Nothing is stored as a vector.
> Adding one later is a nullable column, not a rewrite of history.

**Now:** `Question` is `id`, `text`, `lens`, `verticals`, `coverage`, `decay_class`,
`status` (`raw` / `duplicate` / `killed` / `curated`), `rank`, `kill_reason`,
`duplicate_of`, `brief_ids`, `intersection_id`, `context`. No embedding field.

`Signal` is `source`, `title`, `url`, `snippet`, `score`, `vertical_hints`, `raw`.
Curator output is the same `Question` objects with `status` / `rank` / `kill_reason`.
Digest JSON is `DigestDoc`.

### 3.4 Dedup — SUPERSEDED IN PLACE 2026-09-01 (ruling d)

> **Was (v1.1 as first written):**
>
> Stage 4 of 8: *embed every candidate (pgvector), drop anything with cosine similarity
> above a threshold (~0.92).*
>
> That stage is not buildable on the named stack. Anthropic has no embeddings API.
> Voyage would bake a dimension into the schema. A sentence-transformer does not fit a
> 256 MB cron. Embeddings-as-a-service is listed under §11 Explicitly Not Yet.

**Now:** Stage 4 exists and runs. Similarity is content-token Jaccard (template
stopwords stripped) against the batch and the last 45 days. Threshold
`DEDUP_THRESHOLD` (default 0.64). Nightly "duplicate rate" is the count of
`status=duplicate` on that run.

**Present tense:** dedup does **not** catch paraphrase. A low lexical duplicate rate
is not evidence that it does. `/healthz` reports `pgvector_installed: false` on
purpose. Do not `CREATE EXTENSION vector`.

**Re-trigger (amended — the original "three keyed weeks show a miss" cannot fire):**

- Every digest samples up to three surviving pairs from adjacent days that share an
  intersection (or at least one vertical). Jamie flags pairs that mean the same thing
  in different words.
- After three keyed weeks, run `python scripts/measure_paraphrase_leak.py` once,
  offline, against stored text. No production column.
- Three of Jamie's flags, **or** a leak rate from that measurement that makes the
  digest feel repetitive → then a *nullable* vector column and a provider chosen then.

Quiet weeks do not count. See `docs/CP-RULING-dedup.md`.

### 3.5 Curator

Taste seed is `taste/seed.yaml` if present, else `data/taste_seed.yaml`.
`taste/seed.md` is Jamie's, empty on purpose. Do not fill it with invented taste.

Output: curated / killed questions with reasons. Kills persist as those rows. No
separate `curator_decisions` table in Phase 1.

### 3.6–3.7 Not in Phase 1

Ideator and resurrection are held until three keyed (Opus/Fable) digests have been
read and rated.

### 3.8 Digest

`DigestDoc`: `date`, `title`, `markdown`, `top_ids`, `curated_count`, `killed_count`,
`duplicate_count`, `rejected_intersection_count`, `degraded`, `warnings`,
`near_miss_pairs`. `GET /digest/{date}.md` renders `markdown`.

---

## 4. Sources (Phase 1)

Tier 1: Brave (skip if no key), Hacker News, Reddit, Wikipedia. Common interface
`swarm/sources/base.py`. Tier 2 (Perplexity coverage, GitHub, PH, EDGAR, …) is not
Phase 1.

## 5. Digest layout

Top questions · Intersections · Full bank · Cross-pollinator passed over · Curator's
kill floor · **Near-miss review** · Source health · Footer (cost + lexical duplicate
count + the paraphrase caveat).

## 6. Dashboard

Today, Archive, Taste, Controls. `/healthz` is unauthenticated and does not check the
dashboard token. `pgvector_installed` is `false`. Taste shows lexical mark counts with
the same caveat as the footer — a low number must not read as "working."

## 7. Stack

Python 3.12 · FastAPI + Jinja2 · SQLAlchemy · SQLite locally / Render Postgres ·
Anthropic API only. Tables: `runs`, `signals`, `briefs`, `intersections`, `questions`,
`ratings`, `digests`, `run_locks`. Fail loud; never silent-fallback. A degraded source
is named, not swallowed.

## 8. Metrics — SUPERSEDED IN PLACE 2026-09-01

> **Was:** nightly duplicate rate as a quality number on the Taste page.

**Now:** that number is lexical only. Label it as such. It will read low and stable
regardless of paraphrase. The instrument that can see a miss is the near-miss sample
and the offline measurement, not this counter.

Eval harness is built *from* real output, not before it. Not Phase 1.

## 9. Cost

Fable is 2× Opus. Phase-1 $0.50–1.50/day estimates written against an unnamed
"Opus/Fable" should be read as the upper half of that range or above.
`RUN_BUDGET_USD=5.00` will tell the truth. Exceeding the budget skips optional
stages; it does not fail the run.

## 10. Phase 1 milestone

A digest Jamie wants to open on day 3. Not a second scaffold. Not Voyage.

## 11. Explicitly not yet

Embeddings-as-a-service. pgvector. Ideator. Resurrection. Weekly taste compressor.
Eval harness. Extra verticals/lenses. GitHub-committed digests (Render disk is
ephemeral; the DB is the archive).
