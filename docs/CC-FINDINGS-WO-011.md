# CC findings — WO-011

Built on production `e11bd3b` / `5229554`. Verify is in `docs/CC-VERIFY-WO-011.md`.

## Mapping cause (from Verify)

CP's S1→run-wide-FR hypothesis was **false**. The Airbus-on-eight-cards bug was `prefer_primary_urls` padding `any_primary`, including `from_cites` against every signal in the run. K1 removes that pad. A source is kept only if it was in that scout's input. Display no longer remaps.

## Per item

| Item | Area | Tests | Assertion that went red against `e11bd3b` |
|---|---|---|---|
| K1 labels | already per-scout | `test_labels_resolve_per_scout` | Did **not** go red. Hypothesis failed. |
| K1 drop foreign | `primary.py`, `scout.py`, `honesty.from_cites` | `test_foreign_refs_dropped_and_brief_unlinked` | Uncited FR/arxiv primaries were prepended. Empty brief stayed "linked" on the card. |
| K1 honest count | `honesty.sources_linked_line` | `test_sources_linked_count_is_honest` | Counted `provenance==linked` on curated only. Run 22 read 10 of 10. |
| K1 past runs | `swarm/repair_links.py`, web `preDeployCommand`, marker `wo011_link_repair` | `test_link_repair_runs_once_and_records_the_marker` | Dashboard boot does **not** repair. This deploy's pre-deploy runs `--repair-links` once; `deploy_markers` records it. Later deploys print `skipped=1` and rewrite nothing. Truncated `agent_calls` → `unverified`. |
| K1 near-miss | `archivist` + existing U5 | uses `briefs_by_id` when briefs exist | Fake shared FR URLs cannot be created after the pad is gone. |
| K2 | `cross_pollinator.md` + `_llm` | `test_same_field_pairing_rejected` | `ai × ai` was accepted. Now rejected, `reject_reason=single field`, warning `Cross-pollinator passed over`. No padding. |
| K3 | `federal_register.py` + YAML agencies | `test_federal_register_drops_ad_and_renewal` | Airbus AD (Rule) and committee renewals (Notice) became signals. Type filter is RULE+PRORULE; ADs still dropped by title; `conditions[significant]=1` preferred, then filled. |
| K4 quietly | `smith.md` (already), `curator.md` title line, footer `Banned words: N` | existing U2 + footer | Smiths wrote the three run-22 hits; curator had no ban. Text is not edited after the fact. |
| K4 header | `main.py`, `today.html` | `test_f7_today_page_uses_display_tz` | `run_banner` + `format_run_stamp` + `digest.date`. Time prints once. |
| K5 movers | `movers.py`, EIA/FRED/CFTC | `test_movers_write_the_computed_number_or_nothing` | Adapter did not exist. Text contains the computed change and data date. Under-threshold series emit nothing. |
| K5 route | `gdelt.py`, `verticals.yaml` | `test_gdelt_item_reaches_geopolitics_scout` | GDELT items from a geopolitics query carry `vertical_hints=["geopolitics"]` and reach that scout. |

## Draft lists for the Operator to edit

All marked `# draft — tune after first run` in `verticals.yaml`.

**Geopolitics queries:** `sanctions export controls`, `ceasefire humanitarian corridor`. GDELT: `sanctions OR "export control" OR ceasefire`, `"taiwan strait" OR "red sea" OR "strait of hormuz"`. ReliefWeb: `humanitarian`, `displacement`. FR agencies: OFAC, BIS, State, Treasury.

**Commodities queries:** `crude inventory draw`, `industrial production commodities`. FR agencies: Energy, EPA, USDA, Interior.

**Series:** EIA `PET.WCRSTUS1.W` (US crude inventories), `PET.WTTSTUS1.W` (total petroleum). FRED `DCOILWTICO` (WTI), `PCOPPUSDM` (copper), `INDPRO`. CFTC crude non-commercial longs.

**Existing verticals — FR agency allow-lists (drafts):** Health FDA/CMS/HHS. Education ED. Business Treasury/SEC/CFTC/FTC. AI BIS/Commerce/NIST/FCC.

## Cost

Two more scouts (Geopolitics, Commodities). Run 22 was $1.57 with five scouts. The next Operator run is the measurement; this agent does not POST production `/api/run`.

## Deploy / acceptance

Not deployed from this session. Done means live `/healthz` shows the merged commit, then one run from Today's Run. CP reads the live page.

Repair on first web boot and via `python -m swarm.run_daily --repair-links`. After deploy, read those counts for the re-linked vs unverified report.

EIA and FRED stay `needs key` until the Operator adds the free keys. OpenAlex / Regulations.gov / SAM.gov keys are still missing. Set `DISPLAY_TZ` if UTC is wrong.
