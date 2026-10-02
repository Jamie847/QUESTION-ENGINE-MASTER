# CC verify — WO-012 (opportunity desk)

Posted before any WO-012 code. Measured against live production after PR #4 merge (`2d66594`, `/healthz` commit `2d66594`) and acceptance run **23**.

## Run 23 (WO-011 live, before this order)

| | |
|---|---|
| Started | 2026-10-02 02:59:15 UTC |
| Finished | 2026-10-02 03:05:36 UTC |
| Status | **degraded** |
| Cost | **$1.74** (run 22 was $1.57) |
| Commit | `2d66594f423efdea69a2df3fd095e10e1821aadf` |
| Questions | 18 curated, all `provenance=linked`, all `written_by=model:claude-sonnet-5` |
| Briefs | ai 7, business 6, commodities 6, education 7, geopolitics 8, science 8 |
| Saved | 0 (`promoted` is false on every row) |
| Repair | `deploy_markers.wo011_link_repair` at 02:58:26 UTC: relinked=52, unverified=108, unlinked=82, skipped=0. Later boots do not rewrite. |

Degraded because sources failed, not because writers failed (`writer_ok_calls=12`):

| Source | Result |
|---|---|
| federal_register | HTTP 400 on agency-filtered RULE+PRORULE query (e.g. BIS / Commerce / NIST / FCC + `significant=1`) |
| gdelt | HTTP 429 |
| reliefweb | HTTP 410 on `api.reliefweb.int/v1/reports` |
| eia, fred, openalex, regulations_gov, sam_gov | `needs key` |
| cftc | ok, 0 rows |
| brave | 112 results, no 429 |

Geopolitics and Commodities **do** show on Today (ranks 2, 3, 5–8, 11). They arrived through Brave / other live sources, not GDELT / ReliefWeb / EIA / FRED.

Judgment cost on run 23: cross-pollinator $0.735 (8,715 / 8,062 tokens), curator $0.411 (4,099 / 4,664). Volume scouts+smiths $0.60. Implied fable-5 ≈ $15 / $75 per MTok; sonnet-5 ≈ $3 / $15 per MTok.

K2 held: one accepted pairing was rejected as `Same vertical — AI-safety discourse × AI policy discourse is a single field's internal conversation`.

---

## 1. WO-011 source fix is live

**Yes, K1 is live.** `/healthz` returns `commit: 2d66594`. Dashboard boot does not repair. Cards now print `brief.sources` only (`from_cites` no longer remaps against the run-wide pool).

Run 23 top cards were checked against stored brief URLs. There is **no Airbus / REAP / Nevada SIP pad**. Rank 1–3, 5–11 sources match the briefs those questions cite (Synopsys, Treasury, CNBC student-loan desk, Vienna quantum photonic processor, Indian IIP, teacher shortages, and so on).

**Finding (not a K1 regression).** A linked card can still carry a brief that does not support the question:

- Rank 4 *Shadow waiver lists for AI-disrupted failing majors* cites the earnings-test education brief **and** a Caltech “quantum energy ladder” science brief. The science URL is on-topic for that brief and off-topic for the question.
- Rank 12 *Acqui-hire squeeze on topological qubit labs* assumes “generalist VCs have exited deep tech.” Both briefs are lab results. No VC source is attached.

That is pairing / smith invention, not display padding. The desk will assay whatever `brief_ids` it is handed. Catching rank 12’s unsourced premise is the point of D2. Do not drop rank 4 from the desk just because one brief is a stretch — the assay should mark that claim unverified or contradicted.

**Desk may proceed.** Wrong-link pad from run 22 is gone.

---

## 2. Search budget (Brave)

The desk wants ≤6 Brave searches × ≤5 opportunities ≈ **30 extra searches** on top of fetch.

Fetch already runs 2 news queries per vertical. Run 23: **7 verticals × 2 = 14** Brave calls, 112 hits, `rate_limited=[]`. `BRAVE_MIN_INTERVAL_S=1.1` (Render) is already slower than a 1 req/s plan. Thirty more searches add ~33 seconds. **Per-second rate is fine.**

Monthly quota is **not stored**. Brave’s current Search plan is prepaid: **$5 / 1,000 requests**, plus **$5 free credits / month** (= 1,000 Search requests if that is the only plan). Headers `X-RateLimit-Limit` / `Remaining` exist (`1, 15000` style on older docs) and are not persisted here. This session cannot see the Operator’s Brave dashboard.

Cap that fits a **1,000-request month** at one Operator run per day:

| Mix | Searches / run | × 30 days |
|---|---|---|
| Fetch 14 + desk 30 (5 × 6) | 44 | 1,320 — **over** free 1,000 |
| Fetch 14 + desk 18 (3 × 6) | 32 | 960 — fits |
| Fetch 14 + desk 12 (3 × 4) | 26 | 780 — fits with headroom |

