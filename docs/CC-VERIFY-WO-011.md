# CC verify — WO-011 (run 22)

Posted before any WO-011 code. Measured against live production run 22 (`e11bd3b`, 2026-10-02 02:28 UTC, $1.57, completed) and the GitHub tree at `5229554` / merge `e11bd3b`.

## 1. The source-mapping cause

**CP's hypothesis is false.** Labels are not looked up in the run-wide signal list.

`urls_from_model` in `swarm/agents/scout.py` resolves `S1`… against that scout's own `pairs`:

```
labels = {f"S{n}": sig for n, (sig, _rank) in enumerate(pairs, start=1)}
```

Run 22 `agent_calls` confirm each scout's S1 is its own first candidate, not a Federal Register notice:

| Call | Vertical (from S1) | S1 |
|---|---|---|
| 61 | AI | Cloudflare Clef (hacker_news) |
| 62 | Health | Ask HN: Who is hiring? (hacker_news) |
| 63 | Business | Paramount–WBD Wikipedia attention |
| 64 | Science | AI theoretical-physics breakthrough (brave) |
| 65 | Education | Cornell rape-allegations Wikipedia attention |

None of those S1s is the Airbus AD, the REAP grant, or the Nevada SIP. Health is the only scout whose stored `raw_signals` includes `federal_register`. The two FDA committee-renewal briefs cite the two FDA notices that were in that scout's mix. That part is honest.

**The wrong *primary* badges on ranks 1, 2, 4, 8 and 9 come from a later remapping, not from S1.**

Two stacked defects, both in `prefer_primary_urls` (`swarm/primary.py`):

1. **Scout persist.** After the model cites URLs from its own labels, `_llm_briefs` calls `prefer_primary_urls(brief_text, claimed, scout_pairs)`. If the brief text matches `RECORD_RE` (`rule|docket|filing|paper|regulation|accountability|…`) and token overlap with a primary is `< 2`, the function prepends **every** primary URL in that scout's pair list (`any_primary`). That is why the Education "gainful-employment-style rule" brief stored thirteen arXiv URLs in front of the three commentary URLs the model actually cited.

2. **Dashboard display — this is the Airbus-on-eight-cards bug.** `dashboard/honesty.py` `from_cites` rebuilds the card's From: line at read time. When the linked briefs look like a record, it calls `prefer_primary_urls(blob, claimed, modeled)` where `modeled` is **every signal in the run**, not that scout's input. Same `any_primary` fallback. The first primaries in run 22 are the unhinted Federal Register hits from the query `"foundation model regulation"`: REAP grant, Airbus AD, Nevada SIP. `cites[:5]` then prints those with a *primary* pill. WO-009 U3's `test_primary_record_is_cited_first_for_a_rule` encodes this as intended behaviour.

Brief sources on the five bad ranks contain no `federalregister.gov` URL. The digest markdown, written from `brief.sources`, cites arXiv / Pharmacy Times / NYT. The live cards disagree because `from_cites` rewrites them.

**The check WO-011 wants does not exist.** A resolved URL is never required to have been in that brief's scout input. A brief is never marked `unlinked` for a foreign primary. Neighbours are padded on.

**Past-run repair note.** `agent_calls.input_text` / `output_text` are stored and start with the system prompt plus `Candidate signals:`. Length is capped at 8,000 characters, so later S-labels in a large mix are truncated. Repair can re-resolve only the labels that are still in the stored input.

## 2. How *Sources linked* counts

`sources_linked_line` (`dashboard/honesty.py`):

- Restricts to `status == curated`. If that set is empty it falls back to every question.
- Counts `provenance == "linked"`. Nothing else.
- Does not inspect refs, scout input, or whether a URL is in `signals`.

Run 22: 10 curated + 8 killed. Every stored question has `provenance=linked`. The header therefore reads **Sources linked: 10 of 10**. That is every curated question, not a special "top ten" slice. Killed questions are excluded. The "10" is the curated set size, not a checked-ref count.

## 3. The near-miss pairs

The digest was written **without** `briefs_by_id` (`archivist.render_digest` → `sample_near_miss_pairs(questions, prior)`), so it ranked by shared vertical / lexical overlap. The live Today page recomputes with `briefs_by_id` and tags `url` first.

Shared `brief.sources` URLs between run 22 curated and run 21 curated (the live ranker). First three unique today/prior texts, rank order:

| # | Today | Prior (run 21) | Shared verticals | Shared URLs |
|---|---|---|---|---|
| 1 | Rank 1 · Fedspeak / trading LLMs (`business × ai`) | Rank 3 · earnings-accountability / university departments (`education`) | **none** | `nytimes.com/…/fed-interest-rates-midterms.html` · `federalreserve.gov/releases/h15/` · `economictimes.com/…/us-treasury-yields-falling…` |
| 2 | Rank 2 · GPT-Synopsys shadow verification (`ai`) | Rank 7 · Anthropic CRISPR + math claims (`ai × science`) | `ai` | `theguardian.com/…/ai-godfathers-warn-of-runaway-intelligence-explosion` |
| 3 | Rank 4 · teacher-prep earnings test (`education`) | Rank 13 · public/nonprofit earnings-test exposure (`education × business`) | `education` | `snopes.com/…/trump-cutting-student-loans` · `yahoo.com/…/student-loan-rule-may-force…` · `dailysignal.com/…/trumps-student-loan-rules…` |

