# QUESTION ENGINE — Technical Specification v1.1

**An autonomous agentic swarm that monitors emerging trends and formulates novel questions.**

Owner: Jamie · Built in this repo · Hosted on: Render.com · Output: Daily markdown digests + dashboard

Standing design for Phase 1 as of 2026-09-01. Where a section is marked **SUPERSEDED**,
the old text is the record of a prior design; the superseding block is what to build.

### Document identity — two copies (CW Finding 001, 2026-09-01)

This file was **authored in the implementer workspace on 2026-09-01** as a standing
write-up of Phase 1 as built, plus later rulings. It is **not** the
`question-engine-tech-spec-v1.1.md` dated 2026-08-31 in the Claude project
knowledge. That project copy is a different document. CW read the project copy
in full; this file is what the repo builds against.

Consequences already confirmed:

- The project copy specifies `agent_calls` in §7 (table list, observability
  sentence, prompt version stamp) and in **§10 Phase 1**. This file omitted
  those lines when it was written. That is a condensation gap, not proof the
  spec never required the table.
- The project copy still carries unsuperseded `embedding: list[float]` (§3.3)
  and cosine ~0.92 (§3.4). This file supersedes both in place. Rulings have
  been landing in only one of the two documents.
- The project copy types `source_briefs` / `brief_ids` as `list[int]` and
  `intersection_id` as `int | None`. The running code uses `str` for
  `Question.id`, `Brief.id`, and `Intersection.id`. This file follows the code.

Until the project copy is replaced or superseded to match this file (or this
file is replaced by the project copy plus the rulings), **"the spec says X" is
ambiguous**. This file is canonical for the repo and the build. The project
copy is the prior design record.

---

## 1. Concept

Most trend tools summarize. This system interrogates. It pulls signals across a
thin set of verticals, hunts for non-obvious intersections, and writes questions through
three lenses. A curator kills anything generic. Ratings feed the next day's taste.

### Run cadence — SUPERSEDED IN PLACE 2026-09-03 (WO-001)

> **Was (v1.1 concept + autonomous-by-design):** a daily cron at 10:00 UTC. Spec
> argument, still true and not deleted: *"A 10-minute morning approval step is the
> kind of small friction that quietly kills daily habits. After-the-fact ratings
> are a slightly weaker training signal, but a signal actually provided beats a
> cleaner one that gets skipped."* A system you must remember to run is a system
> you stop running. That risk now applies.

**Cost check before the reversal (one real keyed run, 2026-09-03, $0.968, 13
curated / 9 killed).** Daily ≈ $29/month API on top of Render. Alternatives that
keep some habit:

| Option | Monthly API cost | Keeps the daily habit? |
|---|---|---|
| Manual only (Operator asked) | Whatever you trigger | **No** |
| Weekdays only (`0 10 * * 1-5`) | ~$21 | Yes |
| 3×/week (`0 10 * * 1,3,5`) | ~$12 | Mostly |
| Daily, cheaper judgment model | Lower per run | Yes |

**Now:** the Operator chose **manual only**. The cron service stays (Render
Trigger Run needs it). Its Blueprint `schedule` is `0 0 29 2 *` (29 February)
because `schedule` is a required Blueprint field — this is not a daily job.
Controls → Run swarm now stays. Today and the digest footer show **last run:
N days ago** and mark the digest stale after `STALE_AFTER_DAYS` (default 3).
Do not suspend the cron: a suspended cron cannot be Trigger-Run'd.

Dependency, not this change: the web service still holds a multi-workspace
Anthropic key unless `ANTHROPIC_WORKSPACE_ID` is set or the key is
single-workspace. Controls 400s without that. Cron Trigger Run uses the same
env group.

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

**IDs — SUPERSEDED IN PLACE 2026-09-01 (CW 001, incidental).** The project copy's
§3.2 / §3.3 type `source_briefs` / `brief_ids` as `list[int]` and
`intersection_id` as `int | None`. The running code uses `str` for `Question.id`,
`Brief.id`, and `Intersection.id`. Provenance and §12 follow the code. The
project copy is stale on those types.

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

## 6. Dashboard — SUPERSEDED IN PLACE 2026-09-01 (§12)

> **Was (v1.1 / v1.0 Today page):** ★1–5 rating widget on every question; *"promote to
> ideation"* button for any non-top-5 question. That line treated promotion as a UI
> affordance whose destination was implied. In the repo, `POST /api/questions/{id}/promote`
> only sets `promoted = True` (and may force `status=curated`). No idea row, no timestamp,
> no thread. The button goes nowhere.

