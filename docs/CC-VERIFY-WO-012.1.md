# CC verify — WO-012.1 (sharper desk, live sources, lower cost)

Posted before any WO-012.1 code. Measured against live `/healthz` `1597e3c` and acceptance run **25**. No run in progress.

## Run 25 (already accepted)

| | |
|---|---|
| Cost | $3.34 total · desk $1.50 · $0.49–$0.51 / card |
| Desk model | `claude-fable-5` (6 calls) |
| Sources | FR 400 · GDELT 429 · ReliefWeb 410 · CFTC 0 rows, marked dead |

CP has already checked card #1's numbers against the cited pages. This note is only the six blocking questions.

---

## 1. Federal Register 400

**Cause: invalid agency slugs, not `significant`.** CP's guess was half-right — a WO-011 filter is malformed — but the bad field is `conditions[agencies][]`, not `conditions[significant]`.

Exact request from run 25 (AI vertical, first query, first call — then the adapter raises and the rest of FR never runs):

```
GET https://www.federalregister.gov/api/v1/documents.json
  per_page=8
  order=newest
  conditions[term]=artificial intelligence breakthrough
  conditions[publication_date][gte]=2026-10-01
  conditions[type][]=RULE
  conditions[type][]=PRORULE
  conditions[significant]=1
  conditions[agencies][]=bureau-of-industry-and-security
  conditions[agencies][]=commerce-department
  conditions[agencies][]=national-institute-of-standards-and-technology
  conditions[agencies][]=federal-communications-commission
```

Replay, 2026-10-02 14:08 UTC:

```
HTTP 400
{"errors":{"agencies":"invalid value"}}
```

Same 400 with `significant` removed. `conditions[significant]=1` **without** agencies returns 200 (student-loans RULE+PRORULE since 2026-09-01, 1 hit).

Per-slug replay against `documents.json`:

| YAML slug | Result | Official slug (`/api/v1/agencies`) |
|---|---|---|
| `bureau-of-industry-and-security` | **400** | `industry-and-security-bureau` |
| `office-of-foreign-assets-control` | **400** | `foreign-assets-control-office` |
| `commerce-department` | 200 | same |
| `national-institute-of-standards-and-technology` | 200 | same |
| `federal-communications-commission` | 200 | same |
| `education-department`, FDA, CMS, HHS, State, Treasury, Energy, EPA, USDA, Interior | 200 | same |

FR validates **every** agency in the request. One invented slug 400s the whole call. AI is first in `verticals.yaml` and includes BIS, so the first GET dies and FR reports dead.

**Build:** remap the two slugs (and drop any slug not on the recorded valid list) so a malformed filter fails in tests. Keep `significant=1` prefer-then-fill.

---

## 2. GDELT 429

Published throttle (DOC 2.0, the endpoint we call): **one request every 5 seconds**. Body from this session:

```
Please limit requests to one every 5 seconds or contact kalev.leetaru5@gmail.com …
```

Run 25 fired two geopolitics queries **with no pause**:

1. `sanctions OR "export control" OR ceasefire`
2. `"taiwan strait" OR "red sea" OR "strait of hormuz"`

Elapsed 8,616 ms, first URL already 429. This session: first GET 429 after 10.6 s; retry after 6 s still 429. Shared-IP / prior-run residue can 429 even a single call. The adapter still has no spacing and no named-query record — `collect_signals` already supports `rate_limited_queries` if we set it instead of raising.

**Build:** one combined query for the vertical (two wordings → one OR), ≥5 s between any remaining calls, one retry after 6 s, lasting 429 recorded as `429 on query: <text>`. Do not invent a second public API.

---

## 3. ReliefWeb 410

Adapter calls **v1**: `https://api.reliefweb.int/v1/reports?appname=question-engine&…`

Replay body:

```
{"status":410,"error":{"message":"The API version 'v1' has been decommissioned. Please use version 'v2' instead."}}
```

