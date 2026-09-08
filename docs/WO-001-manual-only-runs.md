# CC Work Order 001 — manual-only runs, no schedule

> ## PARTLY SUPERSEDED — 2026-09-08. See `CP-RULING-cadence-sources-defects.md` §2.
>
> **Manual-only is being reversed in stages, by CP ruling, on measured evidence.** The landing
> spot is a weekday schedule (`0 10 * * 1-5`), reached after the uniqueness defect is fixed and
> the Operator has rated the five existing digests. Daily may follow.
>
> **Why:** this work order's §1 recorded the spec's warning — *"a system you must remember to run
> is a system you stop running"* — as a real risk rather than a defeated one. Eight days of data
> settled it. Digests exist for 09-01, 09-02, 09-03, 09-07 and 09-08; **09-04, 09-05 and 09-06 are
> empty.** Then two runs happened on 09-08. CP's finding: manual-only **failed on its own terms —
> less predictable, not cheaper.**
>
> The cost premise this work order was built on ($0.968/run against ~$11 of credit) also no longer
> holds the way it did; the observed manual rate cost about as much as a weekday schedule would
> have, while producing three empty days.
>
> **What still stands from this work order:** everything in §3 about the **staleness indicator**,
> which was the non-obvious half and is unaffected. Both manual trigger paths stay working. The
> leap-day schedule `0 0 29 2 *` remains correct until step 3 of the staged sequence lands — do
> not replace it before then, and do not replace it with anything that looks real.
>
> **The inversion worth carrying forward:** because `DigestRow` was unique on date, **one scheduled
> run per day is safe and repeated manual clicking is not** — the second run of a day silently
> replaces the first. That is the opposite of the intuition this work order was written on.
> Uniqueness is now per run (CP 2026-09-08 §1). The inversion still explains why the weekday
> schedule is the safer cadence once ratings land.
>
> ---

**From:** CW (Cowork), at the Operator's direction · **Date:** 2026-09-03
**Governance:** Operator decided → CC builds → CW verifies against the deployed service.

## 0. What the Operator asked for

The swarm should run **only when Jamie clicks a button**. No automatic daily execution.

## 1. Before building — surface this to the Operator, do not silently implement

**This reverses a stated design principle, and the reversal should be knowing.** Spec v1.1 §6:

> *"**Fully autonomous by design.** No human-in-the-loop publish gate. A 10-minute morning
> approval step is the kind of small friction that quietly kills daily habits. After-the-fact
> ratings are a slightly weaker training signal, but a signal actually provided beats a cleaner
> one that gets skipped."*

The spec's whole argument for a daily cron is that a system you must remember to run is a
system you stop running. That argument is not wrong because the Operator changed his mind — it
is a real risk that now applies, and it should be recorded rather than deleted.

## 2. What shipped

- Leap-day cron `0 0 29 2 *` so Render still has a required `schedule` and the job does not
  fire on a daily cadence. Suspend is not used: a suspended cron cannot be Trigger-Run'd.
- Both manual paths stay: Render Trigger Run, and Controls → Run swarm now (`POST /api/run`).
- The run lock still guards overlap.
- Today and the digest footer show **last run: N days ago** and mark the digest stale past
  `STALE_AFTER_DAYS` (default 3).

## 3. Staleness indicator (still in force)

With a daily cron, a stale digest is impossible. With manual runs, the dashboard can show a
three-week-old digest with nothing on screen saying so. Surface the age. This is the same
class of problem as the paraphrase gate: removing the mechanism that made a failure visible,
without replacing the visibility.
