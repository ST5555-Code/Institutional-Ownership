-- CP-5.1 candidate VIEW: cp5_unified_holdings_view
--
-- Read-only DRAFT. Not executed against the DB at recon time.
-- The recon's view-vs-CTE benchmark (cp_5_1_cte_candidate.py) inlines this
-- definition as a CTE per query for empirical timing; this .sql captures the
-- final shape that CP-5.1b would CREATE OR REPLACE if the chat-side spec lands
-- on the VIEW path.
--
-- Implements R5 modified rule (Bundle A §1.4 + matrix revalidation Verdict A):
--   per (top_parent_entity_id, ticker, cusip) triple at quarter='2025Q4':
--     thirteen_f          = SUM(holdings_v2.market_value_usd) climbed via
--                           inst_to_top_parent on entity_id
--     fund_tier_adjusted  = SUM(fund_holdings_v2.market_value_usd) climbed via
--                           Method A (entity_rollup_history JOIN, dm_v1) +
--                           inst_to_top_parent, EXCLUDING:
--                             - asset_category != 'EC' (predicate)
--                             - non-valid CUSIP rows
--                             - intra-family FoF
--     r5_aum              = GREATEST(thirteen_f, fund_tier_adjusted)
--     source_winner       = '13F_wins' / 'fund_wins'
--
-- Inst→top_parent climb is encoded as a recursive CTE bounded at hop=10
-- (Bundle B §2.1 max actual hop = 3). Cycle-safe via visited-set carried in
-- the recursive frame.
--
-- DEPENDS ON pre-execution clears: 21 cycle-truncated entity merges, 84K
-- loader-gap rows, Capital Group umbrella, Adams duplicate. CP-5.1b must
-- not ship before those.

