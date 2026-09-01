# CC Build Prompt — Question Engine Phase 1 (thin swarm)

> ## VOID — 2026-09-01. DO NOT BUILD FROM THIS DOCUMENT.
>
> **A Phase 1 implementation already exists.** This work order was written on the premise
> that it did not, and every instruction below is therefore addressed to a build that has
> already happened. Following it would produce a second, competing copy — stubs replacing
> working code, a deliberately failing cron replacing a real one, and a `/healthz`-only
> dashboard replacing a real one.
>
> **Superseding facts** (verified against this repo 2026-09-01):
>
> - `Signal`, the curator output contract (`Question` + `status`/`rank`/`kill_reason`) and the
>   digest contract (`DigestDoc`) all exist. `sources/base.py` is a real interface, not the
>   docstring §0 below describes.
> - **Dedup is lexical**, not vector — content-token similarity, no `embedding` field, no
>   pgvector. §1.3 below tells you to verify `pgvector_installed: true`; the live system
>   reports it **false on purpose**. That check is inverted and would fail a healthy system.
> - The Blueprint corrections in §0 were adopted; auth is `DASHBOARD_TOKEN` with `ACCESS_TOKEN`
>   also accepted.
>
> **What survives, and only this:** §4's test list and §5's not-in-scope boundary are about
> failure classes rather than about what to write, so they remain worth reading as a checklist
> against the code that exists. Everything else is void.
>
> Kept rather than deleted because it is the record of what was open before the rulings, and
> because the inverted pgvector check is worth being able to point at.
>
> ---


**From:** CW (Cowork), scaffold handoff · **Date:** 2026-09-01
**Branch:** new branch off `main`, PR to `main`
**Governance:** CP rules → CC builds → CW verifies against the deployed service. No merge
without CW. This document is a *scaffold handoff*, not a CP ruling — where it and CP
disagree, CP wins.

**Authority:** tech spec v1.1 (project doc `docs/question-engine-tech-spec-v1.1.md`) is the design.
This file does not restate it. Read §3.0, §3.1–3.5, §3.8, §4, §5, §6, §7 before starting.
Where this file and the spec disagree, **stop and surface it** — every known disagreement is
already listed in `docs/OPEN-QUESTIONS-for-CP.md` and a new one means something drifted.

---

## 0. Context — what exists and what does not

The repo is scaffolded, not built. What is real:

| Path | State |
|---|---|
| `render.yaml` | Real. Corrects three defects in spec §2 — see OPEN-QUESTIONS Q7. |
| `swarm/models.py` | `Brief` / `Intersection` / `Question` transcribed verbatim from spec. |
| `swarm/config/*.yaml` | Real structure. **Query strings and subreddits are placeholders.** |
| `dashboard/main.py` | `/healthz` only. None of spec §6's five pages exist. |
| `swarm/run_daily.py` | Stub. Exits non-zero on purpose (see §2 below). |
| `swarm/sources/base.py` | Docstring only — the `Signal` contract is undefined. |
| `swarm/taste/seed.md` | **Empty template. Jamie fills this in, not you, not CP.** |
| `swarm/agents/`, `swarm/prompts/`, `evals/`, `tests/` | Empty. |

## 1. Verify BEFORE building — blocking

**First action: post the results of these four checks before writing any code.**

1. **Q1 is answered.** `docs/OPEN-QUESTIONS-for-CP.md` Q1 is a blocking design gap: spec §3.4
   puts semantic dedup in Phase 1, and no embeddings provider exists in the specified stack.
   **Do not pick one yourself.** If CP has not ruled, build stages 1–3 and 5–8 and leave
   stage 4 unimplemented behind an explicit `NotImplementedError` — not a pass-through, which
   would make "dedup ran and found nothing" indistinguishable from "dedup does not exist."
2. **Blueprint applies and both services are green.** `/healthz` returns `ok: true` on the
   web service, AND `python -m swarm.run_daily --healthcheck` prints `CRON_HEALTHCHECK_PASS`
   in the cron service's log. **Both.** They are separate Render services with separately
   wired env; the web service proves nothing about the cron's `DATABASE_URL`.
3. **pgvector is actually installed**, i.e. `/healthz` reports `pgvector_installed: true`
   after your first migration runs. The Blueprint does not install it — `CREATE EXTENSION IF
   NOT EXISTS vector;` belongs in migration 001. A green Blueprint apply is not evidence.
   **INVERTED. Do not use this check.** Healthy Phase 1 reports `pgvector_installed: false`.
4. **Confirm `generateValue` was accepted** for `DASHBOARD_TOKEN` inside the env group
   (OPEN-QUESTIONS Q5). If Render rejected it, the fallback is `sync: false`, and that is a
   change to `render.yaml`, not a thing to work around in code.

If any check surfaces a design problem, STOP and surface it. Do not work around it.

## 2. Scope decisions already made — build to these

- **A stub cron exits non-zero.** `run_daily.py` fails loudly until the swarm exists, because
  a green cron run reads as evidence the pipeline works. Preserve that property: no stage may
  be stubbed with a silent success. Spec §7's "fail loud, never silent-fallback" applies to
  your own scaffolding, not just to config.