**Now:** ratings stay on Today / Archive (taste). **Promote** is intent: it is the only
door into the catalog. What promotion writes, and what an idea / spec is, lives in **§12**.
Do not invent a pipeline mid-build from this line.

Today, Archive, Taste, Controls. `/healthz` is unauthenticated and does not check the
dashboard token. `pgvector_installed` is `false`. Taste shows lexical mark counts with
the same caveat as the footer — a low number must not read as "working." A Pipeline
page is not Phase 1; it is the first slice of §12, after the §12 greenlight conditions.

## 7. Stack — SUPERSEDED IN PLACE 2026-09-01 (§12, agent_calls) — amended same day (CW 001)

> **Was (project copy v1.1, 2026-08-31 — four occurrences, verbatim as CW read them):**
>
> - §7 Tables — `runs, agent_calls, signals, briefs, intersections,
>   intersection_rejections, questions, dedup_drops, curator_decisions, ratings,
>   taste_profiles, digests, resurrection_links, projects, source_health`
> - §7 Observability — *"one runs row per execution; one agent_calls row per LLM
>   call (stage, model, prompt version, tokens, cost, latency, input/output JSON).
>   When a bad question ships you can trace scout brief → intersection → smith
>   draft → curator reason."*
> - §7 repo layout — prompts are versioned `.md`, one per agent; *"version stamped
>   into agent_calls"*
> - §10 Phase 1 — *"…run lock, budget cap, agent_calls logging, email delivery of
>   Top 5."*
>
> That observability sentence is the spec's. The voided build prompt quoted it; it
> did not originate it. **This repo file omitted those four lines when it was
> condensed on 2026-09-01.** The first supersession of this section wrongly treated
> that omission as "the spec never named the table." That manufactured an absence.
> The table still does not exist in the build. Against the project copy, that is a
> **Phase-1 gap**, not an unspecified feature.
>
> What the system actually persists per run: `stages[]`, `current_stage`,
> `cost_usd`, `warnings`, `source_health`. Not model, prompt version, tokens,
> latency, or I/O per call.

**Now — disposition (a), justification amended:** add `agent_calls` **with the
catalog**. The requirement was specified for Phase 1. The build does not have it.
We are deferring an unimplemented Phase-1 requirement to the catalog ship — we are
not recording that it was never specified. Ideator and spec-writer each produce an
object the Operator acts on; those are the calls that must be traceable, and they
are the natural moment to add the table. Swarm stages may start writing the same
table then. Checkpoints remain resume machinery. See §12.4. Do not promote
checkpoints to fill this role.

Python 3.12 · FastAPI + Jinja2 · SQLAlchemy · SQLite locally / Render Postgres ·
Anthropic API only. Tables that exist today: `runs`, `signals`, `briefs`,
`intersections`, `questions`, `ratings`, `digests`, `run_locks`. Fail loud; never
silent-fallback. A degraded source is named, not swallowed.

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

## 10. Phase 1 milestone — SUPERSEDED IN PLACE 2026-09-01 (CW 001)

> **Was (project copy §10):** Phase 1 includes *"run lock, budget cap, agent_calls
> logging, email delivery of Top 5."* `agent_calls` logging was a Phase-1 item,
> not a later phase.

**Now:** the milestone is still a digest Jamie wants to open on day 3. Run lock
and budget cap exist. Email does not. `agent_calls` logging does not — it is a
Phase-1 gap deferred to the catalog ship (§7 / §12.4), not dropped from the
record. Not a second scaffold. Not Voyage.

## 11. Explicitly not yet

Embeddings-as-a-service. pgvector. Ideator (held — contract in §12, no build until
§12.8). Resurrection. Weekly taste compressor. Eval harness. Extra verticals/lenses.
GitHub-committed digests (Render disk is ephemeral; the DB is the archive).
`agent_calls` (held — added with the catalog, §7 / §12.4). Pipeline page, idea
cards, spec-writer (held — §12).

## 12. Catalog & Pipeline (the second object)

**Written 2026-09-01. Spec only. Not a build order.** Authorized by CP greenlight
after Grok's response to `CP-RESPONSE-catalog-pipeline.md`. The digest is the
newspaper. The catalog is the filing cabinet. Specs are work orders.

### 12.0 Frame

Three objects: `Question` (exists) → `Idea` (on human promote) → `Spec` (explicit
human action on a Buildable card). A fourth object, `Note`, holds a belief update
that is neither a product nor an essay.

