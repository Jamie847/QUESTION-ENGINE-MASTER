# CP Ruling — Q1 dedup strategy

**From:** CP · **Date:** 2026-09-01
**Answers:** `docs/CP-RULING-REQUEST-dedup.md`
**One item:** ratify, overturn, or amend ruling (d).

## Ruling

**(d) is ratified as design**, not as an implementer workaround.

Dedup in Phase 1 is lexical: content-token Jaccard after template stopwords are
stripped. No embeddings vendor. No `embedding` field. No pgvector.
`/healthz` reports `pgvector_installed: false` on purpose. A session that treats
`true` as the healthy value is reading a voided check.

CW's withdrawn cost argument is accepted: nothing is stored as a vector, so a
later upgrade is a nullable column plus a partial backfill, not a rewrite.
That reversibility is a reason *for* (d), not a reason to treat it as unfinished.

## The re-trigger is amended. CW is right.

The condition *"if three keyed weeks show a real miss"* cannot fire. A miss is
paraphrase. Paraphrase is exactly what a content-token gate does not match on.
Three quiet weeks prove the stage ran. They do not prove it worked. The nightly
duplicate-rate number has the same blindness: it will read low and stable while
paraphrase ships, and a low number on Taste will be read as "working."

That is not an argument against (d). It is an argument that (d) was wearing a
provisional label nobody could honour.

**Present tense, as of this ruling:**

> Dedup does **not** catch paraphrase. A low lexical duplicate rate is not
> evidence that it does.

## What replaces the dead condition

All three of CW's options, stacked. Any one alone was incomplete.

1. **Human gate, every digest (now).** The Kill Floor already samples drops.
   The inverse is required: sample up to three pairs of *surviving* questions
   from adjacent days that share an intersection (same vertical set) or at least
   one vertical, ranked by lexical overlap descending. The prompt on each pair
   is "same question in different words?" Jamie's flag is a condition a person
   can attest to.
2. **One offline measurement after three keyed weeks.**
   `python scripts/measure_paraphrase_leak.py` against stored question text.
   No production column. No vendor in `requirements.txt`. A one-afternoon embed
   of accumulated history, when someone pastes a throwaway key, converts "a
   real miss" from a vibe into a count. Until then the script still reports
   the gray-zone lexical band so the work is not blocked on a key.
3. **The honest label (now).** Footer, Today meta, and Taste all say the
   duplicate number is token overlap only. Spec §8 is superseded to match.

**Re-trigger, restated so it can fire:**

- Jamie flags **three** near-miss pairs as paraphrase across keyed weeks, **or**
- the offline measurement after three keyed weeks shows a leak rate that makes
  the digest feel repetitive,

then add a *nullable* vector column and pick a provider then. Not before.
Quiet weeks do not count.

## Spec

v1.1 §3.3 and §3.4 are superseded in place in
`docs/question-engine-tech-spec-v1.1.md`. The old `embedding: list[float]` and
cosine ~0.92 lines stay readable. They are the record that the vector stage was
the design. They are not the build target.

## What this does not do

It does not add Voyage, sentence-transformers, or `CREATE EXTENSION vector`.
It does not ask CC to rebuild Phase 1. It does not fill `taste/seed.md`.
