# CC Findings — WO-007 sources

**From:** CC · **Date:** 2026-09-30 · **Depends on:** WO-006 F1 (labelled briefs) and F2 (round-robin), on the same branch.

WO-006 was not merged or CW-verified. Both orders were assigned together, so this branch contains both. No production deploy from this branch.

## Verify

**Brave.** Runs 12–19, all 8 Brave signals have `raw.query = "artificial intelligence breakthrough"`. Health, Business, and the second AI query got nothing. The free-tier pattern is 1 request/second. Docs for a newer Search plan say 50 qps; production does not match that. Pacing is `BRAVE_MIN_INTERVAL_S` default 1.1. A 429 is retried once. Any 429 that remains is named on source health.

**Live samples, 2026-09-30, no keys invented.**

| Source | Result |
|---|---|
| Hugging Face daily papers | HTTP 200. Paper id, title, summary, upvotes. |
| arXiv Atom | HTTP 200. One request per 3 seconds (published ToU). |
| OpenAlex | HTTP 200 with `has_abstract:true`. Inverted index rebuilds. A row can have a null abstract; the parser allows that. |
| Regulations.gov | HTTP 403 `API_KEY_MISSING` without a key. No sample of documents. |
| SAM.gov `opportunities/v2/search` | HTTP 404 empty body without a key. No sample of notices. |
| USAspending awards | HTTP 200 with award type codes. This is awards, not opportunities. Not built. |

**SAM limit.** A non-federal public key is 10 requests / 24 hours. Five verticals × one call = 5, which fits one run and does not fit a second run the same day (`MAX_RUNS_PER_DAY` is 5). SAM stays. USAspending was not substituted.

**Cost.** Successful keyed digests: run 15 `$1.021`, run 16 `$1.053`, run 18 `$1.068`. Run 19 `$0.755` because the curator failed. Scout input on Federal Register-era runs was about 2,400 tokens per call, about `$0.11` for three scouts.

Projection after snippets (800 characters × up to 30 signals) and five verticals: scout about `$0.73`, smiths about `$0.26`, cross-pollinator about `$0.70`, curator unchanged about `$0.35`. Total about `$2.04`. That is under the `$3.00` flag and under `RUN_BUDGET_USD` `5.00`. It is an estimate. Smith and cross-pollinator prompts stored in `agent_calls` are capped at 8,000 characters, so the old smith token count is not the full prompt.

## What shipped, and the assertion that was red

| Item | Test | Red against unfixed code |
|---|---|---|
| S2 Reddit off | `test_s2_reddit_is_off_and_not_fetched` | Reddit was still fetched. Consecutive `off` rows could latch `dead`. |
| S2 Brave 429 | `test_s2_brave_names_the_query_that_stayed_429` | A 429 was skipped with `continue` and the query was not named. |
| S2 needs key | `test_s2_openalex_missing_key_is_needs_key_and_never_dead` | A missing key looked like a failed fetch and could go dead. |
| S2 freshness | `test_s2_freshness_window_clamps_to_one_and_seven_days` | 10 days since the last archive still looked back 1 day. Two hours still looked back more than 1. |
| S3 routing | `test_s3_targeted_signal_reaches_the_science_scout_without_a_keyword` | A paper with no keyword never reached the Science scout. |
| S3 parsers | `test_s3_adapters_parse_fixtures_with_snippet_and_source_id` | Empty snippet or a missing arXiv id, DOI, docket id, or notice id. OpenAlex abstract must equal `Quantum-inspired Machine Learning (QiML) is a burgeoning field`. |
| S4 verticals | `test_s4_science_and_education_are_phase_one_with_draft_queries` | Loader returned only ai, health, and business. |
| S1 snippets | `test_s1_scout_block_includes_a_trimmed_snippet` | Scout line had no snippet. Stored snippets were clipped at 400. |

Reddit stays in `swarm/sources/reddit.py` with `enabled: false` and the Operator comment. `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` are gone from `render.yaml`. `OPENALEX_API_KEY`, `REGULATIONS_GOV_API_KEY`, and `SAM_GOV_API_KEY` are in the shared env group with `sync: false`. Until a key is present the source reports `needs key` and the run continues.

## Draft queries (tune after the first run)

Brave and Federal Register still use each vertical's `search_queries`. New verticals:

- Science: `quantum computing experiment`, `materials science breakthrough`, `climate observation satellite`, `fusion energy experiment`. arXiv: `quant-ph`, `astro-ph.CO`, `cond-mat.mtrl-sci`, `physics.gen-ph`, `q-bio.NC`.
- Education: `student loan regulation`, `teacher shortage`, `higher education enrollment`, `education technology classroom`. arXiv: `cs.CY`. `journal_feeds` is empty.
- AI arXiv: `cs.AI`, `cs.LG`, `cs.CL`. Health arXiv `q-bio.QM` and `q-bio.BM` were not named in the order; they are drafts.
- Business arXiv: `econ.GN`, `q-fin.GN`, `q-fin.EC`.
- Journal feeds that returned HTTP 200: Nature, Science, and Cell → science. NEJM, JAMA, and The Lancet → health.
- SAM keywords / NAICS: AI `artificial intelligence` / `541512`, health `hospital` / `622110`, business `financial services` / `522110`, science `research laboratory` / `541715`, education `education` / `611110`.

Five scouts run. Smith and curator call counts do not change with the vertical count beyond the briefs those scouts produce. The curator is still one call.

## Local unkeyed run during the suite

The existing swarm test, with no API keys in the environment, archived a degraded digest. Source health from that run:

| Source | Result |
|---|---|
| hacker_news | 33 |
| wikipedia | 10 |
| federal_register | 14 |
| huggingface | 15 |
| reddit | off, not fetched |
| brave, openalex, regulations_gov, sam_gov | needs key |
| arxiv | `TimeoutError` at the 90s adapter cap (five category queries, 3s apart) |
| journals | one feed, JAMA, returned HTTP 406 because `Accept` did not include `text/xml` |

The journal adapter now sends `text/xml` and keeps the feeds that succeed when one fails. `test_s3_one_journal_feed_failure_keeps_the_others` is red against the old `raise_for_status` that dropped every journal.

A second unkeyed run after that change fetched arXiv **50** and journals **90**, with Reddit still off and the four keyed sources still `needs key`. The run was degraded only because `ANTHROPIC_API_KEY` was unset, which is the existing heuristic-writer path.

## Findings, not workarounds

1. SAM's 10 requests / 24 hours covers one five-vertical run and not a second run the same day. SAM was implemented. USAspending was not.
2. Brave's published Search plan is 50 qps. Production behavior on runs 12–19 is 1 request/second. Pacing uses 1.1 seconds.
3. Regulations.gov and SAM.gov could not be live-sampled without keys.
4. A keyed run after this build, with signals fetched and read per source, was not executed. Run 19 is out of Anthropic credit, and the new keys are not in this environment.

## Operator to-do

Put an OpenAlex key, an api.data.gov key, and a SAM.gov public key into the Render shared env group `question-engine-shared`. Do not re-enable Reddit without asking. `DISPLAY_TZ` is `UTC` until the Operator sets an IANA zone.
