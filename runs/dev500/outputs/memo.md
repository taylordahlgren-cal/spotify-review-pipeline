# Next-quarter focus: billing/support (free tier and paywall) leads the specific areas

*Generated 2026-10-21T00:34:46.409+00:00 by `claude-sonnet-5-5` (prompt `memo-v1`) from saved aggregates only. Automated claim check: **pass**. Numbers carry claim IDs ([C..] = issue-level, checked in `claims.csv`; [T..] = product-area facts in `area_aggregates.csv`; [K..] = coverage).*

**Recommended priority area:** `billing_support`

Under the baseline rule (priority_score = complaint_count x mean_severity = severity_sum), the generic "other.general" issue ranks first at 113 [C04], but it is not a product area. Among specific areas, usability has the highest severity sum at 139 [T03], while billing_support is second at 124 [T09] and is driven by free tier limits and paywall, the top specific issue at 109 [C08] from 41 complaints [C05]. I recommend billing/support, because it has higher mean severity (2.695652 [T10]) than usability (2.241935 [T04]); usability is the close alternative, with ads at 61 [C12]. This is self-selected historical review evidence and expresses intent only.

## Supporting evidence

- Free tier limits/paywall is the top specific issue by priority score (109) and has 41 complaints. (issues `billing.free_tier_restrictions_paywall`; reviews `4966b59e-cf09-4881-b3ea-34fd4118a553`, `11ad400f-4487-4dfa-a9da-c8d624f4f107`, `21915fcd-9a35-48ba-b277-6296c4154603`)
- Generic dissatisfaction ranks first at 113 but is not actionable as a product area. (issues `other.general`; reviews `178c3b49-b689-4fe4-92a2-2257a58e6d95`)
- Billing_support severity sum is 124 across area records, with a higher mean severity than usability.

## Alternatives considered

- **usability** - Highest area severity sum (139) but lower mean severity (2.241935), with no severity 4+ records (0.0%); ads at 61 and the home redesign at 36 are the main issues. Strong runner-up.
- **playback** - Smaller volume (38 complaints) but severe: mean 3.052632 and 23.7% severity 4+. Crashes score 34 and stops 29. Worth a targeted stability fix.
- **access** - Small (9 complaints) but 88.9% severity 4+; login failure scores 23. A candidate for a small fix.
- **catalog** - Lower priority at severity sum 46.
- **downloads** - Lowest priority at severity sum 13.

## Recommended actions

- **Track free-tier paywall issue** - Pin the free tier/paywall priority score and complaint count as a headline tile.
- **Separate 'other' from areas** - Show other.general as a non-area row so it does not crowd out specific areas.
- **Add severity-4+ view** - Flag playback and access, which have high severe shares despite lower volume.

## Limitations

- Self-selected app-store reviews; not representative of all users.
- Cancellation language is expressed intent, not observed churn; no revenue or causal impact is estimated.
- Classification coverage: 500 records [K01] all completed [K02], 479 by model call [K03] and 21 by exact-text reuse [K04], so duplicates share one label.
- Usability leads billing/support on area severity sum, so the recommendation also weighs mean severity and a single top issue; the margin is modest.

## Baseline ranking used (top 10)

| Rank | Issue | Name | Complaints | Severity sum | Mean severity | Priority |
|---|---|---|---|---|---|---|
| 1 | `other.general` | General dissatisfaction with app | 58 [C01] | 113 [C02] | 1.948276 [C03] | 113 [C04] |
| 2 | `billing.free_tier_restrictions_paywall` | Free tier limits and premium paywall | 41 [C05] | 109 [C06] | 2.658537 [C07] | 109 [C08] |
| 3 | `usability.ads_interruptions` | Excessive ads interrupting listening | 30 [C09] | 61 [C10] | 2.033333 [C11] | 61 [C12] |
| 4 | `usability.ui_redesign_navigation` | Disliked home screen redesign | 16 [C13] | 36 [C14] | 2.250000 [C15] | 36 [C16] |
| 5 | `playback.crashes_or_wont_open` | App crashes or will not open | 10 [C17] | 34 [C18] | 3.400000 [C19] | 34 [C20] |
| 6 | `playback.stops_or_pauses` | Music stops or pauses randomly | 9 [C21] | 29 [C22] | 3.222222 [C23] | 29 [C24] |
| 7 | `usability.shuffle_queue_controls` | Shuffle and skip controls restricted | 10 [C25] | 28 [C26] | 2.800000 [C27] | 28 [C28] |
| 8 | `playback.connectivity_bluetooth_cast` | False no-internet error when connecting | 9 [C29] | 27 [C30] | 3.000000 [C31] | 27 [C32] |
| 9 | `access.login_failure` | Unable to log into account | 6 [C33] | 23 [C34] | 3.833333 [C35] | 23 [C36] |
| 10 | `catalog.missing_or_removed_content` | Songs and features removed or missing | 8 [C37] | 20 [C38] | 2.500000 [C39] | 20 [C40] |

Claim check problems: none