Current docs: **v2**, same query shape. From 1 Nov 2025 every request needs a **pre-approved** `appname` ([apidoc.reliefweb.int/parameters](https://apidoc.reliefweb.int/parameters)). Replay of v2 with `appname=question-engine`:

```
HTTP 403
{"error":{"message":"You are not using an approved appname. Kindly request an appname from ReliefWeb here: https://apidoc.reliefweb.int/parameters#appname"}}
```

**Build:** switch the path to `/v2/reports`. Read `RELIEFWEB_APPNAME` from the environment. Until the Operator registers one, the source reports `needs key` (same as EIA/FRED) — not 410. Operator to-do: request an appname (org + purpose + random chars) at that form.

---

## 4. CFTC empty

Dataset is live. `GET https://publicreporting.cftc.gov/resource/6dca-aqww.json` (Legacy – Futures Only) returns rows. Columns the adapter already reads exist: `market_and_exchange_names`, `noncomm_positions_long_all`, `report_date_as_yyyy_mm_dd`.

The query is wrong:

```
$limit=400
$order=report_date_as_yyyy_mm_dd          # ASC, oldest first
```

Manual call: first row is **1986-01-15 WHEAT – MidAmerica**. None of those 400 oldest rows contain `CRUDE OIL`, so `extract_points(..., "CRUDE OIL")` is empty and movers emit nothing. Health then marks CFTC dead for consecutive zeros (`error=null`, `ok=true`, `dead=true`).

Same dataset, corrected query, this session:

```
$limit=5
$order=report_date_as_yyyy_mm_dd DESC
$where=upper(market_and_exchange_names) like '%CRUDE OIL%'
```

→ `WTI FINANCIAL CRUDE OIL – NYMEX`, `report_date_as_yyyy_mm_dd=2026-09-22`, `noncomm_positions_long_all` present.

**Build:** per-market `$where` + newest-first + enough weeks for the 14-period trail. If the series is present but the latest change is not a 2σ mover, still emit the latest positioning number so count > 0.

---

## 5. Search quota (Brave)

Run 25: fetch **14** Brave calls (7 verticals × 2) + desk **~18** (3 cards × ~6 claim wordings) ≈ **32**. `rate_limited=[]`. `BRAVE_MIN_INTERVAL_S=1.1`.

After F2 + F3, per opportunity:

| Step | Searches |
|---|---|
| Assay (2 wordings × up to 3 claims) | 6 |
| Rivals (3 wordings + 1 from the chosen shape) | 4 |
| Prospects (buyer × place, at least 3) | 3 |
| **Per card** | **13** |

| Mix | / run | × 30 days |
|---|---|---|
| Fetch 14 + desk 39 (3 × 13) | 53 | 1,590 — **over** free 1,000 |
| Fetch 14 + desk 26 (2 × 13) | 40 | 1,200 — still over |
| Assay this (13 each, cap 10/day) | +13–130 | the larger risk |

Plan (unchanged from WO-012 verify): prepaid Search **$5 / 1,000**, plus **$5 free credits / month** if that is the only product. Per-second rate is fine at 1.1 s. Monthly free credits are **not**.

**Build the defaults as specified.** Do not add a second limiter. Do not raise `BRAVE_MIN_INTERVAL_S`. Persist Brave remaining/limit on the first desk call when the header is present. Operator chooses a paid Search bucket or fewer daily runs.

---

## 6. Page fetching

Still no HTML reader. `SOURCE_TIMEOUT_SECONDS=45`. F4 now **requires** up to two pages per claim.

3 claims × 2 pages × 3 cards = **18 fetches**. At 45 s each that is 13 minutes in the worst case — the optional stage would outrun the rest of the run. **Per-page timeout must be much smaller** (12 s, one retry on timeout/5xx). Cap stored text at `SNIPPET_STORE_CHARS` (2,000). Number rule applies to fetched text. Paywalls / 403 → leave that URL as a snippet and say so.

A stdlib tag-strip is enough; do not add trafilatura. FR HTML and law-firm alerts are the pages CP already used by hand.

---

## Cost / F5 (not a verify block, but it changes the run)

F5 sets `DESK_MODEL=claude-opus-5-5` for a week. Cross-pollinator and curator stay on fable-5. That is a **quality comparison**, not a cost cut. Title says “lower cost”; F5 will almost certainly **raise** desk dollars versus run 25’s $0.50 / card. `desk_reserve_usd=$0.40` is sized for fable. Opus on two calls can eat the leftover $5 budget. Finding, not a rewrite of F5: report actuals; do not silently keep fable.

Judgment reservation math in `budget.py` is already $15 / $75 per MTok (fable-shaped). Desk calls will keep using that reservation. Actual charge follows the same estimator until Anthropic usage is recorded.

---

## Build / no-build

| Item | Build? |
|---|---|
| F1 FR slug remap + recorded-valid request test | Yes |
| F1 GDELT pace + named 429 | Yes |
| F1 ReliefWeb → v2, `needs key` until `RELIEFWEB_APPNAME` | Yes |
| F1 CFTC newest-first + market `$where` | Yes |
| F2 rivals vs commentators, ≥3 searches | Yes |
| F3 prospects with links, ≥3 searches | Yes |
| F4 fetch ≤2 pages / claim, label read-in-full vs snippet | Yes |
| F5 `DESK_MODEL` from env, default `claude-opus-5-5` | Yes |
| New sources / EIA+FRED keys / WO-013–016 | No |
| Lower Brave defaults to fit 1,000/month | No — report; Operator chooses |

Nothing in verify blocks the build. FR, CFTC, and ReliefWeb causes are confirmed. GDELT may still 429 on a shared IP after pacing — the acceptance run must then name the query.