Pair 1 is the no-shared-vertical `url` pair. The URLs are real Fed/yields links, not the Airbus notice. They attach because run 21 rank 3's `brief_ids` include both the education-rule brief **and** the Fed-hike brief, so a university-department question inherits `federalreserve.gov/releases/h15/`. Run 22 rank 1 inherits the same hosts from the treasury-yields brief. The sampler then treats "same URL" as a near-miss even though the questions do not share a topic.

The Airbus / REAP / Nevada notices do **not** appear in stored `brief.sources` for these pairs. They only appear on the cards via `from_cites`.

## 4. The Federal Register query

`FederalRegisterSource.fetch` calls `documents.json` with `conditions[term]` (first two `search_queries` per vertical) and `conditions[publication_date][gte]`. No `conditions[type][]`. No `conditions[significant]`. No `conditions[agencies][]`.

Run 22 stored **7** FR documents:

| Type | Agency | Title | Query | Hints |
|---|---|---|---|---|
| Rule | USDA / Rural Business-Cooperative Service | REAP / rural energy | `foundation model regulation` | none |
| Rule | FAA | Airworthiness Directives; Airbus SAS Airplanes | `foundation model regulation` | none |
| Proposed Rule | EPA | Nevada Truckee Meadows PM-10 SIP | `foundation model regulation` | none |
| Notice | FDA | Antimicrobial Drugs Advisory Committee; Renewal | `FDA approval drug` | health |
| Notice | FDA | Dermatologic and Ophthalmic Drugs Advisory Committee; Renewal | `FDA approval drug` | health |
| Notice | FDA | Request for Nominations for Advisory Committees | `FDA approval drug` | none |
| Notice | SEC | CME Securities Clearing stress-testing rule change | `Federal Reserve interest rates` | none |

Four of seven are Notices. The Airbus AD is a Rule, so a type filter alone will not drop it.

**API filters that exist** ([FR API v1](https://www.federalregister.gov/developers/documentation/api/v1), no key):

- `conditions[type][]` = `RULE` | `PRORULE` | `NOTICE` | `PRESDOCU`
- `conditions[agencies][]` = agency slugs
- `conditions[significant]` = EO 12866 significant-action flag (available; polarity will be confirmed on the first filtered fetch)

K3 can limit to final + proposed rules, prefer significant, exclude ADs / committee renewals in code, and apply a per-vertical agency allow-list.

## 5. The "quietly" ban

| Location | Ban present? |
|---|---|
| `swarm/prompts/smith.md` | Yes — "never uses stock intensifiers (\"quietly,\" \"silently\")" (WO-009 U2) |
| `swarm/prompts/curator.md` | **No.** Title instruction has no banned-word line. |

Run 22 hits:

| Stage | Writer | Where | Count |
|---|---|---|---|
| Smith | `model:claude-sonnet-5` | Question text (rank 2 curated, rank 10 curated, one killed) | 3 |
| Cross-pollinator | `model:claude-fable-5` | Accepted health×health thesis (`quietly raise the evidentiary bar`) | 1 |
| Curator | `model:claude-fable-5` | Kept ranks 2 and 10; did not strip the word | 0 new; 2 kept |
| Archivist | template | Digest markdown reprints the three question texts and the thesis | 6 |

The smiths wrote every question-text occurrence. The ban is in the smith prompt and the model ignored it. The curator title instruction does not repeat the ban, so titles were not the source — the kept questions still contain the word. Footer does not count banned words today.

Eight on the live page is the three question texts + reprints (digest / cards / kill sample) plus the intersection thesis.

## Header time twice

`run_banner()` already includes `format_local(started)`. `dashboard/main.py` then appends `format_run_stamp(started)`, a second copy of the same instant. `today.html` also appends `digest.date` after the banner. That is the double (and sometimes triple) clock.

## What goes red today

| WO-011 test | Red against unfixed code? |
|---|---|
| 1. Labels resolve per scout | **No.** Hypothesis did not hold. S1 already means that scout's first signal. |
| 2. Foreign refs dropped | **Yes.** `prefer_primary_urls` / `from_cites` pad with run-wide or scout-wide primaries. |
| 3. The count is honest | **Yes.** Provenance-only, curated-only. |
| 4. No same-field pairings | **Yes.** Cross-pollinator accepts `ai × ai`, `education × education`, `health × health`. 4 of 8 accepted intersections on run 22 are single-field. Prompt does not require two different verticals. No `single field` reject path. |
| 5. FR filter | **Yes.** Airbus AD and both committee renewals became signals. |
| 6. Movers write the numbers | N/A — adapter does not exist. |
| 7. New verticals route | N/A — `geopolitics` / `commodities` are not in `verticals.yaml`. |

K1 first. New verticals must not inherit the remapping.
