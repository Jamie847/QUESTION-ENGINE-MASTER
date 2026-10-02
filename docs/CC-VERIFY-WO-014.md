# CC verify — WO-014 (memory layer, slice A)

Posted before any WO-014 code. Measured against live `/healthz` `1597e3c` (PR #6, orphan fix) and acceptance run **25**. No run in progress. MCP `query_render_postgres` is read-only.

**Depends on WO-012.1 live — finding, not a rewrite.** WO-012.1 is verify-only (`e48405b` on this tree). The source/desk fixes are uncommitted and not on GitHub. Slice A (index, desk recall, search) hooks the existing WO-012 cards. It does not need FR slugs, GDELT pacing, ReliefWeb v2, CFTC DESC, rivals/prospects, or `DESK_MODEL`. Those stay a later 012.1 ship. 012.1 WIP is stashed off this work so the two orders do not mix.

---

## Live snapshot (2026-10-02)

| | |
|---|---|
| `/healthz` | `{"ok":true,"database":true,"pgvector_installed":false,"dedup":"lexical","commit":"1597e3c"}` |
| Postgres | 17.11 (Debian 17.11-1.pgdg12+2) · plan `0.1c-256mb` · disk 15 GB · **13 MB** used |
| Extensions installed | `plpgsql` 1.0 only |
| `vector` available | **yes** — `pg_available_extensions.vector` default **0.8.0**, `installed_version` null |
| `CREATE EXTENSION vector` | **not executed here.** MCP wraps every statement in a read-only transaction (`SQLSTATE 25006`). Deploy must run it. |
| Latest digest date | 2026-10-02 · 14 digest rows · **11 unique digest days** |
| Runs | 25 |

---

## 1. pgvector on the live database

Postgres 17.11 already ships the `vector` extension (0.8.0). It is not created. `/healthz` has hardcoded `pgvector_installed: false` since the 2026-09-01 ruling, on purpose, so a voided §1.3 check would fail a healthy system.

**After this order `/healthz` will report `pgvector_installed: true` only when the extension is actually installed** — `SELECT 1 FROM pg_extension WHERE extname = 'vector'`. That is a real check, not a flipped constant. Local sqlite and a Postgres that has not run the migration still report `false`. **`dedup` stays `lexical`.** A session that treats `pgvector_installed: true` as "dedup is now semantic" is still reading a voided check.

`tests/test_app.py` currently asserts `pgvector_installed is False`. That assertion must follow the real check (false on the sqlite test DB).

---

## 2. Storage headroom — recommend **512** dimensions

| | |
|---|---|
| Now | 13 MB of 15 GB disk · 256 MB RAM plan |
| Backfill rows | 936 if curated questions only; 1,156 if every question including killed/duplicate |
| Vectors at 512-d | 1,156 × 512 × 4 ≈ **2.3 MB** + HNSW/IVFFlat overhead → a few MB |
| Vectors at 1024-d | ≈ 2× that |
| Year (365 × ~85 items/run: ~18 curated q + ~50 briefs + ~12 intersections + ~5 cards) | ~31,000 items |
| Year at 512-d | ~31k × 512 × 4 ≈ **63 MB** raw + index ~100–150 MB |
| Year at 1024-d | ~126 MB raw + index ~200–300 MB |

Disk is not the constraint. **256 MB RAM is.** A 512-d index for a year of runs fits; 1024-d starts to crowd the same instance as the working set and the rest of the app. Voyage-4 supports 256 / 512 / **1024 (default)** / 2048. **`EMBED_DIMS=512`.** Drop-and-rebuild stays cheap if a later order wants 1024.

Text stays in the existing tables. `memory_items` is a card catalog. `--rebuild-memory` can drop it without touching raw rows.

---

## 3. Voyage — `voyage-4`, not the script's `voyage-3-lite`

Confirmed against current Voyage docs (`docs.voyageai.com/docs/embeddings`, `/pricing`). **Not confirmed against the live API** — this VM has no `VOYAGE_API_KEY`. Official M0 `--embed` is the same block.

| | |
|---|---|
| Current general-purpose | **`voyage-4`** (balance). Family also has `voyage-4-lite` and `voyage-4-large`. All 4-series vectors are compatible with each other. |
| Context | 32,000 tokens / text |
| Output dims | 256, 512, **1024 default**, 2048 via `output_dimension` |
| Batch | ≤1,000 texts; ≤320k tokens / request on `voyage-4` |
| Free allowance | **200 million tokens / account** on the voyage-4 family |
| After free | `$0.06 / million tokens` (`voyage-4`) |
| Free-trial rate | 3 RPM / 10k TPM until a payment method is added (MongoDB/Voyage usage-tier docs) |
| Endpoint | `https://api.voyageai.com/v1/embeddings` · `input_type` `document` / `query` |

**Default: `EMBED_MODEL=voyage-4`, `EMBED_DIMS=512`.** `VOYAGE_API_KEY` is `sync: false` on the shared env group. The Operator pastes it. The measure script still hardcodes `voyage-3-lite`; the build will read `EMBED_MODEL`.

Voyage is the only new vendor. No second database.

---

## 4. Volume and backfill cost

Text that this order embeds, by kind (live counts):

| Kind | Rows | Characters of embed text | ≈ tokens (chars/4) |
|---|---:|---:|---:|
| Question (curated; title + text) | 212 | 51,911 | 13,000 |
| Brief (headline + what is happening) | 441 | 121,605 | 30,400 |
| Intersection (thesis) | 280 | 83,685 | 20,900 |
| Opportunity card (what's actually true + picked shape; cards have no title column — title comes from the question) | 3 | 1,985 | 500 |
| Verdict | 0 | 0 | 0 |
| **Slice A backfill (curated + briefs + intersections + cards)** | **936** | **259,186** | **~65k** |
| All questions including killed/duplicate | 432 | 97,354 | 24,300 |
| All-questions total | 1,156 | 304,629 | **~76k** |

Build will embed **curated questions** (surfaced, not killed/duplicate), every brief, every intersection thesis, completed opportunity cards, and verdicts. Killed/duplicate questions stay in their tables and out of the catalog unless a later order asks.

**Backfill cost ≈ $0** on the 200M free tokens (76k is 0.04% of the allowance; list price would be < $0.01). One batched call per chunk, once, as a deploy step, with a `deploy_markers` row (WO-011 lesson). Later deploys print skipped.

**Per-run embed cost after that:** a typical run (18 q + 50 briefs + 12 intersections + 5 cards) is ~20–40k characters ≈ 5–10k tokens ≈ **$0.0003–$0.0006** after the free allowance, a fraction of a cent before it. Search is one short query embed per Archive search, capped at `MEMORY_SEARCHES_PER_DAY=200`.

---

## 5. M0 paraphrase measurement — official number blocked

```
digest_days=11  curated_questions=212  today=2026-10-02
not_yet: need 21 keyed digest days for the official leak count
embed_pass=blocked: VOYAGE_API_KEY is empty
```

Unique digest dates on file (11): 2026-09-01, 09-02, 09-03, 09-07, 09-08, 09-09, 09-10, 09-28, 09-30, 10-01, 10-02. The script's `--min-days 21` is not met. This VM has neither `VOYAGE_API_KEY` nor `DATABASE_URL`, so `--embed` cannot hit Voyage from here.

**Gray-zone (still lexical — not the paraphrase rate).** Recomputed from a live SQL export of the 212 curated questions through `swarm.dedup.similarity`, floor 0.28, threshold 0.64, shared verticals, adjacent *curated* days (same rule as `scripts/measure_paraphrase_leak.py`):

**`gray_zone_pairs=11`**

Highest overlaps are template-shaped AI questions (Fable / Atlas / "adjacent market nobody is staffing" / Ask HN hiring), 0.29–0.44. That is token overlap the current gate already almost catches. It is **not** a cosine leak rate.

The 2026-09-01 ruling asked for the embed number. It informs a later dedup change; it does not decide one in this order. **Dedup stays lexical.** Operator pastes a Voyage key → CP can re-run `--embed` on the live DB. Until then the official M0 number is **blocked**, not zero.

---

## 6. What `/healthz` will say, and what will not change

| Field | Now | After WO-014 |
|---|---|---|
| `pgvector_installed` | hardcoded `false` | **true** on live Postgres after `CREATE EXTENSION vector`; false on sqlite / before the migration |
| `dedup` | `lexical` | **`lexical`** |
| `commit` | `1597e3c` | the merged WO-014 SHA |

Near-miss sampler, kill-floor inverse, and taste copy stay WO-009's rule. Memory never states current fact: every recalled item carries its date; the desk prompt labels them as past and re-checks claims (WO-012 D2). No MongoDB. Raw text stays canonical.

Ruling request + spec §3.4 get a dated supersede line: *a vector index was added for memory (WO-014); dedup remains lexical pending the paraphrase measurement and calibration.* Old text stays.

---

## Acceptance searches will have something to hit

Live rows already mention the two CP probes:

| Query | Questions | Briefs | Intersections |
|---|---:|---:|---:|
| GLP-1 | 8 | 4 | 6 |
| earnings | 17 | 5 | (not counted) |

Three opportunity cards, zero verdicts. First-run recall on cards will often read **nothing related yet** until more cards exist. Search across briefs/questions will not be empty.

---

## Build plan (after this note)

1. Seven fixture tests, red, no live Voyage.
2. `memory_items` + Voyage write path after archive (optional; footer *memory not updated* on failure).
3. Backfill once (`--backfill-memory`) + `--rebuild-memory`; marker `wo014_memory_backfill`.
4. Desk *Related from memory* (up to 3 dated items) and the three past-item instructions in the card prompt.
5. Archive **Search memory** + kind/vertical filters + newest-first toggle + `MEMORY_SEARCHES_PER_DAY=200`.
6. Real `pgvector_installed` check. `VOYAGE_API_KEY` sync:false. `EMBED_MODEL` / `EMBED_DIMS` from env.

Commit convention `wo014(<area>): …`. Deploy migration → cron → web, never during a run.
