# Golden-50 error analysis

**Labels:** `golden_50_labeled.csv`, hand-labelled by the student, unchanged after the comparison.
**Predictions:** the final 100k-scope run (`runs/final/outputs/records.jsonl.gz`).
**Metrics:** `golden_results.json`. **Per-case table:** `golden_cases.csv`.

The human labels were never used in prompts, examples, thresholds or routing. The golden texts were classified as part of the normal run.

## Headline (50 cases, all 50 with valid predictions)

| Field | Agreement | Notes |
|---|---|---|
| topic | 60% (30/50), macro-F1 0.49 | |
| intent | 78% (39/50), macro-F1 0.71 | |
| severity | 62% exact, 80% within 1, MAE 0.70 | |
| topic + intent + severity | 38% | joint agreement |
| sentiment | 86% within the predeclared ±0.3 tolerance, MAE 0.18 | 49 cases; one human label is blank |
| evidence quote | 100% exact substrings | 35 are the full short review |
| entities | 7 unsupported entities | the word is not in the text |
| needs_review | human flagged 11, model flagged 11, both flagged 4 | |
| ambiguous | 21 cases | human set needs_review or wrote a note |

Fifty cases is a small diagnostic sample, not a population accuracy estimate.

## Adjudication of the 31 cases with any disagreement

After the comparison, each disagreement was checked against the **shared course definitions** (GRADING_CONTRACT.md). The human labels stay exactly as recorded. This adjudication is a separate, post-hoc reading that explains the gap; it is not a corrected score.

| Category | Cases | What happened |
|---|---|---|
| Human label departs from a shared definition | 17 | Generic anger labelled 4-5, although the rubric says "angry language alone is insufficient" (`0c6ca545`, `657f1b77`, `1a41c7e1`, `9034d675`, `99b93e31`, `47428620`).<br>Generic praise given a specific topic, although general praise is `other` (`a70e8d3e`, `0d4f8b48`).<br>Ad complaints labelled playback, although ads are usability (`01d453b0`, `372d4e67`).<br>A bare boycott slogan labelled complaint/5, although the rubric says unclear (`5de7f95b`).<br>"Deleting this App" labelled complaint, although cancellation takes precedence (`3ddb3f4e`).<br>"Can't even open the app" labelled access, although won't-open is playback (`215463ae`).<br>A recommendations praise labelled usability (`de48c99b`).<br>A feature request labelled severity 2, although pure requests are 1 (`b58dd6f0`).<br>An Indonesian review ("lyrics sometimes missing") labelled unclear, where the model read it correctly as catalog (`46842184`).<br>A playback stop labelled 2 where the rubric's "degraded function" is 3 (`947821dc`). |
| Genuinely ambiguous | 11 | Short praise naming one quality ("very diverse", `b5ee7834`). Ad-free praise ("No ads at all!", `1fc8b08f`; "very less advertising", `2aa566c6`). Non-English or name-only text (`ac6cd66d`, `f4c8146a`). Mixed boycott + app hate (`8cc4fad4`). A loud-ad safety complaint, usability vs playback and 2 vs 5 (`46c0b49f`). Lyrics + seek problems (`8c0546b0`). Free-tier restrictions after an update (`dceb14e7`). Premium offline failure, 2 vs 4 (`ac4e860a`). "Forget it" as cancellation (`d2f3874f`). |
| Model error | 3 | `292ce26a`: a complaint about banned songs labelled `unclear`; it is at least a catalog complaint.<br>`723f07de`: a crash fixed by support labelled praise with severity 3, which is internally inconsistent, so code flagged it `needs_review`.<br>`283b5843`: a nonsensical "free dollar" message given topic billing. |

**What this means.**

- Most raw disagreement comes from applying the shared definitions differently, especially severity for generic anger and the topic for generic praise. It does not come from the model misreading text.
- The model follows the written rubric more literally than the human labeller did.
- The three clear model errors are low-volume patterns: political or content-ban complaints, resolved-issue narratives and nonsense text.
- With the same adjudication, the remaining model-vs-rubric disagreement is concentrated in the 11 genuinely ambiguous cases. Those are the ones `needs_review` should catch, and the model flagged only 4 of the human's 11 flags.

**Limitations.**

- One person labelled the golden set, and the same person adjudicated. No second labeller was available.
- The sentiment label for `991b6b3a` was left blank and is excluded from sentiment metrics only.
