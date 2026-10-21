# 100-review cost and runtime calculator

Generated 2026-10-21T02:41:09+00:00 by offline replay (`python -m cost.calculator replay`). No API key or model call is used. Rate multiplier: **2.0**. Rates: `rates.csv`.

## Measured pilot (real calls on `cost_100.csv`, unchanged)

- Input: `cost_100.csv`, sha256 `c884ac3b9be5066995d5063f96ad9af6e5e082975788c1684c4f6b6ea661dd0e` (manifest `c884ac3b...dd0e`: match); 100 IDs; 100 unique texts.
- Cold run `pilot-cold-20261021T002406Z` started 2026-10-21T00:24:06+00:00 with an **empty result cache** and **1 worker**; warm run `pilot-warm-20261021T002406Z` reused the saved cache.
- Cold statuses: {'completed': 100}. Warm result-cache hits: 100 of 100; new enrichment calls in warm run: **0**; downstream calls in warm run: 0.

| Run | Wall-clock s | API spend USD | Local compute USD (est.) | Cost / 1,000 input rows | Cost / completed record | Throughput rows/min |
|---|---|---|---|---|---|---|
| cold | 51.75 | 0.073967 | 0.000288 | 0.739669 | 0.00073967 | 115.9 |
| warm | 0.04 | 0.000000 | 0.000000 | 0.000000 | 0.00000000 | 150000.0 |

### By stage (cold run)

| Stage | Provider | Model | Effort / thinking | Prompt+schema | Batch size | Workers | Requests ok | Failed attempts | Retries | Reviews sent | Uncached in | Cache write | Cache read | Output | USD | Stage wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| enrich | anthropic | `claude-haiku-5-5` | low / disabled | enrich-v1+schema-v1 | 50 | 1 | 3 | 0 | 1 | 101 | 5,224 | 0 | 10,701 | 8,910 | 0.010169 | 28.90 |
| verify | anthropic | `claude-haiku-5-5` | low / disabled | verify-v1+schema-v1 | 50 | 1 | 1 | 0 | 0 | 20 | 1,061 | 1,150 | 0 | 957 | 0.001457 | 3.27 |
| group | anthropic | `claude-haiku-5-5` | low / disabled | group-v1+schema-v1 | 1 | 1 | 1 | 0 | 0 | 0 | 3,393 | 715 | 0 | 1,550 | 0.002407 | 6.03 |
| memo | anthropic | `claude-sonnet-5-5` | low / disabled | memo-v1+schema-v1 | 1 | 1 | 1 | 2 | 2 | 0 | 5,056 | 1,526 | 0 | 1,604 | 0.059934 | 13.02 |
| ingest+materialize+rank (code) | local | - | - | - | - | 1 | - | - | - | - | - | - | - | - | 0 API | 0.03 |

Summed call durations (cold): 50.10s vs wall clock 51.75s (one worker, so they are close; with overlap they would not be).
Verification sample declared: 20 reviews. Fallback quota: max(1, 0.5% of texts).

### Rates used (editable `cost/rates.csv`, standard tier, per million tokens)

| Model | Item | USD / M tokens | Source | Checked |
|---|---|---|---|---|
| claude-haiku-5-5 | cache_read | 0.0200 | https://www.eesel.ai/blog/claude-haiku-5-5-pricing | 2026-10-20 |
| claude-haiku-5-5 | cache_write_5m | 0.2500 | https://www.eesel.ai/blog/claude-haiku-5-5-pricing | 2026-10-20 |
| claude-haiku-5-5 | input | 0.2000 | https://www.eesel.ai/blog/claude-haiku-5-5-pricing | 2026-10-20 |
| claude-haiku-5-5 | output | 1.0000 | https://www.eesel.ai/blog/claude-haiku-5-5-pricing | 2026-10-20 |
| claude-sonnet-5-5 | cache_read | 0.2000 | https://computingforgeeks.com/claude-haiku-5-5-released-features-benchmarks/ | 2026-10-20 |
| claude-sonnet-5-5 | cache_write_5m | 5.0000 | https://computingforgeeks.com/claude-haiku-5-5-released-features-benchmarks/ | 2026-10-20 |
| claude-sonnet-5-5 | input | 4.0000 | https://computingforgeeks.com/claude-haiku-5-5-released-features-benchmarks/ | 2026-10-20 |
| claude-sonnet-5-5 | output | 20.0000 | https://computingforgeeks.com/claude-haiku-5-5-released-features-benchmarks/ | 2026-10-20 |

Formula: `item_cost = billed_units x (usd_per_million / 1,000,000)`; items are mutually exclusive (uncached input, cache write, cache read, output). Thinking is disabled, so no reasoning tokens are billed separately. Per-call items are in `usage.csv`, joined to `pilot_calls.jsonl` by `request_id`.

## Full-run projection

Measured enrichment unit cost: $0.00010169 per distinct text (100 texts, 2 first-pass requests). Tokens/text: uncached_input 52.2, cache_write 0.0, cache_read 107.0, output 89.1.
Measured retry rate 0.010 (share of texts re-sent once; already inside the measured unit cost, so the base case adds nothing extra and the conservative case adds the difference); failed-attempt rate 0.000; fallback rate 0.0000; fallback cost per text (estimate) $0.01298; fixed group+memo $0.0623 added once.

Controls: budget **$25.0**, output cap 8000 tokens/request, max workers 8, 50 requests/min, fallback max fraction 0.005.

| Scenario | Texts | Case | Retry | Enrich USD | Verify (n / USD) | Fixed USD | **API total USD** | Local USD est. | Hours | Limit | Budget |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Full corpus, no exact-text reuse | 660,609 | base | 0.010 | 67.18 | 2,000 / 0.15 | 0.062 | **67.38** | 0.157 | 7.84 | workers | **OVER BUDGET** |
| Full corpus, no exact-text reuse | 660,609 | conservative | 0.050 | 128.05 | 2,000 / 0.15 | 0.062 | **128.27** | 0.163 | 8.15 | workers | **OVER BUDGET** |
| Full corpus, exact-text reuse | 484,189 | base | 0.010 | 49.24 | 2,000 / 0.15 | 0.062 | **49.44** | 0.115 | 5.75 | workers | **OVER BUDGET** |
| Full corpus, exact-text reuse | 484,189 | conservative | 0.050 | 93.86 | 2,000 / 0.15 | 0.062 | **94.07** | 0.120 | 5.98 | workers | **OVER BUDGET** |
| Declared scope sample:100000 (reuse) | 78,099 | base | 0.010 | 7.94 | 1,562 / 0.11 | 0.062 | **8.12** | 0.019 | 0.95 | workers | ok |
| Declared scope sample:100000 (reuse) | 78,099 | conservative | 0.050 | 15.14 | 2,000 / 0.15 | 0.062 | **15.35** | 0.020 | 0.99 | workers | ok |

Every scenario accounts for all 660,622 rows (13 empty texts quarantined). The no-reuse row classifies every one of 660,609 nonempty rows separately; the reuse rows send each distinct text once (484,189 for the full corpus).

## Notes and unknowns

- API spend is computed from provider-reported usage; it has not been reconciled against the Anthropic Console invoice (delayed billing) - compare `api_usd` with the Console usage page for the pilot date.
- Local compute is a rough labelled assumption; dashboard hosting uses free tiers and is outside API spend.
- Batch API pricing (50% off) is not used; it would trade turnaround time for price and is shown only in `rates.csv`.
- Projections are estimates from a 100-review sample; rare failure modes and sustained rate limits may differ.
