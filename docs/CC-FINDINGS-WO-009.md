# CC findings — WO-009

Built on this tree after Verify. WO-008 is not here; the U2 smith-prompt line landed on the current smiths. Nothing else from WO-008 was invented.

## Per item

| Item | Commit | Tests | Assertion that was red on the old code |
|---|---|---|---|
| Verify | `wo009(verify)` | — | — |
| U1 Run now | `wo009(u1)` | `test_wo009_u1.py` | Today has no `data-run-btn` / no Run control |
| U2 titles | `wo009(u2)` | `test_wo009_u2.py` | kept questions have no `title`; card has no `.q-title`; smith.md has no 45-word / quietly line |
| U3 sources | `wo009(u3)` | `test_wo009_u3.py` | From: is the scout headline; rank 3 labels wikipedia next to commentary hosts |
| U4 bank | `wo009(u4)` | `test_wo009_u4.py` | All concatenates per-vertical lists, so a two-vertical question appears twice |
| U5 near-miss | `wo009(u5)` | `test_wo009_u5.py` | sampler ranks by word overlap and always returns three |
| U6 order | `wo009(u6)` | `test_wo009_u6.py` | steering / model-written / coverage / dedup disclosure sit with debug; What we read is always expanded |

Full suite: 108 passed.

## Findings (not built around)

1. **WO-008 is absent.** Empty-lens work is not in this tree. U2's one smith-prompt line is on current `smith.md`. Model-written counts per lens use `written_by` already stored by WO-006. They do not hide an empty lens.

2. **Federal Register routing is unchanged.** U3 cites a primary record when that record is among the run's signals. It does not add Education keywords, does not search FR by agency, and cannot invent the earnings-accountability rule if fetch never stored it. Rank 3 on run 20 would still lack an FR URL until a later source order puts that document in the mix.

3. **Fallback titles are heuristic.** The curator LLM is asked for a ≤10-word title. The no-key path clips the question. Old rows stay untitled. Do not backfill.

4. **This environment cannot push GitHub or deploy Render.** Production is still the Operator's merge. Do not `POST /api/run` on the live service from here. Acceptance (one run from Today's new button) waits for the Operator to ship these commits to the deploy repo.

5. **`DISPLAY_TZ` is still UTC** unless the Operator sets `America/Denver` or `Asia/Manila` on Render. OpenAlex / Regulations.gov / SAM.gov keys are still the Operator's to-do.
