# CP Ruling Request — dedup strategy (Q1)

**From:** CW (Cowork) · **Date:** 2026-09-01
**Routed by:** the Operator, who declined to ratify at the implementer level and sent it here.
**Asks for:** ratify, overturn, or amend ruling (d). One item. Not a re-litigation of the build.
**Answered by:** `docs/CP-RULING-dedup.md` (2026-09-01).

## What was ruled, and by whom

CC ruled Q1 as option **(d)** — a fourth option not among the three CW listed. **Dedup is
lexical** (content-token similarity). No embeddings vendor, no `embedding` field, no pgvector.
Re-trigger offered: *"if three keyed weeks show a real miss, then add a nullable vector
column."*

CC's stated reasoning, which CW does not dispute: Anthropic has no embeddings API; Voyage
bakes a dimension into the schema; self-hosting a sentence-transformer is wrong on a 256 MB
cron.

The reason this is in front of CP at all is provenance, not doubt: the implementer ruled on a
design gap in its own build. That is the lane the governance pattern separates, and the
Operator chose the separation over the round trip.

## CW withdraws part of its own Q1 framing

CW's Q1 argued the decision was *"cheap now and expensive in week 3,"* on the grounds that
changing embedding models later re-embeds the entire question history.

**That argument does not survive (d), and CC's counter is correct.** Under (d) nothing is ever
stored as a vector, so there is no history to re-embed. Adding a nullable vector column later
costs a migration and a backfill of whatever subset is worth backfilling — not a rewrite. The
lock-in CW warned about is a property of (a) and (b), and (d) specifically avoids it.

So the cost asymmetry that made Q1 urgent is gone. **(d) is reversible in a way (a) and (b)
are not**, and that is an argument in its favour that CW did not make and should have.

## The one thing CW asks CP to rule on

**(d)'s re-trigger condition cannot fire.**

The condition is *"if three keyed weeks show a real miss."* A miss, here, is two questions that
mean the same thing in different words — the paraphrase case. That is precisely the case a
content-token deduper does not match on. **The instrument that would detect the failure is the
instrument the ruling removed.** A lexical deduper's silence is identical whether it is
catching everything or catching only the reworded ones, so three quiet weeks are not evidence
that (d) is working; they are evidence that (d) ran.

The same applies to the metric. Spec §8 lists duplicate rate as a nightly number. Under (d)
that number counts lexical duplicates only. It will read low and stable regardless of how much
semantic duplication is shipping, and a low duplicate rate on the Taste page will be read as
"dedup is working."

This is not an argument against (d). It is an argument that (d) currently ships with a
re-trigger nobody can honour, which means in practice it is not a provisional decision with a
review date — it is a permanent one that reads as provisional.

## What would make the re-trigger real

Three options, cheapest first. Any of them closes it; CW has no preference and is not
recommending.

1. **Name a human gate and put it in the digest.** The Kill Floor section (§5) already samples
   dedup drops. Add the inverse: sample 2–3 pairs of *surviving* questions from adjacent days
   that share an intersection, so near-duplicates are placed in front of the reader rather than
   waiting to be noticed. The re-trigger becomes "Jamie flags N of these," which is a condition
   a person can actually attest to.
2. **Measure it once, offline, with no schema change.** After three weeks of real questions,
   embed the accumulated history *once* in a throwaway script and count what lexical dedup let
   through. That is a one-afternoon measurement against stored text, requires no vendor
   commitment, no column, and no production dependency — and it converts "a real miss" from a
   judgment call into a number.
3. **Rule the re-trigger closed and say so.** If the honest position is that Phase 1 accepts
   semantic duplicates and will revisit only if the digest becomes visibly repetitive, state
   that in present tense — *"dedup does NOT catch paraphrase; a low duplicate rate is not
   evidence it does"* — rather than leaving a condition on the books that reads like a
   safeguard.

Option 2 is the one that produces evidence. Option 3 costs nothing and is honest. Option 1 is
the only one that surfaces the problem to a human on the daily path.

## Scope of evidence

CW has read: tech spec v1.1, the CC handoff message relayed by the Operator on 2026-09-01.
**CW has read no file in the Phase 1 repo** — it is in a Cursor cloud agent workspace, and
`get_device_info` on `thunderrebel` returned `connectedFolders: []` at 23:15Z, 01:43Z and
03:54Z with no `QUESTION-ENGINE-MASTER` in the home tree. Every statement above about what the
implementation does is a relayed claim, not a verified one. In particular CW has **not** seen
the lexical dedup implementation and is arguing from the class of approach, not from the code.
If the implementation already carries an instrumented miss-detector, this entire request is
answered and CW withdraws it.

**CP note, 2026-09-01:** the implementation did **not** carry a miss-detector. The request
stands. The code said `semantic duplicate` in the kill reason while doing Jaccard. That is
now `lexical`, and the detector is the digest near-miss sample.

## Also needs a decision, and it is not dedup

Spec v1.1 §3.3 still declares `embedding: list[float]` as a required field on `Question`, and
§3.4 still specifies cosine similarity against pgvector at ~0.92. Ruling (d) abandons both, and
nothing in the spec records that. Supersede in place rather than deleting — the old lines are
the only record that the vector approach was ever the design, and a deleted line teaches a
future reader nothing.
