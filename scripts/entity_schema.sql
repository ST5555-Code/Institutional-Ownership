-- =============================================================================
-- Entity MDM — Phase 1 Schema
-- =============================================================================
-- See ENTITY_ARCHITECTURE.md for full design context.
--
-- DuckDB note (2026-04-05): DuckDB 1.4.4 does not support partial unique
-- indexes (CREATE UNIQUE INDEX ... WHERE valid_to IS NULL). Per Design Decision
-- Log entry Apr 5 2026, this schema uses sentinel date '9999-12-31' instead of
-- NULL for the active row, and full unique constraints include valid_to in the
-- key. "Currently active" throughout this schema means valid_to = '9999-12-31'.
--
-- For constraints that depend on a boolean flag (one primary parent per child,
-- one preferred alias per entity), a nullable app-maintained key column is used
-- since DuckDB does not support partial indexes or constraints on generated
-- columns. DuckDB UNIQUE treats multiple NULLs as non-conflicting, so a UNIQUE
-- over (nullable_key, valid_to) allows many FALSE rows (NULL key) and at most
-- one TRUE row per target.
-- =============================================================================

-- Sequences (BIGINT PK via nextval() only — never MAX()+1)
CREATE SEQUENCE IF NOT EXISTS entity_id_seq START 1;
CREATE SEQUENCE IF NOT EXISTS relationship_id_seq START 1;

