# CC findings — WO-014 slice A

Verify: `docs/CC-VERIFY-WO-014.md` (posted before this code).
Live: `/healthz` `8b810a8` · `pgvector_installed: true` · `dedup: lexical`.
PR: https://github.com/Jamie847/QUESTION-ENGINE-MASTER/pull/7

## Built

| Item | Commit / area | Tests |
|---|---|---|
| M1 table + write path | `swarm/memory/store.py`, `swarm/orm.py` `MemoryItemRow` | `test_rebuild_leaves_raw_tables_untouched` |
| One model at a time | `search_memory` filters `embed_model` + `embed_dims` | `test_queries_never_compare_another_model` |
| Optional after archive | `remember_after_archive` | `test_memory_failure_does_not_block_the_digest` |
| M2 desk recall | `swarm/memory/recall.py`, card prompt, opportunity partial | `test_recall_is_dated_excludes_this_run_and_labels_the_prompt` |
| Exact words still win | hybrid score in `search_memory` | `test_exact_rule_number_beats_a_closer_vector` |
| Backfill once | `swarm/memory/backfill.py` marker `wo014_memory_backfill` | `test_backfill_runs_once_and_records_the_marker` |
| M3 search cap | `MEMORY_SEARCHES_PER_DAY` default 200 | `test_search_cap_holds` |
| Real pgvector check | `swarm/db.pgvector_installed` | `tests/test_app.py` (false on sqlite) |

Defaults: `EMBED_MODEL=voyage-4`, `EMBED_DIMS=512`. `VOYAGE_API_KEY` is `sync: false`.

## Live after merge `8b810a8`

| | |
|---|---|
| Postgres | 17.11 · `vector` **0.8.0 installed** |
| DB size | 13 MB → **14 MB** (extension + empty catalog + FTS/HNSW) |
| `memory_items` | **0** |
| Backfill | `BACKFILL_MEMORY embedded=0 skipped=0 ok=0` — `VOYAGE_API_KEY is empty`. Marker **not** recorded. Next deploy retries. |
| Dedup | lexical (unchanged) |

## M0

Official `--embed` number is **blocked**. 11 digest days < 21. No Voyage key on the verify VM or in Render. Lexical gray-zone: **11** pairs. That is not the paraphrase rate.

## Findings (not built around)

1. **WO-012.1 is not live.** Slice A hooks existing WO-012 cards. FR/GDELT/ReliefWeb/CFTC/rivals/pages/`DESK_MODEL` stay a later 012.1 ship. 012.1 WIP is stashed on this workspace as `wo012.1-wip-interrupted-by-wo014`.
2. **No Voyage key in the shared env group.** Backfill and per-run embed are no-ops until the Operator pastes one. Digests still archive. Archive **Search memory** will embed nothing and return empty until the catalog fills.
3. **Opportunity cards have no title column.** Catalog text is question title + what's actually true + picked shape, as live schema required.
4. **Create EXTENSION could not be tested from MCP** (read-only). Deploy created it. `/healthz` now reports the real check.

## Acceptance

Live Today and Opportunities already show **Related from memory** / **nothing related yet** on the three existing cards. Archive **Search memory** is up (`200 searches left today`); `?mq=GLP-1` returns the empty-catalog line because nothing is embedded.

**Run 26** (`8b810a8`) was started from Today after Live, reached **desk**, then was orphaned when findings PR #8 auto-deployed. That was a CC mistake — do not deploy during a run. `POST /api/run?force=true` then hit **MAX_RUNS_PER_DAY=5** (runs 22–26 today). There will not be a finished WO-014 acceptance digest until tomorrow, or until the Operator raises the ceiling / pastes Voyage and Trigger-Runs the cron.

Until the Voyage key is pasted: backfill stays `embedded=0`, Search memory stays empty, new cards stay **nothing related yet**, and a finished run's footer will read **memory not updated**. Paste the key; the next deploy retries backfill (marker not written).

## Operator to-do (unchanged)

Voyage API key into the shared env group. Then a deploy or the next run fills the catalog.
