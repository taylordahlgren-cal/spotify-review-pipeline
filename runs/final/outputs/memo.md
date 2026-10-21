# Next-quarter focus: billing/support (free-tier restrictions) leads the specific areas

*Generated 2026-10-21T02:51:36.989+00:00 by `claude-sonnet-5-5` (prompt `memo-v2`) from saved aggregates only. Automated claim check: **pass**. Numbers carry claim IDs ([C..] = issue-level, checked in `claims.csv`; [T..] = product-area facts in `area_aggregates.csv`; [K..] = coverage).*

**Recommended priority area:** `billing_support`

Under the baseline rule (priority_score = complaint_count x mean_severity), the generic "other.general" issue ranks first at 78701 [C04], but it is not a product area. Among specific areas, billing_support has the highest severity sum at 23467 [T15], and its top issue, free tier limits and paywalled features, scores 18916 [C08]. Usability is second at 30785 [T09] by area sum, but that is mostly driven by ads (16481 [C12]). I recommend billing_support, with usability ads as the runner-up.

## Supporting evidence

- Free-tier restrictions rank 2 overall with 6975 complaints [C05] and a priority score of 18916 [C08]. (issues `billing.free_tier_restrictions_paywall`; reviews `86151d66-9d56-43ea-8514-4a33c1646656`, `67788933-9b7d-4e82-a7df-cb5b1a95dabd`)
- Billing_support has the most cancellation mentions of any area at 1924 [T14], and mean severity of 2.674912 [T16]. This is expressed intent only, not observed churn. (issues `billing.free_tier_restrictions_paywall`)
- Ads interruptions rank 3 with a score of 16481 [C12], so there is a related free-tier experience theme. (issues `usability.ads_interruptions`; reviews `bd157456-e532-4177-b5b3-201ee893284f`)

## Alternatives considered

- **usability** - Largest area by severity sum, 30785 [T09], led by ads (16481 [C12]) and shuffle/queue controls (6674 [C16]). Strong runner-up, with lower mean severity of 2.240702 [T10].
- **playback** - Smaller volume, with a severity sum of 17635 [T21], but the highest severity among the large areas: mean 2.989490 [T22], with 17.7% rated severity 4+ [T24]. Stops/pauses score 5618 [C20] and crashes score 4794 [C24].
- **access** - Low volume (severity sum 6471 [T33]) but very severe: 77.1% rated severity 4+ [T36]. Login failure scores 4333 [C28]. Worth a targeted fix.
- **catalog** - Lower priority, with a severity sum of 7457 [T27].
- **downloads** - Lowest priority, with a severity sum of 3276 [T39].

## Recommended actions

- **Track free-tier restriction complaints** - Add a dashboard tile for the free-tier restrictions issue with its priority score and cancellation mentions.
- **Pair ads with paywall** - Show ads interruptions beside free-tier issues to review the free experience together.
- **Severity watchlist** - Keep a high-severity view for access and playback issues, since volume ranking understates them.
- **Show the 'other' share separately** - Display the generic complaints share, 54.0% [T05], apart from product areas.

## Limitations

- Self-selected, historical app-store reviews; not representative of all users.
- Only 236894 [K02] of 660622 [K01] records were classified. 423728 [K03] were quarantined, mostly as outside the declared classification scope (422667 [K06]).
- Exact-text reuse accounts for 159552 [K05] completed records, which share one model label, so duplicates may inflate counts.
- Cancellation language is expressed intent, not churn. No revenue or causal estimates are made.
- The ranking is by volume x severity, so low-volume, high-severity areas such as access rank lower.

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
