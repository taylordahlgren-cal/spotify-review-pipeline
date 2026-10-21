# Next-quarter focus: billing/support (free-tier restrictions)

*Generated 2026-10-21T00:24:58.385+00:00 by `claude-sonnet-5-5` (prompt `memo-v1`) from saved aggregates only. Automated claim check: **pass**. Numbers carry claim IDs ([C..] = issue-level, checked in `claims.csv`; [T..] = product-area facts in `area_aggregates.csv`; [K..] = coverage).*

**Recommended priority area:** `billing_support`

Using the baseline rule (priority_score = complaint_count x mean_severity), billing/support is the top specific area, with a severity sum of 26 [T03]. Its lead issue, free-tier features locked behind premium, ranks first with a priority score of 26 [C04] from 9 complaints [C01]. The generic "other" issue ranks second at 23 [C08], but it is not a product area. Playback (25 [T09]) and usability (25 [T15]) are close behind, so the margin is narrow.

## Supporting evidence

- Free-tier restrictions rank first: 9 complaints [C01], severity sum 26 [C02], mean severity 2.888889 [C03]. Users describe lost song choice and capped skips after an update. (issues `billing.free_tier_restrictions_paywall`; reviews `d146397f-4a94-4980-be00-ae9212eca3a7`, `21915fcd-9a35-48ba-b277-6296c4154603`)
- Billing/support accounts for 18.0% of ranked records [T05] and includes 2 cancellation-language records [T02]. This is expressed intent only, not observed churn. (issues `billing.free_tier_restrictions_paywall`; reviews `a78d831a-69f4-428a-9235-cfdd9775c509`)
- The generic 'other' issue ranks second (23 [C06]). It names no specific problem, so it is acknowledged but not actionable as an area. (issues `other.general`; reviews `45c561b9-cc47-4d80-95d3-f0d20bc84af3`)

## Alternatives considered

- **playback** - A close second by severity sum (25 [T09]) with the highest mean severity among the big areas (3.125000 [T10]). 25.0% of its records are severity 4+ [T12]. Crashes score 8 [C20]. Consider it if reliability outweighs the baseline ranking.
- **usability** - It has the most complaints of the specific areas (11 [T13]) but lower mean severity (2.272727 [T16]). Ads interruptions score 12 [C12].
- **access** - Login failure is severe (mean 4.000000 [C15]) but low volume (2 complaints [C13]), with a score of 8 [C16]. It suits a targeted fix, not a quarter-long focus.
- **catalog** - Lower priority, with a severity sum of 11 [T27].
- **downloads** - Lower priority, with a severity sum of 6 [T39].

## Recommended actions

- **Track free-tier restriction complaints** - Add a trend tile for the free-tier paywall issue, ranked by priority score.
- **Show playback as a watch item** - Show playback severity 4+ share next to the baseline ranking, since the gap to billing/support is small.
- **Break down the 'other' bucket** - Add a review queue to find specific themes inside generic dissatisfaction.

## Limitations

- This is self-selected, historical app-store review evidence from a small sample of 100 records [K01], all classified [K02].
- Cancellation language is expressed intent, not churn. No revenue or causal impact is estimated.
- Duplicate texts share one model label, which may inflate counts.
- The gaps between billing/support, playback and usability are small, so the ranking is sensitive to the severity labels.

## Baseline ranking used (top 10)

| Rank | Issue | Name | Complaints | Severity sum | Mean severity | Priority |
|---|---|---|---|---|---|---|
| 1 | `billing.free_tier_restrictions_paywall` | Free tier features locked behind premium | 9 [C01] | 26 [C02] | 2.888889 [C03] | 26 [C04] |
| 2 | `other.general` | General dissatisfaction with app updates | 12 [C05] | 23 [C06] | 1.916667 [C07] | 23 [C08] |
| 3 | `usability.ads_interruptions` | Too many ads interrupting playback | 6 [C09] | 12 [C10] | 2.000000 [C11] | 12 [C12] |
| 4 | `access.login_failure` | Cannot log in to account | 2 [C13] | 8 [C14] | 4.000000 [C15] | 8 [C16] |
| 5 | `playback.crashes_or_wont_open` | App crashes or stuck on loading | 2 [C17] | 8 [C18] | 4.000000 [C19] | 8 [C20] |
| 6 | `playback.other` | Cannot seek back or repeat sections | 2 [C21] | 6 [C22] | 3.000000 [C23] | 6 [C24] |
| 7 | `playback.stops_or_pauses` | Playback stops or fails to start | 2 [C25] | 6 [C26] | 3.000000 [C27] | 6 [C28] |
| 8 | `usability.shuffle_queue_controls` | Shuffle plays randomly and skips are capped | 2 [C29] | 6 [C30] | 3.000000 [C31] | 6 [C32] |
| 9 | `catalog.lyrics` | Lyrics missing or inconsistently shown | 2 [C33] | 4 [C34] | 2.000000 [C35] | 4 [C36] |
| 10 | `catalog.missing_or_removed_content` | Expected songs missing from catalog | 2 [C37] | 4 [C38] | 2.000000 [C39] | 4 [C40] |

Claim check problems: none
