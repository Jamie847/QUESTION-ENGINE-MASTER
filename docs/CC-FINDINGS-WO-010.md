# CC findings — WO-010

Built on this tree after Verify (`docs/CC-VERIFY-WO-010.md`). WO-009 is already on this `main` (`wo009(u1)`–`wo009(u6)`). It is not on the deploy repo and not live.

## Verify (held, posted before the build)

| Item | Result |
|---|---|
| Live web + cron | `cf876d1a` — Merge PR #2, WO-008. Deployed 2026-10-01 17:44 UTC. |
| WO-009 | On this `main` only (`b1b056f` and parents). Not in `cf876d1a`. |
| Run 21 refusal | `agent_calls` id 56, `cross_pollinator`, `claude-fable-5`, `stop_reason=refusal`. Input includes the AI biolab / CRISPR headlines. CP's hypothesis is supported. |
| Unlinked counts | 0 smith outputs lacked `brief_refs`. 12 stored `unlinked` (labels past B16). 6 built on template intersections. |

## Per item

| Item | Commit | Tests | Assertion that was red on the old code |
|---|---|---|---|
| Verify | `wo010(verify)` | — | — |
| R1 refusal retry | `wo010(r1)` | `test_wo010_refusal_recovers`, `test_wo010_prompt_unchanged_on_retry` | Stage falls back to templates; no second `agent_calls` row; retry prompt is missing or trimmed |
| R2 no keyed templates | `wo010(r2)` | `test_wo010_double_refusal_skips_pairings`, `test_wo010_keyed_empty_is_not_template` | Template intersections (`share a compute stake…`) appear after a keyed empty pairing call |
| R3 source links | `wo010(r3)` / smiths in `wo010(r2)` | `test_wo010_questions_cite_briefs_with_no_intersections` | `briefs[:16]` so B20 is unlinked; header has no `Sources linked: N of M` |
| R4 plain failures | `wo010(r4)` | `test_wo010_plain_failure_line` | Today says *A model call failed. See service logs.* |
| R5 live commit | `wo010(r5)` | `test_wo010_commit_shown` | `/healthz` and the footer have no commit |
| R6 ship WO-009 | already on this `main` | WO-009 suite | Acceptance is the **live** page after the Operator pushes GitHub and deploys. Not claimed here. |
| Curator fail-closed | held from WO-006 F3 | `test_wo010_curator_double_refusal_writes_no_digest` | A heuristic digest archives after both models refuse |

Full suite: 116 passed.

`FALLBACK_MODEL` is read from the environment (`claude-opus-5-5` in `render.yaml`). It is not hardcoded in the retry path.

## Deploy and acceptance

This environment cannot push GitHub or deploy Render. Production is still `cf876d1a` (WO-008) until the Operator copies this `main` to the deploy repo.

**Do not `POST /api/run` on the live service from here.** Acceptance (one run from Today's Run button) waits for: GitHub has these commits → migrate → cron → web, never during a run → Operator clicks Run on the live Today page.

When that run lands, CP reads the live page directly. Pass means: footer commit matches the deploy, every lens has at least five model-written questions, intersections are model-written or the page says why not, sources linked ≥ 80% or the warning line, and WO-009's Run button / titles / real From: / Behind the scenes / no "quietly."

## Findings (not built around)

1. **`written_by` / `curated_by` still name the primary model after a recovered retry.** A pairing recovered on Opus is stored as `model:claude-fable-5`. The footer and `agent_calls` tell the truth. Changing the writer label would hide which model was asked first. Report, do not re-label.

2. **Exceptions are not retried.** Only `stop_reason=refusal` on a completed message retries. A 400 / timeout / rate limit stays a single attempt and a plain category line.

3. **Keyed runs no longer synthesize template rejects** when the model returns only accepted pairings. Rejects stay empty rather than grow a `written_by=template` card. Keyless runs still synthesize them.

4. **Re-trigger is unchanged.** If judgment is refused on more than 1 of 5 runs over two weeks, the Operator chooses the primary. This pass does not change `JUDGMENT_MODEL`.

5. **Render injects `RENDER_GIT_COMMIT`.** `/healthz` `commit` is the short SHA. A local process without that env shows no footer stamp — that is expected, not a missing deploy.

6. **`DISPLAY_TZ` is still UTC** unless the Operator sets it. OpenAlex / Regulations.gov / SAM.gov keys are still the Operator's to-do.