**Ratings are taste. Promotion is intent.** Never auto-file curated questions into
the pipeline. Coverage / whitespace never promotes an idea to Buildable (same
ruling as the curator). Ideator and spec-writer run **out-of-band from the
dashboard**, never in the cron, so a burst of curiosity cannot starve tomorrow's
digest. Postgres is canonical. Ideas and specs export as `.md` the way digests do.

A spec may be written only when all three are true: the Operator marked the idea
**Buildable**, the Operator clicked **Write build spec** on that card, and the spec
names one first slice (a day-3 digest, not a platform). Specs are shaped like this
file in miniature: concept, pipeline, not-in-scope, milestone. Supersede in place.

### 12.1 Contracts

IDs that already exist in this repo stay the types the repo uses. `Question.id`,
`Intersection.id`, and `Brief.id` are `str`. `run_id` is `int`. New catalog rows
may use `int` primary keys. `Coverage` includes `unknown`.

```python
class PipelineStatus(str, Enum):
    inbox = "inbox"            # promoted, no card yet
    briefed = "briefed"        # card exists, shape undecided
    parked = "parked"          # real, not now
    buildable = "buildable"    # Operator marked SaaS / app / tool
    specced = "specced"        # SpecDoc exists
    building = "building"      # handed to a CC session
    shipped = "shipped"
    killed = "killed"          # with reason

class Shape(str, Enum):
    product = "product"
    investigation = "investigation"
    essay = "essay"
    nonprofit = "nonprofit"
    unclassified = "unclassified"

class Thread(BaseModel):
    id: int
    title: str                          # "Eldercare logistics under labor shortage"
    thesis: str                         # one line, revised as the thread grows
    verticals: list[str]
    opened_at: date
    last_touched: date
    # Do not persist idea_ids / note_ids / question_ids. Derive them.

class IdeaDoc(BaseModel):
    id: int
    question_id: str
    thread_id: int | None
    status: PipelineStatus
    shape_guess: Shape                  # ideator's guess
    shape: Shape | None                 # Operator's decision, overrides guess
    concept: str                        # one paragraph
    who_is_in_pain: str
    why_now: str
    wedge: str
    weekend_test: str
    why_it_might_fail: str
    provenance: Provenance
    decay_class: DecayClass             # column from day one; no reader until resurrection
    kill_reason: str | None
    created_at: datetime
    updated_at: datetime

class Provenance(BaseModel):
    question_id: str
    intersection_id: str | None
    brief_ids: list[str]
    run_id: int
    lens: str
    coverage: Literal["none", "thin", "crowded", "unknown"] | None

class Note(BaseModel):
    id: int
    thread_id: int | None
    question_id: str | None
    body: str                           # one paragraph
    author: Literal["operator", "ideator"]
    accepted: bool                      # False = ideator draft; True = Operator-authored or accepted
    created_at: datetime

class SpecDoc(BaseModel):
    id: int
    idea_id: int
    version: int                        # increment; old rows stay readable
    title: str
    concept: str
    first_slice: str                    # the day-3 milestone, one paragraph
    pipeline_or_architecture: str
    stack: str
    not_in_scope: list[str]
    open_questions: list[str]
    markdown: str                       # rendered, downloadable
    created_at: datetime
    superseded_by: int | None           # no history table
```

Tables when this ships: `threads`, `ideas`, `notes`, `specs`, `agent_calls`.
`questions` gains `promoted_at` and `thread_id` (nullable). `thread_id` on a
question is written **only** at promote time (Operator confirm / override). It is
never assigned by a nightly lexical pass.

**Ruling — non-promoted thread tagging (Q-C).** Out of the first slice. If it
ever ships, it writes a `thread_candidates` join, **never** `questions.thread_id`.
Auto-setting `thread_id` on the daily bank is auto-filing by another name. Do not
re-open this as a cheap win.

### 12.2 Thread assignment

Threads are in the first slice. They answer "what territory does the system keep
circling." Assignment is **one judgment-model call folded into the ideator
prompt** (one prompt, two outputs: `IdeaDoc` + thread proposal: existing / new /
ambiguous).

- Suggested **existing** thread may default-accept when the thesis is on screen.
- **New** and **ambiguous** require a click.
- Threads are **never** auto-opened from the daily bank.
- On the heuristic path (no `ANTHROPIC_API_KEY`): `thread_id` stays null, status
  stays `inbox`. Do not invent a thread without a key.

### 12.3 Notes

Operator-authored in v1. The ideator may propose a note when `shape_guess` is
`unclassified`; a proposed note is a draft (`accepted=False`) until the Operator
accepts. No status, no card.

