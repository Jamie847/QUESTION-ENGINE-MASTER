# CC accept — WO-012 (opportunity desk)

Live after PR #5 merge `d7c64ed`. `/healthz` commit `d7c64ed`.

## Run 24 (killed)

Operator clicked Run now at 03:17:55 UTC. Render's second WO-012 deploy (`dep-davi3j1mgk9c73bv1kq0`, live 03:18:08) stopped instance `…-rhxph` during fetch. Last swarm line: `checkpoint fetch` at 03:18:13. Cost $0. Lock `daily` stayed on run 24.

Force-started run 25 at 03:29:41 UTC (`POST /api/run?force=true`) so the stale lock did not 409.

## Run 25 (acceptance)

| | |
|---|---|
| Started | 2026-10-02 03:29:41 UTC |
| Finished | 2026-10-02 03:39:32 UTC |
| Duration | 9m 50s |
| Status | **degraded** |
| Cost | **$3.34** |
| Desk | **$1.50 (3 cards)** — $0.51 / $0.49 / $0.49 |
| Commit | `d7c64ed` |
| Saved questions | 0 |
| Cards | 3, all `written_by=model:claude-fable-5`, all snippet-only |

Desk LLM: 6 fable-5 calls, 30,727 in / 13,790 out, **$1.495**. No WO-010 fallback. Rest of run: cross-pollinator $0.89, curator $0.40, scouts $0.40, smiths $0.16.

Degraded for the same dead sources as run 23: federal_register 400, gdelt 429, reliefweb 410, cftc consecutive zeros. EIA / FRED / OpenAlex / Regulations.gov / SAM still need keys. Brave 112 hits, not rate-limited.

Briefs this run: ai 8, business 6, commodities 5, education 8, geopolitics 7, health 8, science 8. Geopolitics is on Today (ranks 1, 4, 5). Commodities produced briefs; no curated top-12 card is tagged commodities (one killed pairing was commodities × geopolitics).

## The three cards

No claim was **contradicted**. Every card has verdicts with source links. The desk still corrected the premises (the point of D2):

1. **Earnings-test rule drains rural hospital hiring pipelines** (rank 3, education × health) — $0.49. Claim 1 **supported**. Claims 2–3 **partly supported**: mental/social-health master's fail at 64.3%, not public-health as a class; no named rural hospital; no outbreak-time link. First cohort data 2027. Shape: data product. Rivals named (Duane Morris, Urban Institute, Chartis).
2. **Medical-credit lenders become obesity treatment underwriters** (rank 2, health × business) — $0.49. All three claims **partly supported**: 503B exclusion is proposed, not final; list price is not what people pay (LillyDirect $299 starter); October hike odds fell below a coin flip. Shape: data product. `none found in 6 searches`.
3. **Export enforcement moves from license tracking to inference audits** (rank 1, ai × geopolitics) — $0.51. Claim 1 **supported** (GPT-Synopsys, 30 Sep 2026). Claims 2–3 **partly supported**: API-as-release is contested, not settled; no BIS reorg or timeline. Shape: software. `none found in 6 searches`. **What's actually true** stored empty — number-rule / empty-model field; later commit writes `not available` instead of a blank.

Fit on every card: `assets profile not written`. No verdicts yet — Operator marks those.

## Cost vs the order

Order estimate: $0.30–0.60 **per run** for the desk. Actual: **$1.50 / run**, **~$0.50 / opportunity**. Two judgment calls × three cards on fable-5 at ~$15/$75 per MTok. Finding from verify, not a surprise. Total run $3.34 vs run 23 $1.74.

Brave: fetch 14 + desk ~18 searches this run (3 × ~6). Free 1,000/month still tight on a daily cadence.

## Follow-up in this commit

- Banner / `/api/status` follow the daily **lock**, not any `runs.status=running` row. Run 24 was painting Today as "scouting" after 25 finished.
- `--close-orphans` on web preDeploy fails running rows that do not hold the lock.
- A field stripped to nothing shows `not available`, not a blank.

## Operator still

Write the assets profile. Mark at least one Pursue / Park / Kill. Add EIA and FRED (and OpenAlex / Regulations / SAM) if you want those sources. Grant the Cursor GitHub App `contents:write` and `pull_requests:write` on QUESTION-ENGINE-MASTER so the next order does not need a pasted token.
