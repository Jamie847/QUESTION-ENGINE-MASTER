# Open Questions — Question Engine

> ## SUPERSEDED IN PART — 2026-09-01, ruled by CC via the Operator, then ratified by CP
>
> **Read this block first. The body below is preserved unedited as the record of what was
> open on 2026-09-01 before the rulings landed. Do not act on the body's options — several
> are closed.**
>
> | | Disposition |
> |---|---|
> | **Q1** embeddings provider | **Ruled (d)** — a fourth option, not among the three below. Dedup is **lexical** (content-token similarity). No vectors, no `embedding` field, no pgvector. Re-trigger (amended by CP the same day): Jamie flags three near-miss pairs as paraphrase, or the offline measurement after three keyed weeks shows a leak. Quiet weeks do not count. See `docs/CP-RULING-dedup.md`. |
> | **Q2** `Signal` undefined | **Closed** — `Signal` exists in the repo; `sources/base.py` is a real interface. Verified in this repo 2026-09-01. |
> | **Q3** curator output contract | **Closed** — `Question` + `status` / `rank` / `kill_reason`. Verified. |
> | **Q4** digest JSON shape | **Closed** — `DigestDoc`. Verified. |
> | **Q5** env var naming | **Adopted.** Auth is `DASHBOARD_TOKEN`; `ACCESS_TOKEN` still accepted. Models: `JUDGMENT_MODEL=claude-fable-5`, `ANTHROPIC_MODEL=claude-sonnet-5`. |
> | **Q6** model values / cost | **Adopted.** `RUN_BUDGET_USD=5.00`, explicitly because Fable is 2× Opus. |
> | **Q7** Blueprint defects | **Adopted.** `0.1c-256mb`, env group for shared secrets, `DATABASE_URL` on each service. |
>
> **The premise the body got wrong.** This document was written against tech spec v1.1 as
> though no implementation existed. A Phase 1 implementation does exist. Q2–Q4 were real gaps
> *in the spec* and were already closed *in the code*; that distinction is the whole error, and
> it is Discipline 1 in the ordinary direction — a document is a label for the system, and this
> one was read as the system.
>
> ### Two items this ruling opens, neither of them a re-litigation of Q1
>
> 1. **Spec v1.1 is now stale in two load-bearing places.** Closed 2026-09-01: §3.3 / §3.4
>    superseded in place in `docs/question-engine-tech-spec-v1.1.md`.
> 2. **Ruling (d) came from the implementer.** Closed 2026-09-01: CP ratified (d) and amended
>    the re-trigger. See `docs/CP-RULING-dedup.md`.
>
> **§1.3 of the voided CC build prompt** tells a reader to verify `pgvector_installed: true`.
> Under (d) `/healthz` reports that **false on purpose**. That check is inverted and would
> fail a healthy system. Do not pick it up.
>
> ### What CW could not verify, and why
>
> `get_device_info` on device `thunderrebel` returned `connectedFolders: []` at 23:15Z,
> 01:43Z and 03:54Z. No file in the Phase 1 repo was read by CW. Closures above for Q2–Q4
> were relayed claims on that date. They have since been verified against this repo.
>
> ---


**From:** CW (Cowork) · **Date:** 2026-09-01
**Re:** tech spec v1.1, scaffolding the repo ahead of the Phase-1 build
**Type:** findings only. Nothing designed, nothing decided. Routes to CP for ruling.

## Verdict

The scaffold is complete and the Blueprint is deployable, but **Phase 1 as specified cannot
be built as written.** §3.4 makes semantic dedup a Phase-1 stage and it depends on an
embeddings provider that §7 does not name, §11 explicitly defers, and the Anthropic API does
not offer. That is Q1 and it blocks. Q2–Q4 are undefined contracts CC would otherwise have to
invent mid-build. Q5–Q7 are corrections already applied to `render.yaml`, listed so the spec
can be superseded rather than silently diverged from.

## Scope of evidence

Read: tech spec v1.1 (project doc, as of 2026-08-31), the deploy brief pasted into this
session on 2026-08-31. Verified externally on 2026-09-01: Anthropic model IDs against
platform.claude.com/docs/en/models/overview; Render Blueprint schema against
render.com/docs/blueprint-spec. **No production system was read — none exists yet.** Every
claim below is about the two documents and the two vendor references, and nothing else.

---

## Q1 — BLOCKING. Semantic dedup has no embeddings provider.

**The contradiction, all four inside v1.1:**

- §3.4 puts semantic dedup in the Phase-1 pipeline (stage 4 of 8): *"embed every candidate
  (pgvector), drop anything with cosine similarity above a threshold (~0.92)"*.
- §3.3's `Question` contract carries `embedding: list[float]` as a required field.
- §7's stack names exactly one LLM dependency: *"Anthropic API"*.
- §11 lists *"embeddings-as-a-service"* under **Explicitly Not Yet**.

**The external fact that makes it blocking:** the Anthropic API has no embeddings endpoint.
Anthropic's own embeddings documentation directs users to Voyage AI. So there is no reading
of §7 under which stage 4 is buildable, and §11 forbids the obvious fix.

**Why this is worth a ruling rather than a build decision:** whatever CC picks becomes a
third API key, a third vendor, a dimensionality baked into the pgvector column, and a
similarity threshold calibrated against that specific model. Changing it later re-embeds the
entire question history. This is a cheap decision now and an expensive one in week 3.