### 12.4 `agent_calls` — disposition (a)

The project-copy spec required this table in Phase 1. The table does not exist.
That is a Phase-1 gap. Stage checkpoints are not a substitute (see §7). Add
`agent_calls` **with this catalog** — a deferral of an unimplemented requirement,
not a claim it was unspecified. Each ideator call and each spec-writer call
writes a row: stage, model, prompt version, tokens, cost, latency, input/output
JSON, and the `idea_id` / `spec_id` acted on. Swarm stages may start writing the
same table when the catalog ships; until then, do not pretend per-call
observability exists.

### 12.5 First slice (build target, after §12.8)

1. **Pipeline page:** promoted questions grouped by thread, then by status. Manual
   status moves including Parked and Killed (with reason).
2. **On promote:** one out-of-band judgment-model call writes the `IdeaDoc` and
   proposes a thread. Operator confirms or overrides. Heuristic path: inbox, no
   thread (§12.2).
3. **Notes:** add-note on any thread or question. Operator-authored in v1;
   ideator-proposed drafts later.
4. **Write build spec:** explicit action on Buildable cards only. Versioned
   `SpecDoc`, downloadable as `.md`. `version` + `superseded_by`; old rows stay
   readable. No history table.
5. **Pipeline this week** in the **daily digest markdown** the archivist already
   writes — not email (email does not exist). Inbox > 7 days, threads that grew,
   Buildable cards with no spec, Notes added.

Do not invent a taxonomy of shapes beyond the five above before 20 promoted items
exist. No thread merge/split UI; manual `thread_id` edits are enough until threads
are messy.

### 12.6 Backlog (not first slice)

Each item has a re-trigger so this is not a graveyard. `decay_class` on `ideas` is
**not** backlog — it is a first-slice column with no reader until resurrection.

| Item | What | Re-trigger |
|---|---|---|
| 6.1 Taste weight | Promoted-and-Buildable questions are top-tier exemplars; killed ideas with reasons are top-tier anti-exemplars. | Ships **with** the weekly taste profiler, not before. |
| 6.2 Thread deep-dive | On-demand mini-run scoped to one thread's territory; no digest; candidates land on the thread. Out-of-band, separate budget cap. | Phase 3, and the thread has 3+ ideas. |
| 6.3 Context pack | One `.md` bundle: card, questions, briefs, notes, spec. What gets dropped into a CC session. | First time a spec is handed to a build session and the Operator is copy-pasting. |
| 6.4 Spec-writer reads prior specs | Titles + not-in-scope of specs 1..N-1, to catch overlap. | Second spec is requested. |
| 6.5 Shape override is a labeled event | Persist every Operator override of `shape_guess`. | First slice may store `shape` vs `shape_guess`; the *aggregate override rate* is read after 20 promotes. |
| 6.6 Kill-reason vocabulary | Distinguish "already exists (link)" / "not my problem" / "too early" in the weekly nudge sample. | After 10 killed ideas, if reasons are free-text mush. |
| 6.7 Resurrection reads Parked ideas | Parked + `decay_class` vs today's briefs. | When the resurrection agent ships (Phase 3). Column already present. |
| Q-C `thread_candidates` | Lexical suggest of non-promoted questions onto open threads. Never writes `questions.thread_id`. | After threads exist and the Operator is manually attaching orphans every day. |

### 12.7 What not to build

- Auto-filing. Auto-speccing. Anything that turns the daily bank into work orders.
- A second markdown store in GitHub. Postgres is canonical; `.md` is an export.
- Thread merging/splitting UI in the first slice.
- A taxonomy of shapes beyond the five in §12.1.
- Ideator on heuristic-fallback output. Three keyed digests first, no exceptions,
  including "just to see the card shape."
- Any of §12.6 in the first slice, except the `decay_class` column.
- Auto-opening threads from the daily bank.
- Promoting stage checkpoints to stand in for `agent_calls`.

### 12.8 Greenlight conditions for the *build*

Build the first slice when **all** of:

1. Three keyed (Opus/Fable) digests exist and the Operator has rated them.
2. CW has read the **deployed** service and confirmed what Promote does. The
   2026-09-01 repo read (boolean only) closed the design question — slice 2 is
   new tables, not a migration — and does **not** satisfy this condition.
3. §12 is in this spec (this section) and §6 / §7 have been superseded in place.
4. The Operator greenlights the build. This section is not that greenlight.

Until then: this contract stands. Finish the Render deploy. Run three days. Rate
everything. Do not run the ideator.
