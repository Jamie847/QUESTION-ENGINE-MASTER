# CC verify — WO-010 (run 21)

Posted before any WO-010 code.

## 1. What is deployed

| Service | Live commit | Message |
|---|---|---|
| Web `question-engine-dashboard` | `cf876d1a` | Merge PR #2: WO-008 empty lenses |
| Cron `question-engine-swarm` | `cf876d1a` | same |

- **WO-008 is live** on both web and cron (deployed 2026-10-01 17:44 UTC, before run 21 at 17:46).
- **WO-009 is not in that commit.** It is on this worktree's `main` (`b1b056f` and parents `wo009(u1)`–`wo009(u6)`). It was never merged to `Jamie847/QUESTION-ENGINE-MASTER`, so Render never deployed it. There is no separate GitHub branch for it on the deploy repo. The earlier Today page check ran against a local build.

## 2. What was refused

Run 21 `agent_calls` id 56:

- **Agent:** `cross_pollinator`
- **Model:** `claude-fable-5`
- **Stop:** `refusal` (`no structured payload from claude-fable-5 (stop_reason=refusal)`)
- **Tokens:** 6588 in / 502 out. 9 of 10 calls ok. Curator (Fable) succeeded.

Headlines in that input include the usual FTC / Fed / FDA briefs **and**:

- *Anthropic's AI biolab claims a CRISPR-comparable discovery* (health)
- *Anthropic's AI-run biolab claims a CRISPR-caliber discovery* (science)

CP's hypothesis is supported: the refused pairing call was looking at an AI-run biology lab claiming a CRISPR-level discovery. The same run's briefs also include a Nature retraction of a CCR5/HIV-resistance paper and an Anthropic Fields-Medal-caliber math claim. No prompt body is pasted here.

## 3. Why half the questions are unlinked

18 questions stored for run 21 (14 curated, 4 killed). Today’s “10 of 19” is a display count; the table has 18 rows.

| Smith output | Count |
|---|---|
| No `brief_refs` | **0** — every question in the three smith payloads lists at least one B-label |
| Refs that failed to map | **12** stored `provenance=unlinked` with empty `brief_ids` |
| Built on template intersections | **6** have an `intersection_id`; every intersection on run 21 is `written_by=template` |

Cause, two stacked defects:

1. Cross-pollinator refused → this tree’s `_llm or _fallback` wrote template pairings (*share a compute/capital stake…*, coverage `unknown`, no template tag). Smiths then cited I2/I3/I4. Those six questions inherited the template pairing’s brief ids and show as linked.
2. Smiths only label `briefs[:16]`. Run 21 had **37** briefs. The payloads cite B17, B20, B22, B23, B28, which do not exist. Questions with `intersection_ref=none` and only those labels (or a mix that resolved to nothing) stored unlinked. That is the empty “sources not recorded” pile.

Fixing the 16-cap and refusing template pairings on a keyed run addresses both. A question whose refs still fail to map stays unlinked (WO-006 F1).