CREATE OR REPLACE VIEW cp5_unified_holdings_view AS
WITH RECURSIVE
  -- Step 1: institution → top_parent climb (recursive over inst→inst control)
  inst_edges AS (
    SELECT er.child_entity_id, er.parent_entity_id
    FROM entity_relationships er
    JOIN entity_current pec ON pec.entity_id = er.parent_entity_id
    JOIN entity_current cec ON cec.entity_id = er.child_entity_id
    WHERE er.valid_to = DATE '9999-12-31'
      AND er.control_type IN ('control', 'mutual', 'merge')
      AND pec.entity_type = 'institution'
      AND cec.entity_type = 'institution'
  ),
  inst_climb (entity_id, top_parent_entity_id, hop) AS (
    SELECT ec.entity_id, ec.entity_id, 0
    FROM entity_current ec
    WHERE ec.entity_type = 'institution'
    UNION ALL
    SELECT ic.entity_id, ie.parent_entity_id, ic.hop + 1
    FROM inst_climb ic
    JOIN inst_edges ie ON ie.child_entity_id = ic.top_parent_entity_id
    WHERE ic.hop < 10
  ),
  inst_to_top_parent AS (
    -- Take the deepest hop per entity_id (= the actual top_parent)
    SELECT entity_id, top_parent_entity_id
    FROM inst_climb
    QUALIFY ROW_NUMBER() OVER (PARTITION BY entity_id ORDER BY hop DESC) = 1
  ),
  -- Step 2: fund → institution via decision_maker_v1 ERH (Method A)
  fund_to_inst AS (
    SELECT erh.entity_id AS fund_entity_id,
           erh.rollup_entity_id AS institution_entity_id
    FROM entity_rollup_history erh
    JOIN entity_current ec ON ec.entity_id = erh.entity_id
    WHERE erh.valid_to = DATE '9999-12-31'
      AND erh.rollup_type = 'decision_maker_v1'
      AND ec.entity_type = 'fund'
  ),
  fund_to_top_parent AS (
    SELECT fti.fund_entity_id,
           itp.top_parent_entity_id
    FROM fund_to_inst fti
    JOIN inst_to_top_parent itp ON itp.entity_id = fti.institution_entity_id
  ),
  -- Step 3: 13F leg (holdings_v2 climbed via inst_to_top_parent)
  thirteen_f AS (
    SELECT itp.top_parent_entity_id,
           h.cusip,
           h.ticker,
           SUM(h.market_value_usd) AS thirteen_f_aum
    FROM holdings_v2 h
    JOIN inst_to_top_parent itp ON itp.entity_id = h.entity_id
    WHERE h.is_latest = TRUE
      AND h.quarter = '2025Q4'
    GROUP BY itp.top_parent_entity_id, h.cusip, h.ticker
  ),
  -- Step 4: fund-tier leg (fund_holdings_v2 climbed via fund_to_top_parent)
  --   - asset_category = 'EC' (equity-class only)
  --   - cusip is_valid (excludes NA_lit/zeros_or_nines/NULL)
  --   - intra-family FoF excluded: held cusip resolves to a fund whose
  --     fund_to_top_parent matches the outer fund's top_parent
  fund_held_funds AS (
    -- For each (cusip), if cusip resolves to a fund entity_id via securities,
    -- map cusip → that fund's top_parent.
    SELECT s.cusip,
           ftp.top_parent_entity_id AS held_top_parent_eid
    FROM securities s
    JOIN entity_identifiers ei
      ON ei.identifier_type = 'cusip'
     AND ei.identifier_value = s.cusip
     AND ei.valid_to = DATE '9999-12-31'
    JOIN fund_to_top_parent ftp ON ftp.fund_entity_id = ei.entity_id
  ),
  fund_tier AS (
    SELECT ftp.top_parent_entity_id,
           fh.cusip,
           fh.ticker,
           SUM(fh.market_value_usd) AS fund_tier_aum
    FROM fund_holdings_v2 fh
    JOIN fund_to_top_parent ftp ON ftp.fund_entity_id = fh.entity_id
    LEFT JOIN fund_held_funds fhf
      ON fhf.cusip = fh.cusip
     AND fhf.held_top_parent_eid = ftp.top_parent_entity_id
    WHERE fh.is_latest = TRUE
      AND fh.quarter = '2025Q4'
      AND fh.asset_category = 'EC'
      AND fh.cusip IS NOT NULL
      AND fh.cusip NOT IN ('000000000', '999999999')
      AND fhf.cusip IS NULL  -- intra-family FoF excluded
    GROUP BY ftp.top_parent_entity_id, fh.cusip, fh.ticker
  )
-- Step 5: outer R5 dedup
SELECT
  COALESCE(tf.top_parent_entity_id, ft.top_parent_entity_id) AS top_parent_entity_id,
  ec.display_name                                            AS top_parent_name,
  COALESCE(tf.cusip, ft.cusip)                               AS cusip,
  COALESCE(tf.ticker, ft.ticker)                             AS ticker,
  COALESCE(tf.thirteen_f_aum, 0)                             AS thirteen_f_aum,
  COALESCE(ft.fund_tier_aum, 0)                              AS fund_tier_aum,
  GREATEST(COALESCE(tf.thirteen_f_aum, 0),
           COALESCE(ft.fund_tier_aum, 0))                    AS r5_aum,
  CASE
    WHEN tf.thirteen_f_aum IS NULL THEN 'fund_only'
    WHEN ft.fund_tier_aum  IS NULL THEN '13F_only'
    WHEN tf.thirteen_f_aum >= ft.fund_tier_aum THEN '13F_wins'
    ELSE 'fund_wins'
  END                                                        AS source_winner
FROM thirteen_f tf
FULL OUTER JOIN fund_tier ft
  ON tf.top_parent_entity_id = ft.top_parent_entity_id
 AND tf.cusip                = ft.cusip
LEFT JOIN entity_current ec
  ON ec.entity_id = COALESCE(tf.top_parent_entity_id, ft.top_parent_entity_id)
;
