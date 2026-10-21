# Shared label definitions, subtopics and examples

The pipeline uses the course's common labels exactly (see `data/GRADING_CONTRACT.md`). This page records how they were applied.
Examples are invented for illustration; none comes from the golden 50, whose human labels are never shown to a model.

## Primary topic (exactly one)

| topic | Definition | Applied examples |
|---|---|---|
| `access` | Login, signup, password, verification codes, being logged out, hacked/lost accounts | "Can't log in since the update" -> access / login_failure |
| `usability` | Navigation, controls, layout, UI redesigns, queue/playlist/library management, shuffle/repeat controls (when not described as a paywall), widgets, lock-screen/car controls, ad interruptions | "One ad after every song" -> usability / ads_interruptions |
| `playback` | Playback failure, music stopping by itself, crashes, won't open, lag, connection, Bluetooth/Connect, audio quality, battery/data/storage use | "Pauses randomly over Bluetooth" -> playback / connectivity_bluetooth_cast |
| `downloads` | Downloading, saved music, offline listening, disappearing downloads | "Downloads vanish offline" -> downloads / offline_mode_fails |
| `catalog` | Missing/removed songs or artists, search, discovery, recommendations, lyrics availability, podcasts/audiobooks content | "Love Discover Weekly" -> catalog / recommendations_algorithm (praise) |
| `billing` | Price, price increases, charges, refunds, subscriptions, trials, paywalls, premium entitlement, explicitly premium-only controls | "Free tier forces shuffle" -> billing / free_tier_restrictions_paywall |
| `support` | Contacting support and the support response | "Support never answered my ticket" -> support / no_response_or_unhelpful |
| `other` | General praise/criticism, unrelated content, no supported specific topic | "Best app ever" -> other / general |

Tie rules: choose the problem with the highest supported severity, then the first specific problem mentioned. For praise, the first
specific praised feature; general praise is `other`. A paid-plan mention alone is not billing (premium user + crash = playback;
subscription not activating = billing). Generic "bad app" = other + complaint; no defect is inferred.

## Optional subtopics (custom; used to form issue IDs `topic.subtopic`)

| topic | subtopics |
|---|---|
| access | login_failure, logged_out, signup_or_verification, password_reset, account_hacked_or_lost, other |
| usability | ads_interruptions, ui_redesign_navigation, shuffle_queue_controls, playlist_library_management, widgets_lockscreen_car, other |
| playback | stops_or_pauses, crashes_or_wont_open, lag_slow_loading, connectivity_bluetooth_cast, audio_quality_volume, battery_storage_resources, other |
| downloads | downloads_disappear, cannot_download, offline_mode_fails, other |
| catalog | missing_or_removed_content, search, recommendations_algorithm, lyrics, podcasts_audiobooks, other |
| billing | price_increase_cost, unexpected_charges_refunds, premium_not_recognized, free_tier_restrictions_paywall, plan_management_family_student, other |
| support | no_response_or_unhelpful, other |
| other | general, unrelated_or_unclear |

The subtopic list was fixed before the full run from domain knowledge of Spotify app-store complaints. A subtopic that does not
belong to the chosen topic is mapped to that topic's `other` in code and noted in the record (`subtopic_mapped_to_other`).

## Intent (precedence order)

1. `cancellation` - explicitly leaving, uninstalling, cancelling, switching, or threatening to. ("Uninstalling." / "Switching to YouTube Music")
2. `complaint` - negative experience, including mixed praise + criticism. ("good but the new layout is confusing")
3. `request` - desired change without a reported failure. ("Please add a sleep timer")
4. `praise` - positive only. ("Love it")
5. `unclear` - meaningless, unrelated, unreadable, bare boycott/political slogans without a product complaint or personal departure.

## Severity (from reported impact only)

| level | Meaning | Examples |
|---|---|---|
| 1 | No reported problem: praise, unclear, pure feature request | "Great app", "add a sleep timer" |
| 2 | Dislike, generic criticism, minor annoyance, cosmetic, too many ads, price grumbles with no functional loss | "Too many ads", "worst app" |
| 3 | Degraded/restricted function, some use or workaround remains | "Lags sometimes", "free tier is shuffle-only" |
| 4 | Clearly blocked core task | "Can't log in at all", "crashes on every launch" |
| 5 | Explicit serious financial, privacy or data harm | "Charged twice after cancelling", "account hacked, playlists gone" |

Stars, anger and capital letters do not establish severity; cancellation intent does not raise it. Code flags (never rewrites)
contradictions such as praise with severity > 1 by setting `needs_review=true` with reason `intent/severity inconsistent`.

## Other fields

- `sentiment`: -1.0 to 1.0, one decimal. Golden evaluation uses a predeclared tolerance of 0.3 plus MAE.
- `entities`: up to 4 features named in the text, in the review's wording. Evaluation counts entities that do not occur in the text.
- `evidence_quote`: shortest exact span supporting the label. The model may return `*` for reviews of 120 characters or fewer, which
  code replaces with the full original text. Code checks exact substring membership and only ever returns a slice of the source text
  (trimmed quotes or whitespace-only differences are mapped back onto the original characters; anything else is invalid and retried).
- `needs_review`: model prediction for ambiguous, missing-context, sarcastic or unreadable-language reviews; evaluated against the
  human flag, not treated as a correctness guarantee.
