# CC Findings — WO-006 provenance, honesty, dates, and sources

**From:** CC · **Date:** 2026-09-30 · **Branch:** `cursor/wo006-wo007-honesty-sources-84ea`

WO-006 was not merged and not CW-verified when this work started. HEAD and both Render services were `8b7f18fe0549ffa289e1ca181f19dbebda774644`. WO-007 was assigned in the same turn and depends on F1 and F2, so both orders are on this branch. Nothing here was deployed. Do not deploy while a run is in progress. Migration first, then cron, then web.

## Verify (still true at 8b7f18f)

| Finding | Where it was true |
|---|---|
| F1 | `swarm/agents/smiths.py` matched an intersection by exact thesis, else `intersections[0]`. Scout stored model `source_urls` unchecked. |
| F2 | Scout took the top 18 by raw score and printed `score=`. |
| F3 | Each agent used `_llm or _fallback`. A keyed curator failure still archived. |
| F4 | Empty fetch substituted demo signals, including a GLP-1 Wikipedia URL. |
| F5 | Taste notes were a hardcoded lead. No `taste/seed.yaml`. The Operator did not write `data/taste_seed.yaml`. §6 of `docs/CP-RULING-cadence-sources-defects.md` is superseded in place. |
| F6 | Promote set status `curated` and rank 50. |
| F7 | Digest date was `date.today()` UTC. Controls printed a raw timestamp. |
| F8 | Cards had no source line. Today had no "what we read". |
| F9 | Coverage was an unlabelled word. |

## Production measurements

Archived runs that have `agent_calls` and a digest: **15, 16, 18, 19**. Run 17 failed with no digest. Runs 1–14 have no `agent_calls` rows.

**F1 misattribution** (question `intersection_id` equals the first accepted intersection in insertion order):

| Run | Match | Rate |
|---|---|---|
| 15 | 17/22 | 77.3% |
| 16 | 24/24 | 100% |
| 18 | 10/20 | 50% |
| 19 | 17/22 | 77.3% |
| All | 68/88 | 77.3% |

An alphabetical `DISTINCT ON` measure is the wrong one. It reported zero matches.

**F2 signals in the scout prompt.** Scout `input_text` was under the 8000-character store cap, so the stored prompt is the prompt. Smith and curator text is capped at 8000 characters, so "what the smith saw" is not fully measurable.

Runs 15–16 (before Federal Register was in the fetch): one scout call has Brave, one has Wikipedia, Federal Register is absent, Hacker News dominates. Runs 17–19 include Federal Register in some calls and not others. Example, run 18: one call is Brave + Hacker News with no Federal Register; another is Brave + Federal Register + Wikipedia with no Hacker News. Primary documents were missing from a given vertical's prompt. Fetched counts on the later runs: Brave always 8, Hacker News about 29–32, Wikipedia 3–8, Federal Register 43–45. Reddit produced no signal rows.

**F3 silent fallbacks.** The only `ok=false` agent call among runs 15–19 is run 19's curator: Anthropic `BadRequestError` 400, credit balance too low. That run still archived a digest (`degraded`, `cost_usd` 0.755, curator cost 0). Runs 15, 16, and 18 had every agent call `ok=true`.

## What shipped, and the assertion that was red

Shared files carry more than one finding, so the code is not one commit per finding. The tests are.

| Item | Test | Red against unfixed code |
|---|---|---|
| F1 | `test_f1_unknown_label_is_unlinked_and_scout_drops_invented_urls` | Unknown `intersection_ref` became `intersections[0]`. Invented `source_urls` were stored. |
| F2 | `test_f2_round_robin_keeps_a_low_score_source_inside_eighteen_slots` | Global top 18 by score is all Hacker News. The selector is called with limit 18 because the production cap is now 30. |
| F3 | `test_f3_template_card_is_labelled`, `test_f3_keyed_curator_failure_writes_no_digest` | Template cards had no tag. A keyed curator that returns nothing still wrote a digest. |
| F4 | `test_f4_all_sources_dark_fails_without_a_digest` | Empty fetch substituted demo headlines. |
| F5 | `test_f5_stand_in_is_labelled_until_ratings_cross_the_threshold` | Taste page had no stand-in label. Five keeps and five kills with a why did not replace the stand-in. |
| F6 | `test_f6_promote_keeps_status_and_rank` | Promote changed a killed question to curated. |
| F7 | `test_f7_denver_stamp_and_digest_date`, `test_f7_today_page_uses_display_tz` | 2026-09-30 02:30 UTC in `America/Denver` showed Sep 30. The page must contain `Sep 29, 8:30 PM MDT` and digest date `2026-09-29`. |
| F8 | `test_f8_cards_hide_unrecorded_sources_and_show_linked_ones` | A `pre-wo006` card linked a URL. The assertion is scoped to the `<article>`. |
| F9 | `test_f9_coverage_is_labelled_a_model_guess` | The card said `coverage thin` with no model-guess label. |
| Backfill | `test_pre_wo006_backfill_rewrites_blank_provenance_only` | Blank provenance stayed blank. A row already `linked` must stay `linked`. |

`ALLOW_DEMO_SIGNALS` is absent from `render.yaml`. A keyed curator fallback fails the run and writes no digest. Partial scout or smith fallback may still archive, and those cards say `template`.

## Not done here

A keyed run on the deployed service is CW's check after merge. Run 19 already exhausted the Anthropic credit balance. This branch does not spend it.