**Options, not recommendations:**
- (a) Add Voyage AI. Costs a key and a vendor; §11's deferral gets lifted with a reason.
- (b) Self-host a sentence-transformers model in the cron service. No vendor, no key; costs
  build time, memory on a `0.1c-256mb`-adjacent plan, and ~90s of cold start.
- (c) Cut stage 4 from Phase 1 and let resurrection + curator absorb near-duplicates until
  there is a real duplicate-rate number to justify the cost. §3.4's own justification is
  that resurrection *doesn't* cover it — but on day 1 there are zero prior questions, so
  dedup is a no-op for roughly the first week regardless.

**Note on (c):** §8 wants duplicate rate as a nightly metric. Under (c) that metric does not
exist, and its absence should be stated in the run footer rather than left blank.

## Q2 — `Signal` is undefined.

§4: *"All adapters implement `fetch() -> list[Signal]`"*. No `Signal` model appears anywhere
in v1.1. Five Phase-1 adapters get built against this. `swarm/sources/base.py` is
deliberately left as a docstring rather than scaffolded, because writing it means inventing
the contract, and five adapters would then be built on an invention.

## Q3 — The curator's output contract is prose only.

§3.5 describes the output — *"15–25 curated questions, ranked, grouped by vertical /
intersection, each with lens, sources, coverage, decay class, and a one-line curator
rationale"* — but gives no Pydantic model, while §3 requires every agent to return one.
Same for the killed questions persisted *"as labeled data"*: `curator_decisions` is named in
§7's table list and never given a shape.

## Q4 — The digest row's JSON shape is unspecified.

§3.8: *"structured JSON + rendered markdown"*. §5 gives the markdown layout in full. The JSON
half is what `GET /digests/{date}.md` renders from and what §8's eval harness replays
against, so its shape is load-bearing for two later phases.

## Q5 — Env var naming. **Operator deferred this to CP on 2026-09-01.**

| | spec §2 | deploy brief |
|---|---|---|
| dashboard auth | `DASHBOARD_TOKEN` | `ACCESS_TOKEN` |
| judgment model | (none — implied hardcoded) | `JUDGMENT_MODEL` |
| worker model | (none) | `ANTHROPIC_MODEL` |

`render.yaml` currently uses **the spec's name** (`DASHBOARD_TOKEN`) on the principle that the
spec is the standing authority until ruled otherwise, and **adds both model vars** because the
Operator ruled on their values (below) and a hardcoded model string is a parameter with no
change record — the exact condition that makes a later parameter drift unattributable.

A rename after first deploy touches this file, the dashboard auth dependency, and the Render
dashboard by hand. Cheap this week.

**Related, and also unresolved:** spec §2 marks the token `sync: false` (Render prompts a
human to type a value); the brief says *"let it auto-generate."* `render.yaml` uses
`generateValue: true`, which is the option where no human handles a secret. **NOT VERIFIED:
that `generateValue` is accepted inside an `envVarGroup` rather than on a service.** Confirm
at apply time; the fallback is `sync: false` plus a locally-generated value.

## Q6 — Model values: ruled, and worth recording as a parameter change.

Operator ruled 2026-09-01: `JUDGMENT_MODEL=claude-fable-5` (not `claude-opus-5` as the brief
first said), `ANTHROPIC_MODEL=claude-sonnet-5`. All three IDs verified live on 2026-09-01.

Cost consequence, since §9's table predates the choice: Fable is $10/$50 per MTok against
Opus's $5/$25 — **2× on both directions** for the two heaviest stages (§3.0 puts both the
cross-pollinator and the curator on the judgment model). §9's Phase-1 estimate of $0.50–1.50/day
was written against an unnamed "Opus/Fable" and should be re-read as the upper half of that
range or above. `RUN_BUDGET_USD` is set to the spec's 5.00 and will tell the truth.

## Q7 — Three corrections applied to the spec's Blueprint. Spec is now stale.

Two would have failed at Blueprint parse:

1. `plan: basic-256mb` is not a valid Render Postgres plan. The ladder starts at
   `0.1c-256mb`.
2. The cron service's `envVars: [same as above]` is prose. Shared vars now live in an
   `envVarGroup`.
3. `DATABASE_URL` cannot live in that group — Render env groups cannot hold service-property
   references — so it is declared on each service explicitly. This is what turns *"confirm
   DATABASE_URL is wired to both"* from a checklist item into a property of the file.

**Request:** supersede these in the spec rather than overwriting §2 — the old plan string and
the `[same as above]` line are the only record that the Blueprint was never applied before.

---

## Not determinable from the documents

- Whether a `0.1c-256mb` Postgres holds pgvector indexes for 60 days of questions at the
  chosen embedding dimensionality. Depends on Q1. Routes to CW after the first week of real
  volume, not now. *(Void under (d) — there is no pgvector index.)*
- Whether Reddit 403s on Render as it did in the build environment. Only a real deploy
  answers this. Expected to fail; §3.1 says a degraded run is correct behaviour, so the
  check is that the run *completes* with `reddit ✗(403)` in the footer, not that Reddit works.

## Backlog

- **Taste seed is empty.** `swarm/taste/seed.md` is a template, not content. Re-trigger:
  mandatory before the first cron run that anyone intends to read, because §3.5 makes it the
  curator's entire day-1 gate. An AI-written seed was deliberately not supplied.
- **`/healthz` does not check the dashboard token** and is unauthenticated by design. Re-trigger:
  before any real digest content is served from the web service.
- **`RUN_TOKEN_CAP` value is a guess.** §2 requires "a token cap" and names no number; 400000
  is scaffold filler. Re-trigger: first run whose footer reports actual token usage.
