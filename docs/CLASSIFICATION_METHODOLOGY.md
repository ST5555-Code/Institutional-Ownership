# Data Classification Methodology

_Last updated: April 20, 2026 — entity count refreshed to 26,535 (was 20,205 at Apr 9 baseline; +6,330 from DM14b/DM15 sub-adviser MDM buildout + 13D/G filer resolution Apr 17)._

SEC filings do not include investor type or strategy classifications. Every "Type" label in the platform is derived by us from multiple sources.

## Classification Pipeline

### entity_type on holdings_v2 (per-entity, used by all filters)

Resolution order:
1. `entity_classification_history` (26,535 entities, per `SELECT COUNT(*) FROM entity_current` 2026-04-20) — if classification != 'unknown', use it
2. ADV strategy inference via CRD link (3,254 entities) — hedge_fund, private_equity, quantitative override active/mixed/unknown
3. `manager_type` fallback — parent-level type from parent_seeds

### manager_type on holdings_v2 (parent-level, legacy)

All CIKs under the same parent inherit one type. Source: `parent_seeds` (110 curated parents) + keyword matching + ADV strategy. Retained for backward compatibility but not used by Active Only filters.

### is_actively_managed on fund_universe (fund-level)

Binary passive/active via name-pattern keywords: "Index", "ETF", "S&P", "Russell", "MSCI" = passive. Everything else = active. Source: `fix_fund_classification.py`.

## Classification Sources

| Source | Coverage | Confidence | Types Assigned |
|--------|----------|------------|----------------|
| Parent seeds | ~110 parents, ~45% of AUM | High | All types |
| ADV strategy_inferred | 3,254 entities (38%) | Medium-High | hedge_fund, private_equity, quantitative, passive, active |
| Entity classification_history | 26,535 entities (2026-04-20) | Varies (see confidence field) | All types |
| Keyword matching | Fallback for unmatched | Low | wealth_management, hedge_fund, PE |
| Manual review | ~177 entities >$10B | High | Corrected misclassifications |

## Type Taxonomy

| Type | Description | Confidence |
|------|-------------|------------|
| passive | Index funds, ETF providers (Vanguard, SSGA, Geode) | High — well-defined universe |
| active | Actively managed strategies — broadest bucket | Medium — includes unclassified |
| hedge_fund | Long/short, event-driven, macro (Citadel, DE Shaw, Millennium) | Medium — ADV + parent_seeds |
| quantitative | Systematic/algorithmic (Two Sigma, Renaissance, AQR) | Medium-High — distinctive strategies |
| activist | Holders with intent to influence (Carl Icahn, Elliott, Starboard) | High — curated list of 31 |
| mixed | Parent with both active and passive subsidiaries (JPMorgan, UBS) | Medium — parent-level assignment |
| wealth_management | Private wealth, trust companies, family offices | Medium |
| pension_insurance | Pension funds, insurance company investment arms | High — curated |
| SWF | Sovereign wealth funds (Norges Bank, GIC, ADIA) | High — curated |
| endowment_foundation | University endowments, charitable foundations | High — curated |
| private_equity | PE firms filing 13F (Blackstone, KKR, Apollo) | Medium — ADV sourced |
| strategic | Corporate treasury, strategic investors | Low — catch-all |
| venture_capital | VC firms with public holdings | Low — small AUM |
| multi_strategy | Multi-strategy platforms | Low — rare |

## Known Gaps

- ~6,633 entities classified as "unknown" in entity_classification_history (mostly standalone filers <$1B AUM)
- ~1,095 LOW confidence entities — need manual review with ADV cross-reference
- Family offices lack a dedicated type — split between hedge_fund and strategic
- Fund-level type does not inherit manager's richer classification (e.g., Citadel fund = "active" not "hedge_fund")
- entity_type was populated once at Phase 4 cutover — new entities from future pipeline runs will need classification
