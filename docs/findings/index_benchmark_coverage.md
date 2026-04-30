# Index Benchmark Coverage — Reference for `index-benchmark-validation`

**Date:** 2026-04-30
**Source:** `fund_universe` naming sweep (current quarter)
**Roadmap:** ROADMAP.md → P2 → `index-benchmark-validation`
**Builds on:** Item 8 (2026-04-09) — `index_proxies`, `fund_index_scores`, `benchmark_weights` tables already in prod.

## Coverage summary

- **27 benchmarks** identified from fund-name keywords in `fund_universe`.
- **3,599 funds** ($4.6T AUM) carry "Index" or "ETF" in their name but do not yet map to a specific benchmark — these are the Phase 3 correlation targets.
- **11 GICS sector benchmarks** identified (Phase 4).

## Top broad-market benchmarks (selected)

| Benchmark | Funds | AUM | Representative fund (Phase 1 reference portfolio) |
| --- | ---: | ---: | --- |
| S&P 500 | 227 | $4.0T | Vanguard 500 Index (`VFIAX` / S&P 500 reference) |
| Total Stock Market | 14 | $2.7T | Vanguard Total Stock Market Index (`VTSAX`) |
| Nasdaq 100 | 98 | $579B | Invesco QQQ Trust |

> Full 27-benchmark table to be populated as Phase 1 ships (`benchmark_portfolios` seed). Pick exactly one representative fund per benchmark; record `series_id` and `ticker` for the source.

## GICS sector benchmarks (Phase 4)

11 sector benchmarks identified, with AUM concentrations:

| Sector | AUM (sector-fund total) |
| --- | ---: |
| Information Technology | $151B |
| Financials | $70B |
| Health Care | $63B |
| Energy | $49B |
| (7 remaining sectors) | — |

Sector funds will feed into the Sector Rotation tab once Phase 4 lands.

## Unmatched cohort (Phase 3 target)

- **3,599 funds** / **$4.6T AUM** carry "Index"/"ETF" in their canonical name but were not pinned to one of the 27 benchmarks by name match alone.
- These are the Phase 3 correlation classification target: compute overlap % + weight correlation against each Phase 1 reference portfolio, then assign by the ≥90% / ≤60% thresholds.

## Classification rules (from roadmap)

| Overlap | Weight correlation | Decision |
| --- | --- | --- |
| > 90% | > 0.95 | Confirmed **passive** (mapped to that benchmark) |
| < 60% | — | Confirmed **active** |
| 60–90% | any | **Review** queue |

## Notes

- Phase 1 deliverable: `benchmark_portfolios(benchmark_name, series_id, quarter, ticker, weight)` — supersedes `index_proxies` once parity verified against the existing 8-index cross-validation from Item 8.
- Phase 2 deliverable: `fund_index_correlation(series_id, benchmark_name, quarter, overlap_pct, weight_corr)` — supersedes `fund_index_scores`.
- External weight validation (Phase 3 footnote): periodically reconcile representative-fund weights against published S&P / index-provider factsheets to catch drift in the reference portfolios themselves.