- **Degraded ≠ failed, and the distinction must be visible.** Spec §3.1: a scout that loses
  Reddit still publishes. But the run footer (§5) must name every degraded source. Reddit
  403ing on Render is the *expected* outcome, and the test is that the run completes with
  `reddit ✗(403)` in the footer — not that Reddit works.
- **One judgment model.** Spec §3.0: `JUDGMENT_MODEL` (`claude-fable-5`) covers both the
  cross-pollinator and the curator. Scouts and smiths use `ANTHROPIC_MODEL`
  (`claude-sonnet-5`). Read both from env — never hardcode a model string. A hardcoded
  parameter leaves no record that it changed.
- **Config-driven phases.** `verticals.yaml` and `lenses.yaml` carry a `phase` field. Phase 2
  is a config change, not a code change (spec §3.0). Build the loader to filter on it now.
- **Coverage is a three-valued score, never a boolean**, and never promotes a question past
  the curator on its own (spec §3.2). Persist `coverage_queries` and `coverage_snippets` so a
  false positive can be audited later.
- **Checkpoint every stage to Postgres** (spec §3, §7). `--resume` and `--stage curator` have
  to work from the DB, which means a stage's output is written before the next stage starts.

## 3. What to build

Spec §10 Phase 1, in the pipeline order of §3. Milestone: **a digest Jamie wants to open on
day 3.**

- Schema + migrations for §7's table list. `agent_calls` carries stage, model, prompt version,
  tokens, cost, latency, and input/output JSON — that row is what makes a bad question
  traceable back through smith → intersection → scout brief.
- The five Tier-1 adapters (§4), each with its own timeout and health status. Resolve the
  `Signal` contract first (OPEN-QUESTIONS Q2) — one file per source after that.
- 3 scouts, cross-pollinator with coverage scoring **and the rejection log**, 3 smiths,
  curator reading `taste/seed.md`, archivist writing the digest row.
- Run lock (a `runs` row with `status=running`) so `POST /run` cannot overlap the cron.
- Hard budget: exceeding `RUN_BUDGET_USD` or `RUN_TOKEN_CAP` **skips optional stages, it does
  not fail the run** (spec §2), and the footer names what was skipped.
- `GET /digests/{date}.md` and email delivery of the Top 5.

**Single-source anything two paths share.** The cost accumulator, the model client, and the
budget check are each called from the cron and the web `POST /run`; import them, do not
reimplement.

## 4. Tests

For every test, state **what it does against the unfixed code and which assertion goes red.**
A test that fails for a reason unrelated to the defect certifies nothing.

Required, because these are the failure classes this design invites:

- **A degraded run still produces a digest.** Force the Reddit adapter to 403; assert a digest
  row is written AND the footer names `reddit`. Against code that treats an adapter failure as
  fatal, the digest-row assertion goes red — put it *first*, ahead of any footer-shape check,
  or a shape assertion fails first and the red mark certifies nothing.
- **The budget cap skips rather than fails.** Set `RUN_BUDGET_USD` below one stage's cost;
  assert the run exits 0, the digest exists, and `stages_skipped` is non-empty.
- **The run lock actually blocks.** Two concurrent `run_daily` invocations; assert exactly one
  acquires. This must run against **real Postgres**, not a fake session — a fake session never
  autobegins a transaction, so the natural test for a lock bug passes against the broken code.
- **Coverage cannot promote alone.** A question whose only strength is `coverage: none` does
  not survive the curator.
- **Model strings come from env.** Assert no `claude-` literal appears outside
  `render.yaml`, config, and tests.

## 5. NOT in scope

Ideator (§3.6), resurrection (§3.7), the weekly taste profiler (§3.5), all four non-`/healthz`
dashboard pages (§6), the eval harness (§8 — explicitly built *from* real output, not before
it), Tier-2 sources (§4), and everything in §11. Phase 1 is stages 1–5 and 8, plus the digest
endpoint and email.

Do not fill in `swarm/taste/seed.md`. It is the Operator's, and an AI-written taste seed would
train the curator on an invented taste while looking like it worked.

## 6. Deploy order + commit convention

Migration → cron producer → web consumer. Migrations name the target Render database and the
reference is re-confirmed against the live project list at apply time. No deploys over a live
session without Jamie's greenlight. Pin `requirements.txt` to exact versions after the first
successful local run and commit the result in its own commit.

Commit convention: `phase1(<area>): <what changed>`, e.g. `phase1(sources): brave adapter with
10s timeout and health status`.

---

## What this handoff does NOT establish

- **Nothing here has been run.** No test has executed, no Blueprint has been applied, no
  adapter has fetched anything. Every claim above is about two documents and two vendor
  references. Treat `render.yaml` as unapplied until §1.2 says otherwise.
- **The config placeholders are not tuned.** The Brave query strings and subreddit lists in
  `verticals.yaml` were written to give the loader something to load. Expect to rewrite them
  after the first real run.
- **`/healthz` green is not proof the swarm works.** It proves the database is reachable,
  pgvector is present, and the expected env vars are non-empty. That is all it proves, and it
  will stay green through every Phase-1 bug you write.
