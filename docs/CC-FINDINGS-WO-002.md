# CC Findings Report — WO-002 (retrieval, quality, value)

**From:** CC · **Date:** 2026-09-03 · **Type:** investigation. Nothing ships from this document.

**Spec used:** `docs/question-engine-tech-spec-v1.1.md` in this repo (canonical for the build). The Claude-project file with the same name and version is a different document (CW Finding 001). Rulings in this repo supersede embeddings; the project copy does not.

**Scope of evidence**

| Kind | What |
|---|---|
| Code | Current repo as of this report: pipeline, taste loader, lenses.yaml, no `agent_calls` table |
| One real keyed run | Run **10**, 2026-09-03 18:38–18:42 UTC, `$0.968`, status `degraded`, 13 curated / 9 killed |
| Not measured | Question quality (0 ratings). Prompt token use vs `RUN_TOKEN_CAP`. Scout compression vs source text |
| Reasoning | Labeled as such. Most of Q3 is this kind |

Failed runs 4–9 are **not** quality evidence. They never archived a writer digest.

---

## Q1 — Does this system need RAG?

**The question as posed hides the real one.** Model strength and retrieval solve different problems. Fable reasons over what it is handed. It cannot reason over what it was never handed. The useful question is: **what is the swarm not seeing?**

### Today's fetch is not a retrieval corpus

Run 10 stored **33 signals** (30 Hacker News, 3 Wikipedia). Brave and Reddit contributed **0**. That volume fits a modern context window without a vector index. **Retrieval over today's fetch is not warranted** on this evidence. Claim type: code + one run.

### The corpus that accumulates is history

Spec §7 already persists questions, briefs, intersections, curator reasons, ratings. Named consumers of retrieval over that history:

- Resurrection §3.7 — Phase 3
- Curator pre-filter §3.5 — similarity to past 4–5★
- Semantic dedup §3.4

**All three want the same embedding store. The third is already ruled.**

**This reopens a ratified decision.** Dedup is **lexical** (CP ruling 2026-09-01, `docs/CP-RULING-dedup.md`). Adding embeddings for "RAG" makes semantic dedup almost free and quietly overturns that ruling. Route any "add retrieval" proposal to **CP**. Do not add a vector column as an implementation detail of a quality feature.

The ruling is cheap to revisit: nothing is stored as a vector. A later change is a nullable column + backfill, not a rewrite. Revisit it **deliberately**.

**Re-trigger already written:** three Operator-flagged near-miss paraphrase pairs, or the offline leak measurement after three keyed weeks. One run and **zero ratings** does not meet it.

### What the swarm is not seeing (from run 10)

| Stage | Count | Note |
|---|---|---|
| Signals fetched | 33 | HN 30, Wikipedia 3. Brave 0, Reddit 0 |
| Briefs | 8 | ai 4, business 3, health **1** |
| Questions | 22 | |
| Curated / killed | 13 / 9 | |

**33 → 8 is a scout bottleneck**, not a missing index. Health arriving as one brief is a fetch/routing problem (Brave down, Wikipedia thin, keyword routing on HN titles). A stronger judgment model cannot recover a vertical that never reached it.

Whether those 8 briefs **dropped names, numbers, and mechanisms** is not measured. `agent_calls` does not exist, so scout input/output cannot be diffed. Hypothesis, not finding: lossy scout summarisation is a likelier quality ceiling than absent retrieval, and cheaper to test — once `agent_calls` exists, compare signal titles/snippets to brief `what_is_happening`.

`RUN_TOKEN_CAP=400000` is still scaffold filler (CW already noted). No run has reported hitting it. Not evidence it is right.

### Explicit negative

**Do not add RAG / Voyage / pgvector for today's fetch.** Not warranted. History-side retrieval is a Phase 3 / curator-prefilter conversation that **must go through CP** because it reopens lexical dedup.

**On "is Fable enough?":** one keyed run, zero ratings, taste seed unfilled. There is no evidence Fable is or isn't enough. The missing input is Jamie's taste and Jamie's stars, not a retriever.

---

## Q2 — What would materially improve the system?

Do not rediscover the known broken list. Ranked by leverage given current evidence:

### 1. Operator fills `taste/seed.md` / `taste/seed.yaml` — not an engineering finding

The curator is running on `data/taste_seed.yaml` (stand-in). `taste/seed.md` is empty on purpose. **Every quality judgment before Jamie writes that file is measuring the wrong thing.** Highest-leverage change available. Costs no code. An AI-written seed would look like it worked.

### 2. Rate the 13 curated questions from run 10

Spec §8 sequence: weeks 1–3 run and rate. **Zero ratings exist.** Without stars there is no eval pack, no curator pre-filter signal, and no evidence the questions are good.

