# CC verify — WO-009 (Today page)

Posted before any WO-009 code. Measured against this tree at `6d475e6` and against production run 20 (`e070c6ca`, 2026-09-30) from the earlier live read.

WO-008 is not in this tree. The empty-lens work is not merged here. U2's smith-prompt line lands on the current smiths. Nothing else from WO-008 is invented.

## 1. Run button

The control exists only on Controls.

- `dashboard/templates/controls.html` is the only template with `id="run-btn"`.
- `dashboard/static/app.js` binds `#run-btn` if that node is present, and posts `POST /api/run`. Today includes the same script via `base.html`, but Today does not render the node, so the handler is a no-op.
- `dashboard/templates/today.html` has no run trigger. The empty state and the stale line both say "Trigger a run from Controls".
- Today calls nothing that starts a run.

## 2. The wrong source label (run 20, rank 3)

**Field the label reads.** `dashboard/honesty.py` `from_line` builds the "From:" string from the linked briefs:

1. `brief.headline` — the scout's rewritten headline
2. `brief.sources` — URLs the scout claimed, filtered to URLs that appeared in that vertical's scout mix (`_known_urls`)

It does not read `signals.source`, `signals.title`, or the host of the URL.

**Why it disagrees with the URLs.** Scout `format_scout_line` labels every candidate `- {title} ({source}, #{rank}) {url}`. `Brief.raw_signals` is not the source of the cited URLs; it is the first four source *names* in the scout mix (`[s.source for s in signals[:4]]`). The model then writes a headline (which can keep a wikipedia flavour) and picks commentary URLs that happen to be in the mix.

Run 20 rank 3 (gainful-employment) was brief `r20-education-trump-s-new-gainful-empl-64819abf5d`. Its `raw_signals` were `["wikipedia","brave","arxiv","wikipedia"]`. Its `sources` were thesource.com, townhall.com, and ibtimes.co.uk. No Federal Register URL. The "(wikipedia)" on the page is the scout-mix / rewritten headline, not the `signals.source` of those three hosts.

## 3. Federal Register, 3 of 14 read (run 20)

`FederalRegisterSource` sets `vertical_hints` from `hint_verticals(title)` only. A document with no keyword hit gets `[]` and never enters a vertical scout (except the last-resort unassigned slice, which is not how the 14 were counted).

Of the 14 stored FR documents on run 20:

| Routing | Count | Notes |
|---|---|---|
| `health` | 2 | keyword hit on the title |
| `business` | 1 | keyword hit on the title |
| no vertical | 11 | includes the Title IX recodification |

The Department of Education's final earnings-accountability / gainful-employment rule was **not** among the 14. Education never saw an FR row for that rule, so rank 3 could not cite it. This tree's `verticals.yaml` still has no education vertical; the routing defect is the untargeted title-keyword hints, not a missing education scout in this worktree.

## 4. Duplicated bank

This tree's `bank_groups` keys on the **first** vertical only, and Today has no All / filter UI. A two-vertical question appears once, under its first tag.

CP's live read of run 20 showed ranks 6, 7 and 8 twice. That is what happens if All is the concatenation of per-vertical lists and a question is filed under every tag. U4 will add an explicit All (once, both tags) and a vertical filter (still under each of its verticals).

## 5. Near-miss selection

`sample_near_miss_pairs` keeps curated questions from adjacent days, scores `_share_kind` (same intersection / same vertical set / any shared vertical / none), then ranks by **content-token overlap descending**. It always returns up to three pairs when any survivors exist. It does not look at shared URLs, shared briefs, or named terms.

That rule prefers pairs that already look alike in words. A paraphrase has low overlap by definition, so the sample on run 20 (0–5% shared words, plainly different questions) is the expected output of the current ranker, not a fluke.