**If the key is on paid Search with no monthly cap**, 30 desk searches are fine. **If it is free-credit only**, default `OPPORTUNITY_MAX=5` at 6 searches each will exhaust the month on daily runs. Build the defaults as specified; persist Brave remaining/limit on the first desk call so the footer can say `Brave N remaining` when the header is present. Do not invent a second rate limiter. Do not raise `BRAVE_MIN_INTERVAL_S`.

On-demand Assay this (up to 10/day × 6 = 60) is the larger Brave risk. Same rule: pace at 1.1s; stop when Brave returns 429 after one retry (existing `_request`).

---

## 3. Saved questions (`promoted_at`)

| | |
|---|---|
| Column | `questions.promoted_at` |
| ORM | `DateTime(timezone=True)` on `QuestionRow` |
| Live Postgres | `timestamp without time zone` (added by `_migrate_wo006`) |
| Written by | `POST /api/questions/{id}/promote` — sets `promoted=True`; stamps `promoted_at` **only if it is null** |
| Does not | change `status` or `rank` (WO-006 F6) |
| Today | 0 rows with `promoted=true` |

**How the desk finds “saved since the last run”:**

```
questions.promoted IS TRUE
AND questions.promoted_at >= previous_run.started_at
```

`previous_run` is the latest `runs` row with `id < current` (run 22, when this is run 23). A save during the current run is not “since the last run”; it waits for the next desk pass. Re-promote does not move the stamp, so a question saved once is eligible on the first desk run after that stamp and must be **deduped by question id** if it is also in the top-3 so it does not consume two of `OPPORTUNITY_MAX`.

There is no `ideas` table. Promote is still only those two columns.

---

## 4. Cost per opportunity (judgment + WO-010 fallback)

Desk calls use `JUDGMENT_MODEL=claude-fable-5`. WO-010 already retries the **same prompt** on `FALLBACK_MODEL=claude-opus-5-5` when `stop_reason=refusal`. Desk agents must go through `swarm.llm.LLMClient` with `judgment=True` so that path applies. A keyed empty/refusal does **not** fill a card (WO-008 / WO-010).

Estimate from run 23’s fable-5 dollars-per-token, assuming two calls (D2 assay + D4 card), short of the curator:

| Call | In / out (approx) | $ on fable-5 |
|---|---|---|
| Assay (claims + verdicts + what’s true) | 2.5k / 1.2k | ~$0.13 |
| Card (schema-validated) | 3.5k / 1.5k | ~$0.18 |
| **One opportunity** | | **~$0.31** |
| Five opportunities | | **~$1.55** |
| Three (typical, no saves) | | **~$0.93** |

The order’s $0.30–0.60 / run is **low** if both steps are fable-5 at curator-like density. It holds only if prompts stay small or assay+card share one call. D4 says one call writes the card **from the assay**, so two calls is the honest read.

One Opus refusal recovery is the same token shape at a higher posted rate (not measured here). Budget the desk as optional: if `cost_usd + reserved_desk > RUN_BUDGET_USD` ($5), skip and footer it. Reserve **$0.40 per remaining slot** before starting each opportunity (covers one fable pair; not a full Opus pair). If the first call refuses and recovers, count the Opus dollars against the same budget and stop when the next slot would exceed it.

Show **desk total** and **per opportunity** in the run footer, separate from scout/smith/curator.

---

## 5. Reading cited pages

**The desk cannot fetch a cited page’s article text today.** There is no HTML / readability / trafilatura helper. Adapters are API-only. Stored text is:

- `signals.snippet` — clipped to 2,000 chars at fetch (`SNIPPET_STORE_CHARS`)
- scout prompt trim — 800 chars (`SNIPPET_CHARS`)
- `briefs.what_is_happening` / `why_now` — model prose, not the page
- Brave `description` — a search snippet, not the page

`SOURCE_TIMEOUT_SECONDS=45`. Hitting `brief.sources` URLs from the desk would be new network, often paywalled (NYT, Law360, Yahoo), and would race the optional-stage budget. **Do not add a page fetcher in this order.**

Assay works from: (1) stored brief fields + signal snippets for the cited URLs, (2) Brave search snippets from the two wordings per claim. **Every card says** `Checked from stored snippets and search snippets — cited pages were not fetched.`

---

## Build / no-build

| Item | Build? |
|---|---|
| D1–D6 as specified | Yes |
| Defaults `OPPORTUNITY_MAX=5`, `ASSAYS_PER_DAY=10` | Yes |
| Assay from snippets + Brave, card discloses that | Yes |
| Page fetcher | **No** (finding 5) |
| Lower default searches to fit free Brave | **No** — report the 1,000/month cap; Operator chooses plan or keys |
| Drop rank-4-style stretch pairings from the desk | **No** — assay them |
| Fix FR 400 / ReliefWeb 410 / GDELT 429 / EIA+FRED keys | **No** — out of this order; Operator keys still missing |

Nothing in verify blocks the desk. WO-011 K1 is live. The first desk run will assay run-24 (or the next Operator Run), not rewrite run 23.
