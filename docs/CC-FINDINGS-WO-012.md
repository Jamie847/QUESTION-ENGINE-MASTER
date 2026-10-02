# CC findings — WO-012

Verify: `docs/CC-VERIFY-WO-012.md` (posted before this code).

## Built

| Item | Commit area | Tests |
|---|---|---|
| D1 selection | `swarm/desk/select.py` | `test_selection_skips_unlinked_includes_saved_and_holds_the_cap` |
| D2 assay | `swarm/agents/desk.py` `name_claims` / `write_card` | `test_contradicted_premise_is_caught_and_card_continues` |
| D3 shapes | `swarm/config/shapes.yaml` | same card test |
| D4 card rules | `swarm/desk/validate.py` | numbers, rivals, prospects, empty profile |
| D5 Today + Opportunities + verdicts | `dashboard/` | `test_pursue_and_kill_need_a_why_and_redecide_keeps_history` |
| D6 assets | `swarm/desk/assets.py`, Taste page | `test_empty_assets_profile_is_named` |
| Optional stage / budget | `run_desk` reserve `$0.40` | `test_over_budget_skips_the_desk_and_names_it` |
| WO-010 fallback | `llm.agent = "desk"`, `judgment=True` | `test_desk_refusal_uses_wo010_fallback` |
| Assay this ceiling | `POST /api/questions/{id}/assay` | `test_assay_this_stops_at_daily_ceiling` |

Repair from WO-011 is unchanged: one-shot preDeploy, marker `wo011_link_repair`.

## Findings (not built around)

1. **Cited pages are not fetched.** Cards disclose snippet-only checks. See verify §5.
2. **Desk cost will likely exceed $0.30–0.60 / run** at two fable-5 calls × 3–5 cards. Footer shows actuals.
3. **Free Brave 1,000/month** does not cover fetch 14 + desk 30 on a daily run. Defaults stay as specified.
4. **A linked question can still carry an off-topic brief** (run 23 rank 4). The desk assays what it is handed.
5. **FR 400 / ReliefWeb 410 / GDELT 429 / missing EIA+FRED keys** are still dark. Out of this order.

## Acceptance

Needs a keyed production run on the merged commit. Pass: up to 3 cards (plus any saves), each with claim verdicts and links. CP reads the live page. Operator marks at least one verdict.