### 3. `agent_calls` (known Phase-1 gap)

Spec (project copy) required one row per LLM call with I/O JSON. Disposition (a) deferred it to the catalog. CW Finding 002: a 400 body was discarded for a day. Any quality investigation is hobbled without it. **Hypothesis that it is needed:** already confirmed by the debugging cost; not a "standard practice" claim.

Cost to add: a table + write in `llm.py`. Breaks nothing if append-only. Reopens the "defer to catalog" disposition — name that if someone builds it early.

### 4. Distinguish "lost a source" from "zero model calls"

Both can look like `degraded`. Fail-closed now refuses a heuristic digest when the key is set and every call fails (runs 4–9). Run 10 is `degraded` with $0.97 spent — that is "lost sources, writer worked." Keep those cases distinct on Controls (error vs writer_ok_calls). In scope of visibility, not a new agent.

### 5. Web / env group Anthropic key (known, not this study)

Identity-linked key needs `ANTHROPIC_WORKSPACE_ID` or a single-workspace key. Manual-only (WO-001) is worse if Controls 400s. **Dependency.**

### 6. Fetch mix, not retrieval

Run 10 was an HN digest with a Wikipedia garnish. Health had one brief. Material improvement: Brave 429 handling (already patched in repo, may not be live), Reddit remaining degraded-OK, maybe arXiv when the source list actually includes it. Evidence: source counts on run 10. Cost: adapter work. Does not reopen Q1.

### 7. Phase 2 lenses — config, if they exist

Spec talk of Underserved / Philanthropic as Phase 2. **This repo's `swarm/config/lenses.yaml` only has the three Phase 1 lenses.** Turning them on is not a one-line enable until those entries are added. Cheap, but it is a YAML write, not a flip of an existing `enabled: false`.

### Explicitly not recommended on current evidence

- Embedding store / RAG (see Q1; reopens CP lexical ruling)
- Catalog / ideator (still gated on three keyed **rated** days)
- Changing Fable vs Sonnet to "improve quality" before taste + ratings
- Business design (Q3)

Enhancements justified only by "RAG is standard" are hypotheses. They are listed here as rejected for now.

---

## Q3 — Value capture (what would have to be true)

**Evidence gate:** one real run, 13 questions, **zero ratings**, taste seed empty. Designing a business on unevaluated output is the same class of failure this project has been catching elsewhere. This section is **reasoning**, not measurement.

### Shapes value could take

| Shape | Requires | Who might pay | Defensible beyond "we called a good model"? |
|---|---|---|---|
| Published feed / newsletter | Weeks of rated output people return to; a voice | Subscribers or a sponsor | Only if the questions are recognizably Jamie's, not generic Fable |
| Research tool others run on their verticals | Productization, their taste seed, their keys | Operators in a niche | Config + taste, easily copied |
| Data product (intersection / rejection corpus) | Volume + labels; legal review of source-derived reuse | Researchers, strategists | The **rejection log** is the unusual artifact |
| Bespoke analysis for one industry | A client, a filled taste file, liability conversation | One buyer | Relationship + accumulated keep/kill, not the model |
| Engine licensed, output not sold | Stable API, evals, support | Teams that want the swarm | Same as the tool path |

### What is actually proprietary

Public sources + a frontier model is **not** a moat. A competitor rebuilds the pipeline in a month.

Candidates that could compound:

1. **Accumulated taste profile** — only after Jamie writes the seed and rates weeks of output.
2. **Curator decision corpus** (labelled keep/kill) — nobody else has Jamie's labels. Empty today.
3. **Cross-pollinator rejection log** — persists; value unproven until someone uses the rejects.

None of these exist as an asset yet. They are what would have to become true.

### Value to people at large

The cheapest available answer is **turning on Underserved / Philanthropic lenses** once they are actually in `lenses.yaml`. That is a config change, not a platform. It does not need a company.

### What would disqualify each path (not resolved)

- Legal / IP on republishing source-derived headlines and snippets
- Whether an "insight" is ownable
- Quality liability if someone acts on a generated question

These need a human and possibly a lawyer. CC is neither.

**Out of scope here:** market size, revenue, investment merit.

---

## Routing

| Finding | Action |
|---|---|
| No RAG for today's fetch | Do not build |
| History retrieval / semantic dedup | **CP** — reopens lexical ruling |
| Taste seed empty | **Operator** — one hour, no code |
| Rate run 10 | **Operator** |
| `agent_calls` | Separate build order; reopens defer-to-catalog disposition |
| Manual-only schedule | WO-001 (build) |
| Web API key | Known dependency; not this study |
