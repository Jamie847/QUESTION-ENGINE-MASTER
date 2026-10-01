# CC Findings — WO-008 empty lenses

**From:** CC · **Date:** 2026-10-01 · **Code measured:** `e070c6c` (run 20) · **Branch:** `cursor/wo008-empty-lenses-84ea`

The two extra lenses were not approved. They are not in this branch.

## Verify

Run 20: completed, `$1.457`, 10 of 10 model calls `ok=true`. Questions: contrarian 8 model-written and curated; opportunity 6 template (4 duplicate, 2 killed); second-order 6 template, all killed.

### 1. Cause of the two silent lenses

| Call | Lens | ok | output tokens | `questions` type | questions inside | validation drops |
|---|---|---|---|---|---|---|
| 47 | Contrarian | true | 2158 | array | 8 | 0 |
| 48 | Second-Order | true | 1876 | **string** | 8 | all dropped before validation |
| 49 | Opportunity | true | 1990 | **string** | 8 | all dropped before validation |

The string is a complete JSON object, `{"questions":[...]}`, ending in `brief_refs`. Output tokens are about half of the 4,000 `max_tokens` limit, so this is not a cut-off reply. Stop reason was not stored on `e070c6c`. A `max_tokens` stop would have landed near 4,000 output tokens. These did not.

Both inner payloads would have passed validation: 8 questions each, text length, coverage, and decay all legal, 0 would-drop. Unknown labels were not the discard. The smith did `for raw in data.get("questions")`, and a string iterates as characters. Every character throws, `out` stays empty, and `return out or None` fills the lens with templates. The call stays `ok=true`.

Ruled out, in the order the order asked:

- Truncation. Not the cause on run 20.
- Validation drops for a bad `intersection_ref`. Already unlinked at HEAD, and the contrarian array lost nothing. The other two lenses never reached validation.
- The model returned zero questions. It returned 8 per lens, wrapped as a string.

The same string shape appears on earlier smith calls: run 15 opportunity; runs 17 and 18 second-order and opportunity; run 19 second-order. Run 16's three smith payloads were arrays.

### 2. Caps at HEAD

`e070c6c` does not slice `briefs[:16]` or `intersections[:10]`. That slice was the `8b7f18f` behavior. Run 20 sent the briefs it had: 35, in id order ai 6, business 7, education 6, health 8, science 8. The model cited `B32`, which is a science brief, so all five verticals were in the prompt. `agent_calls.input_text` is still capped at 8,000 characters (about 12,780 input tokens were actually sent), so the stored prompt alone cannot show the later briefs. The brief labels can.

L3 still adds a round-robin cap of 30 briefs and 12 intersections. Run 20 sent 35 briefs. A later prefix slice would drop science. The cap takes turns, so a vertical is not dropped for being last.

### 3. Silent fallbacks (`ok=true`, template used anyway)

Smiths, from the string-payload shape above: 1 call on run 15, 0 on 16, 2 on 17, 2 on 18, 1 on 19, 2 on 20.

Scouts: `briefs` was a string on run 15 (1 call), run 18 (2), and run 19 (1). Run 20's five scout calls were arrays, and all 35 briefs are `written_by=model:claude-sonnet-5`. Not fixed here.

Cross-pollinator: every stored payload starts as an intersections array. Run 20's 14 intersections are `written_by=model:claude-fable-5`. The stored text is capped at 8,000 characters, which is the log cap, not a failed parse. Not fixed here.

Curator: the only `ok=false` call in this set is run 19. Run 20's curator succeeded.

Runs 15–19 have null `written_by` because those rows predate the column. The payload shape is the evidence for them.

## Fixes

| Fix | What changed | Test | Red against the old code |
|---|---|---|---|
| L1 | Unwrap a stringified `questions` value before parsing. Do not raise `max_tokens`. | `test_l1_stringified_questions_are_kept` | The string was walked character by character and the lens became templates. |
| L2 | A keyed empty lens retries once. A cut-off reply asks for at most 4 on the retry. Still empty contributes nothing and the header names it (`second-order: no questions (empty)`). Templates remain only when no key is set. | `test_truncated_reply_retries_once_and_stays_empty`, `test_empty_lens_is_named_in_the_header`, `test_keyless_run_keeps_labelled_templates` | A keyed miss was filled with templates and the header did not name the lens. |
| L1 labels | A bad label stays unlinked. | `test_bad_label_is_unlinked_not_dropped` | A bad label used to be discarded, or to inherit `intersections[0]`. At HEAD it was already unlinked; the test keeps that from regressing when the string unwrap lands. |
| L3 | Round-robin briefs to 30 and intersections to 12. | `test_every_vertical_reaches_every_smith_inside_the_cap` | Sending the list in order includes `ONLY-EIGHTH-AI`. A prefix of 30 would drop `FIRST-education`. |
| L4 | `agent_calls.stop_reason`, `parsed_count`, `dropped_count`. Digest header per lens. A zero lens is also a warning. | `test_call_log_records_stop_reason_and_counts` | The call row had no stop reason and no parse counts. |

`max_tokens` stays 4,000. Raising it to 8,000 would not have changed run 20.

## Acceptance run

Not run. This branch is not deployed. Run 20 cost `$1.46`. The acceptance run is the next keyed run after migration, cron, then web, and not while a run is in progress. Pass is at least 5 model-written questions on each lens, or a header that says why a lens is empty.

## Two lenses

Not approved, not built. Run 20's smith calls cost `$0.071`, `$0.067`, and `$0.068`. Two more lenses are about `$0.14` per run, plus whatever they add to the curator prompt. The draft essences stay in the work order.

## Finding, not a workaround

The order's truncation remedy does not match run 20. The failure is a string where the schema asked for an array. The API accepted it, `ok` stayed true, and the template hid it. Scouts have the same string shape on some earlier runs. That stays out of scope, as the order said.
