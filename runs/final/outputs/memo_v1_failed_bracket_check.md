# Next-quarter focus: billing/support (free-tier limits) leads on baseline priority

*Generated 2026-10-21T01:37:33.287+00:00 by `claude-sonnet-5-5` (prompt `memo-v1`) from saved aggregates only. Automated claim check: **pass**. Numbers carry claim IDs ([C..] = issue-level, checked in `claims.csv`; [T..] = product-area facts in `area_aggregates.csv`; [K..] = coverage).*

**Recommended priority area:** `billing_support`

Under the baseline rule (priority_score = complaint_count x mean_severity), the generic "other" bucket ranks first at 78701 [C04] but is not a product area. Among specific areas, the top issue is free tier limits and paywalled features, with a priority score of 18916 [C08] from 6975 complaints [C05]. I recommend billing/support, with usability (ads, 16481 [C12]) as the close alternative. This is self-selected historical review evidence and expresses intent, not churn.

## Supporting evidence

- Billing_support has the highest area severity_sum among specific areas after usability's 30785 [T09]; it is 23467 [T15], with the highest cancellation count of any area at 1924 [T14]. Its leading issue (free-tier restrictions) is the top specific issue at 18916 [C06]. (issues `billing.free_tier_restrictions_paywall`; reviews `86151d66-9d56-43ea-8514-4a33c1646656`, `67788933-9b7d-4e82-a7df-cb5b1a95dabd`)
- Mean severity for the free-tier issue is 2.711971 [C07], above ads at 2.040991 [C11]. (issues `billing.free_tier_restrictions_paywall`, `usability.ads_interruptions`; reviews `86151d66-9d56-43ea-8514-4a33c1646656`)

## Alternatives considered

- **usability** - Largest area by severity_sum at 30785 [T09], driven by ads at 16481 [C10] and shuffle/queue controls at 6674 [C14]. Many complaints overlap with free-tier restrictions, so scope with billing.
- **playback** - Smaller volume (severity_sum 17635 [T21]) but highest severity, with 17.7% [T24] rated 4+. Stops/pauses score 5618 [C18] and crashes 4794 [C22].
- **access** - Login failure scores 4333 [C26] with mean severity 3.882616 [C27]. 77.1% [T36] of access records are 4+. Volume is small, so it suits a targeted fix.
- **catalog** - Lower priority at 7457 [T27].
- **downloads** - Lowest priority at 3276 [T39].

## Recommended actions

- **Track free-tier restriction complaints** - Show the issue's priority score alongside its cancellation-intent mentions, 1636 [C-none].
- **Pair ads and free-tier views** - Show the two issues together because the complaints overlap in theme.
- **Add a severity-4+ watchlist** - Flag playback crashes and login failures, which are high severity but lower volume.

## Limitations

- Self-selected app-store reviews; not representative of all users.
- Coverage: 236894 [K02] of 660622 [K01] records were completed. 423728 [K03] were quarantined, mostly outside the declared classification scope (422667 [K06]).
- Exact-text reuse labels 159552 [K05] records, so duplicates share one label.
- Cancellation language is expressed intent, not observed churn. No revenue or causal estimates are made.
- The 'other' bucket holds 54.0% [T05] of ranked records and is not a product area.

## Baseline ranking used (top 10)

| Rank | Issue | Name | Complaints | Severity sum | Mean severity | Priority |
|---|---|---|---|---|---|---|
| 1 | `other.general` | General dissatisfaction and vague complaints | 39942 [C01] | 78701 [C02] | 1.970382 [C03] | 78701 [C04] |
| 2 | `billing.free_tier_restrictions_paywall` | Free tier limits and paywalled features | 6975 [C05] | 18916 [C06] | 2.711971 [C07] | 18916 [C08] |
| 3 | `usability.ads_interruptions` | Excessive ads interrupting listening | 8075 [C09] | 16481 [C10] | 2.040991 [C11] | 16481 [C12] |
| 4 | `usability.shuffle_queue_controls` | Shuffle forced and limited playback controls | 2435 [C13] | 6674 [C14] | 2.740862 [C15] | 6674 [C16] |
| 5 | `playback.stops_or_pauses` | Music stops or pauses unexpectedly | 1837 [C17] | 5618 [C18] | 3.058247 [C19] | 5618 [C20] |
| 6 | `playback.crashes_or_wont_open` | App crashes or fails to open | 1439 [C21] | 4794 [C22] | 3.331480 [C23] | 4794 [C24] |
| 7 | `access.login_failure` | Unable to log in to account | 1116 [C25] | 4333 [C26] | 3.882616 [C27] | 4333 [C28] |
| 8 | `usability.ui_redesign_navigation` | Confusing interface after redesign | 1659 [C29] | 3770 [C30] | 2.272453 [C31] | 3770 [C32] |
| 9 | `catalog.missing_or_removed_content` | Songs unavailable or only previews play | 1035 [C33] | 2501 [C34] | 2.416425 [C35] | 2501 [C36] |
| 10 | `playback.other` | Wrong songs and glitchy playback | 852 [C37] | 2368 [C38] | 2.779343 [C39] | 2368 [C40] |

Claim check problems: none