-- -----------------------------------------------------------------------------
-- entities — immutable master registry
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entities (
    entity_id       BIGINT PRIMARY KEY,
    entity_type     VARCHAR NOT NULL,  -- institution|fund|standalone_filer|sub_adviser|individual
    canonical_name  VARCHAR NOT NULL,
    created_source  VARCHAR NOT NULL,  -- PARENT_SEEDS|managers|fund_universe|adv_managers|manual
    is_inferred     BOOLEAN NOT NULL DEFAULT FALSE,  -- TRUE for synthetic Phase 1 seed data
    created_at      TIMESTAMP DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- entity_identifiers — CIK/CRD/SERIES_ID bridge (SCD Type 2)
-- -----------------------------------------------------------------------------
-- ux_identifier_active: one active mapping per (identifier_type, identifier_value)
-- globally. Enforced via full UNIQUE including valid_to sentinel.
CREATE TABLE IF NOT EXISTS entity_identifiers (
    entity_id         BIGINT NOT NULL REFERENCES entities(entity_id),
    identifier_type   VARCHAR NOT NULL,  -- cik|crd|series_id|lei|sec_file
    identifier_value  VARCHAR NOT NULL,
    confidence        VARCHAR NOT NULL
        CHECK (confidence IN ('exact','high','medium','low','fuzzy_match')),
    source            VARCHAR NOT NULL,
    is_inferred       BOOLEAN NOT NULL DEFAULT FALSE,
    valid_from        DATE NOT NULL DEFAULT DATE '2000-01-01',
    valid_to          DATE NOT NULL DEFAULT DATE '9999-12-31',
    created_at        TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (entity_id, identifier_type, identifier_value, valid_from),
    -- ux_identifier_active: one active (valid_to='9999-12-31') mapping per identifier globally
    UNIQUE (identifier_type, identifier_value, valid_to)
);

-- -----------------------------------------------------------------------------
-- entity_relationships — institutional graph (SCD Type 2)
-- -----------------------------------------------------------------------------
-- Types:
--   wholly_owned   — 100% subsidiary (control)
--   fund_sponsor   — registrant to adviser (control)
--   sub_adviser    — adviser to fund (advisory, not rollup)
--   parent_brand   — brand relationship (control)
--   joint_venture  — JV structure (is_primary=FALSE on secondary parents)
--
-- primary_parent_key: nullable column, = child_entity_id when is_primary=TRUE,
-- NULL otherwise. Enforces ux_primary_parent (one primary parent per child)
-- via UNIQUE(primary_parent_key, valid_to) since DuckDB allows multiple NULLs
-- in UNIQUE constraints. Application code MUST maintain this column in lockstep
-- with is_primary — see build_entities.py insert_relationship().
CREATE TABLE IF NOT EXISTS entity_relationships (
    relationship_id      BIGINT PRIMARY KEY,
    parent_entity_id     BIGINT NOT NULL REFERENCES entities(entity_id),
    child_entity_id      BIGINT NOT NULL REFERENCES entities(entity_id),
    relationship_type    VARCHAR NOT NULL
        CHECK (relationship_type IN ('wholly_owned','fund_sponsor','sub_adviser','parent_brand','joint_venture','mutual_structure')),
    control_type         VARCHAR NOT NULL
        CHECK (control_type IN ('control','advisory','brand','mutual')),
    is_primary           BOOLEAN NOT NULL DEFAULT FALSE,
    primary_parent_key   BIGINT,  -- app-maintained: = child_entity_id iff is_primary, else NULL
    confidence           VARCHAR NOT NULL
        CHECK (confidence IN ('exact','high','medium','low','fuzzy_match')),
    source               VARCHAR NOT NULL,
    is_inferred          BOOLEAN NOT NULL DEFAULT FALSE,
    valid_from           DATE NOT NULL DEFAULT DATE '2000-01-01',
    valid_to             DATE NOT NULL DEFAULT DATE '9999-12-31',
    created_at           TIMESTAMP DEFAULT NOW(),
    -- ux_er_active: no duplicate active relationship of same type for same pair
    UNIQUE (parent_entity_id, child_entity_id, relationship_type, valid_to),
    -- ux_primary_parent: at most one active primary parent per child
    UNIQUE (primary_parent_key, valid_to),
    -- is_primary and primary_parent_key must be consistent
    CHECK ((is_primary = TRUE AND primary_parent_key = child_entity_id)
        OR (is_primary = FALSE AND primary_parent_key IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_er_parent ON entity_relationships(parent_entity_id);
CREATE INDEX IF NOT EXISTS idx_er_child ON entity_relationships(child_entity_id);

-- -----------------------------------------------------------------------------
-- entity_aliases — all name variants with types
-- -----------------------------------------------------------------------------
-- preferred_key: nullable column, = entity_id when is_preferred=TRUE, NULL
-- otherwise. Enforces ux_ea_preferred (one preferred alias per entity) via
-- UNIQUE(preferred_key, valid_to). App code MUST maintain in lockstep.
CREATE TABLE IF NOT EXISTS entity_aliases (
    entity_id      BIGINT NOT NULL REFERENCES entities(entity_id),
    alias_name     VARCHAR NOT NULL,
    alias_type     VARCHAR NOT NULL
        CHECK (alias_type IN ('legal','brand','filing','normalized')),
    is_preferred   BOOLEAN NOT NULL DEFAULT FALSE,
    preferred_key  BIGINT,  -- app-maintained: = entity_id iff is_preferred, else NULL
    source_table   VARCHAR,
    is_inferred    BOOLEAN NOT NULL DEFAULT FALSE,
    valid_from     DATE NOT NULL DEFAULT DATE '2000-01-01',
    valid_to       DATE NOT NULL DEFAULT DATE '9999-12-31',
    created_at     TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (entity_id, alias_name, valid_from),
    -- ux_ea_preferred: at most one active preferred alias per entity
    UNIQUE (preferred_key, valid_to),
    CHECK ((is_preferred = TRUE AND preferred_key = entity_id)
        OR (is_preferred = FALSE AND preferred_key IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_ea_name ON entity_aliases(alias_name);
CREATE INDEX IF NOT EXISTS idx_ea_active ON entity_aliases(entity_id, valid_to);

-- -----------------------------------------------------------------------------
-- entity_classification_history — SCD Type 2 classification
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entity_classification_history (
    entity_id       BIGINT NOT NULL REFERENCES entities(entity_id),
    classification  VARCHAR NOT NULL,  -- passive|active|mixed|quant|hedge_fund|activist|unknown
    is_activist     BOOLEAN NOT NULL DEFAULT FALSE,
    confidence      VARCHAR NOT NULL
        CHECK (confidence IN ('exact','high','medium','low','fuzzy_match')),
    source          VARCHAR NOT NULL,
    is_inferred     BOOLEAN NOT NULL DEFAULT FALSE,
    valid_from      DATE NOT NULL DEFAULT DATE '2000-01-01',
    valid_to        DATE NOT NULL DEFAULT DATE '9999-12-31',
    created_at      TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (entity_id, valid_from),
    -- ux_ech_active: one active classification per entity
    UNIQUE (entity_id, valid_to)
);

-- -----------------------------------------------------------------------------
-- entity_rollup_history — persisted rollup outcomes (rollup as data, not logic)
-- -----------------------------------------------------------------------------
-- All aggregation queries join this table — never entity_relationships directly.
-- Two rollup worldviews coexist via rollup_type:
--   economic_control_v1 — fund sponsor / voting authority (default)
--   decision_maker_v1   — entity making active investment decisions (sub-adviser routing)
-- routing_confidence tracks data source quality:
--   high   — N-CEN, ADV Schedule A/B, self-rollup (authoritative)
--   medium — fuzzy match, name similarity, orphan scan, inferred
--   low    — manual, manual_umbrella_trust (needs periodic review)
-- review_due_date forces annual re-validation of low/medium routings via
-- validate_entities.py manual_routing_review gate.
CREATE TABLE IF NOT EXISTS entity_rollup_history (
    entity_id           BIGINT NOT NULL REFERENCES entities(entity_id),
    rollup_entity_id    BIGINT NOT NULL REFERENCES entities(entity_id),
    rollup_type         VARCHAR NOT NULL DEFAULT 'economic_control_v1',
    rule_applied        VARCHAR,  -- wholly_owned|fund_sponsor|priority_rank|self|ncen_sub_adviser|aicf_fix|intra_firm_collapsed
    source              VARCHAR,  -- N-CEN|ADV_SCHEDULE_A|ADV_SCHEDULE_B|self|orphan_scan|inferred|manual|manual_umbrella_trust
    confidence          VARCHAR NOT NULL
        CHECK (confidence IN ('exact','high','medium','low','fuzzy_match')),
    routing_confidence  VARCHAR DEFAULT 'high'  -- high|medium|low
        CHECK (routing_confidence IN ('high','medium','low')),
    review_due_date     DATE,  -- NULL for high confidence; annual review for low/medium
    valid_from          DATE NOT NULL DEFAULT DATE '2000-01-01',
    valid_to            DATE NOT NULL DEFAULT DATE '9999-12-31',
    computed_at         TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (entity_id, rollup_type, valid_from),
    -- ux_rollup_active: one active rollup per (entity, type)
    UNIQUE (entity_id, rollup_type, valid_to)
);

CREATE INDEX IF NOT EXISTS idx_rollup_parent ON entity_rollup_history(rollup_entity_id, valid_to);

-- -----------------------------------------------------------------------------
-- entity_identifiers_staging — soft-landing queue for identifier conflicts
-- -----------------------------------------------------------------------------
-- Phase 2: replaces silent ON CONFLICT DO NOTHING in feeders. When a feeder
-- (fetch_ncen.py, ADV parser, long-tail resolver) wants to add an identifier
-- that collides with an existing active mapping, the attempted row lands here
-- for operator review instead of being silently dropped.
--
-- Review workflow: pending → promoted (merged to entity_identifiers) / rejected / duplicate.
-- Auto-promotion logic deferred to Phase 3.5.
CREATE SEQUENCE IF NOT EXISTS identifier_staging_id_seq START 1;

CREATE TABLE IF NOT EXISTS entity_identifiers_staging (
    staging_id          BIGINT PRIMARY KEY,
    entity_id           BIGINT NOT NULL REFERENCES entities(entity_id),
    identifier_type     VARCHAR NOT NULL,
    identifier_value    VARCHAR NOT NULL,
    confidence          VARCHAR NOT NULL
        CHECK (confidence IN ('exact','high','medium','low','fuzzy_match')),
    source              VARCHAR NOT NULL,
    conflict_reason     VARCHAR NOT NULL,  -- duplicate_active_mapping|entity_ambiguous|cross_feeder_disagreement|manual_review_requested
    existing_entity_id  BIGINT,            -- the entity that currently owns this identifier (NULL if ambiguous)
    review_status       VARCHAR NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending','promoted','rejected','duplicate')),
    reviewed_by         VARCHAR,
    reviewed_at         TIMESTAMP,
    notes               VARCHAR,
    created_at          TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_eis_pending ON entity_identifiers_staging(review_status, created_at);
CREATE INDEX IF NOT EXISTS idx_eis_identifier ON entity_identifiers_staging(identifier_type, identifier_value);
CREATE INDEX IF NOT EXISTS idx_eis_entity ON entity_identifiers_staging(entity_id);

-- -----------------------------------------------------------------------------
-- entity_overrides_persistent — survives --reset rebuilds
-- -----------------------------------------------------------------------------
-- Phase 3.5: manual corrections that must be replayed after every
-- build_entities.py --reset. Same format as the CSV upload to
-- POST /admin/entity_override, plus applied_at and still_valid.
-- build_entities.py replays all still_valid=TRUE rows after rebuild.
CREATE TABLE IF NOT EXISTS entity_overrides_persistent (
    override_id    BIGINT PRIMARY KEY DEFAULT nextval('identifier_staging_id_seq'),
    entity_cik     VARCHAR,          -- CIK of the target entity (used to re-resolve entity_id after rebuild)
    action         VARCHAR NOT NULL,  -- reclassify|alias_add|merge
    field          VARCHAR,
    old_value      VARCHAR,
    new_value      VARCHAR NOT NULL,
    reason         VARCHAR,
    analyst        VARCHAR,
    still_valid    BOOLEAN NOT NULL DEFAULT TRUE,
    applied_at     TIMESTAMP DEFAULT NOW(),
    created_at     TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_eop_valid ON entity_overrides_persistent(still_valid);

-- -----------------------------------------------------------------------------
-- entity_current — denormalized current-state view
-- -----------------------------------------------------------------------------
-- "Currently active" throughout this view means valid_to = '9999-12-31'.
-- Phase 4 upgrades this to a MATERIALIZED VIEW with REFRESH in run_pipeline.sh.
CREATE OR REPLACE VIEW entity_current AS
SELECT
    e.entity_id,
    e.entity_type,
    e.created_at,
    COALESCE(ea.alias_name, e.canonical_name) AS display_name,
    ech.classification,
    ech.is_activist,
    ech.confidence AS classification_confidence,
    er.rollup_entity_id,
    er.rollup_type
FROM entities e
LEFT JOIN (
    SELECT entity_id, alias_name
    FROM entity_aliases
    WHERE is_preferred = TRUE AND valid_to = DATE '9999-12-31'
) ea ON e.entity_id = ea.entity_id
LEFT JOIN entity_classification_history ech
    ON e.entity_id = ech.entity_id
    AND ech.valid_to = DATE '9999-12-31'
LEFT JOIN entity_rollup_history er
    ON e.entity_id = er.entity_id
    AND er.rollup_type = 'economic_control_v1'
    AND er.valid_to = DATE '9999-12-31';
