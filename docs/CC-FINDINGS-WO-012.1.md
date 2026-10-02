# CC findings — WO-012.1

Verify: `docs/CC-VERIFY-WO-012.1.md` (posted before this code). Built on `fc052cc` (WO-014 slice A).

## Built

| Item | Where | Tests |
|---|---|---|
| F1 FR official slugs | `swarm/sources/federal_register.py`, `verticals.yaml` | `test_federal_register_request_matches_recorded_valid_agencies` |
| F1 GDELT 5.5s pace + named 429 | `swarm/sources/gdelt.py` | `test_gdelt_is_paced_and_names_a_lasting_429` |
| F1 ReliefWeb v2, no invented appname | `swarm/sources/reliefweb.py` → `needs key` | registry `reliefweb_appname` |
| F1 CFTC newest-first + market `$where` | `swarm/sources/cftc.py` | `test_cftc_query_is_newest_first_for_the_named_market` |
| F2 rivals vs commentators | `swarm/desk/classify.py` | `test_rivals_versus_commentators` |
| F3 absence needs 3 searches | `none_found` | `test_absence_needs_three_searches` |
| F3 prospects carry links | `prospects_with_links` | `test_prospects_carry_links` |
| F4 ≤2 pages/claim, 12s, labelled | `swarm/desk/pages.py` | `test_pages_read_are_labelled` |
| F5 `DESK_MODEL` from env | `settings.desk_model`, desk calls | `test_desk_model_comes_from_the_environment` |
| Lock-guard | `--refuse-if-locked` on web preDeploy | `test_refuse_if_locked_fails_deploy_when_a_run_holds_the_lock` |
| Voyage-empty copy | Archive Search memory | `test_search_memory_names_missing_voyage_key` |

## Findings (not built around)

1. **Brave volume.** F2+F3 add rival and prospect queries on top of two wordings per claim. Do not add a second Brave limiter.
2. **ReliefWeb stays dark** until the Operator pastes a pre-approved `RELIEFWEB_APPNAME`. An invented `question-engine` appname 403s.
3. **F5 is not cheaper.** `DESK_MODEL=claude-opus-5-5` raises desk $ versus run 25's fable-5 cards. Title "lower cost" referred to fewer wasted source calls, not the desk model.
4. **Lock-guard does not start a run** and does not close orphans while the lock is live. A stale lock (7200s) does not block a deploy.
5. **Search memory still increments the daily cap** when the Voyage key is missing. The page names the missing key instead of "Nothing in memory matches."

## Do not deploy while a run holds the lock

Merge only after `held_run_id()` is empty (or the lock is stale). Web preDeploy then prints `REFUSE_DEPLOY ok` and continues repair / orphans / memory backfill.
