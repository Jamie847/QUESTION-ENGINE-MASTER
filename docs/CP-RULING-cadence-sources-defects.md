# CP Ruling — cadence, sources, and three defects pulled forward

**Recorded by:** CW (Cowork), from the Operator's relay · **Date:** 2026-09-08
**Status:** RATIFIED. CP's ruling, transcribed. CW asked the questions; CP decided them.
**Supersedes in part:** `WO-001-manual-only-runs.md` (see §2).
**Source:** CW's briefing `CW-BRIEF-CP-cadence-and-sources.md` of 2026-09-08.

## 0. Provenance

CW put four questions to CP. CP ruled on all four and added two items of its own. This file is
the record so the decisions do not live only in a chat window. **Judgements below are CP's.**
CW's notes are marked as such and are separable.

CP's characterisation of the briefing, kept because it names what drove the ruling: *"the 76%
Hacker News number is the finding that should reorganize the roadmap."*

## 1. Digest uniqueness — unbundled, fixed first

**Ruled:** the `DigestRow` date-uniqueness amendment becomes a **standing defect fix, ahead of
both the catalog and focus runs.**

CP explicitly corrected its own earlier ruling. It had ratified the amendment as *"required
whenever the first of these two features builds"*; CP now holds **that condition was wrong** —
two ordinary Run clicks fired it on 2026-09-08 and destroyed run 13's $1.10 of rateable output.

CP's reason: *"Ratings are the scarcest resource in this project and the schema silently deletes
them."*

CP also adopted the second-order point: **under this schema a cron is safer than manual
clicking**, which inverts the premise WO-001 was written on.

## 2. Cadence — staged, and WO-001 partly reversed

**Ruled, in this order:**

1. Fix uniqueness (§1).
2. **The Operator rates the five existing digests.**
3. **Then** a weekday schedule — `0 10 * * 1-5`. **Not daily.**
4. Daily may follow if the ratings justify it.

CP's finding on the interim period, stated more sharply than CW had: **manual-only failed on its
own terms** — *"less predictable, not cheaper, and it produced three empty days."* Measured: five
digests across eight days, gaps on 09-04, 09-05 and 09-06; then two runs in one day on 09-08.

CP affirmed CW's core point: **more digests do not advance the gate; only rating does.**

**This partly reverses WO-001**, which was written on a cost premise that the observed data did
not support. WO-001's staleness-indicator work stands and is unaffected. The leap-day schedule
(`0 0 29 2 *`) is superseded at step 3, not before.

## 3. Sources — free primary documents first, and no Perplexity

**Ruled:** **Federal Register, then Regulations.gov.** No Perplexity.

CP's reasoning: *"the system is already asking regulatory questions while reading none of the
primary regulatory record."* CP notes this is the same conclusion it reached from the SSRN
direction in the WO-004 ruling, and that CW's version is stronger because it is evidence-backed
rather than argued.

On Perplexity specifically: *"Perplexity sells synthesis; we have synthesis. We're short of
primary material."*

**If a second general web search is ever wanted:** Parallel at $1/1,000 with a 5,000-request free
tier is the trial — not a $5/1,000 synthesizer.

**Nothing here reopens the lexical dedup ruling of 2026-09-01.** These are fetch-side additions;
no embeddings, no pgvector, no vector store. If CC later argues that more sources require
semantic dedup to manage volume, **that is a reopening and must come back to CP as one.**

## 4. Reddit — in scope now

**Ruled:** fix it now. Free, dead for fourteen consecutive runs.

CP named the failure class: *"an adapter returning empty without erroring"* — the shape this
project keeps meeting.

**Plus a new requirement:** a source returning zero on N consecutive runs must report **dead**,
not merely degraded. *"A permanently silent source shouldn't be indistinguishable from a quiet
one."*

> **CW note on implementing that rule — a design trap worth avoiding.** Runs are currently
> sparse and irregular, so "N consecutive runs" is not "N days." More importantly, **the flag
> must be recoverable and must not be sticky**: Brave returned zero on runs 6 through 10 and has
> returned 8 on every run since. A dead-flag that latched on run 10 would still be lying today.
> The rule should clear itself the moment a source returns anything, and the dashboard should
> show when it last did.

## 5. Two items CP pulled forward that CW had listed but not pressed

**`agent_calls` stops being deferred.** CP: it has been deferred twice, already cost a day of
debugging (CW Finding 002), and cost is creeping $0.97 → $1.11 with no way to attribute it to a
stage. **Build it alongside the uniqueness fix.** Spec §7 and §10 both place it in Phase 1; this
ends a Phase-1 gap that has been open since the first build.

**Kill reasons become stored labelled data.** CP: *"'The mechanism slot is empty' is exactly the
corpus WO-002 identified as one of the few genuinely proprietary assets here. If it's only
rendered to a page, it's being thrown away nightly."*

## 6. Confirmed: the taste seed is the Operator's

CP confirms the Operator wrote `taste/seed.md` before the first keyed run, and the kill reasons
show the curator applying it. **The earlier CW finding that the seed was empty is superseded**
and should not be repeated by a later session.

**Superseded 2026-09-30 (WO-006).** The Operator stated he did not write the example questions
in `data/taste_seed.yaml`. The sentence quoted as proof — "specific populations, named
mechanisms…" — was a hardcoded string in `swarm/taste.py`, now the `notes` field of the
stand-in file. That file is a stand-in. It is not his seed. Do not repeat the claim above.

## 7. What is and is not blocked on ratings — CW note

CP wrote that *"every gate on the board is waiting on you rating five digests."* That is true of
the **cadence** decision and of the catalog and focus runs. It is **not** true of most of this
ruling:

| Item | Blocked on ratings? |
|---|---|
| §1 digest uniqueness | **No** — build now |
| §5 `agent_calls` | **No** — build now |
| §4 Reddit OAuth + dead-source rule | **No** — build now |
| §3 Federal Register adapter | **No** — build now |
| §2 step 3, weekday schedule | **Yes** |
| Catalog, focus runs | **Yes** (CP's earlier sequencing) |

So four of the six work items are unblocked today. **Rating and building are parallel, not
sequential**, and treating them as sequential would idle CC for no reason.
