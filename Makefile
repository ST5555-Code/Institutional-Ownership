# 13F Institutional Ownership — pipeline Makefile
#
# Single entry point for the quarterly refresh sequence. Every pipeline
# step is also runnable standalone. `DRY_RUN=1 make quarterly-update`
# prints the plan without executing anything.
#
# Individual steps use the production DB by default. For staging runs,
# invoke the underlying scripts directly with `--staging` — this Makefile
# is intentionally scoped to the production refresh sequence.

PY        := python3
SCRIPTS   := scripts
DB_PATH   := data/13f.duckdb

# DRY_RUN=1 → recipes echo what they would run instead of executing.
ifeq ($(DRY_RUN),1)
Q := @echo "[DRY RUN]"
else
Q :=
endif

.PHONY: help quarterly-update \
        fetch-13f fetch-nport fetch-dera-nport \
        build-entities compute-flows fetch-market \
        build-summaries build-classifications \
        backup-db validate \
        freshness status \
        fetch-13dg fetch-adv fetch-ncen fetch-finra-short \
        build-managers build-fund-classes build-cusip

help:
	@echo "13F pipeline targets:"
	@echo ""
	@echo "  Primary:"
	@echo "    make quarterly-update     — run the full 9-step quarterly sequence"
	@echo "    make status               — print last-run timestamps from data_freshness"
	@echo "    make freshness            — gate: fail if any critical table is stale"
	@echo ""
	@echo "  Individual pipeline steps (runnable standalone):"
	@echo "    make fetch-13f            — Step 1: holdings_v2 refresh"
	@echo "    make fetch-nport          — Step 2: fund_holdings_v2 via XML (legacy)"
	@echo "    make fetch-dera-nport     — Step 2 alt: fund_holdings_v2 via DERA ZIP"
	@echo "    make build-entities       — Step 3: entity MDM sync"
	@echo "    make compute-flows        — Step 4: investor_flows + ticker_flow_stats"
	@echo "    make fetch-market         — Step 5: market_data + securities"
	@echo "    make build-summaries      — Step 6: summary_by_parent"
	@echo "    make build-classifications— Step 7: manager / entity classifications"
	@echo "    make backup-db            — Step 8: EXPORT DATABASE backup"
	@echo "    make validate             — Step 9: validate_entities.py --prod"
	@echo ""
	@echo "  Supplementary:"
	@echo "    make fetch-13dg           — 13D/G beneficial ownership"
	@echo "    make fetch-adv            — Form ADV pull"
	@echo "    make fetch-ncen           — N-CEN adviser map"
	@echo "    make fetch-finra-short    — FINRA short volume"
	@echo "    make build-managers       — managers table"
	@echo "    make build-fund-classes   — fund_classes + LEI"
	@echo "    make build-cusip          — securities (CUSIP normalisation)"
	@echo ""
	@echo "  DRY_RUN=1 make quarterly-update  — print plan without executing"

# ---------------------------------------------------------------------------
# Primary sequence — each sub-make inherits DRY_RUN, so the plan prints
# end-to-end when DRY_RUN=1 and executes when DRY_RUN is unset.
# Sequential execution: make stops on the first failing step.
# ---------------------------------------------------------------------------
quarterly-update:
	@echo "=== 13F quarterly-update starting ==="
	$(MAKE) fetch-13f
	$(MAKE) fetch-nport
	$(MAKE) build-entities
	$(MAKE) compute-flows
	$(MAKE) fetch-market
	$(MAKE) build-summaries
	$(MAKE) build-classifications
	$(MAKE) backup-db
	$(MAKE) validate
	@echo "=== 13F quarterly-update complete ==="

# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------
fetch-13f:
	@echo "--- Step 1: fetch_13f (holdings_v2) ---"
	$(Q) $(PY) $(SCRIPTS)/fetch_13f.py

fetch-nport:
	@echo "--- Step 2: fetch_nport_v2 (fund_holdings_v2, XML path) ---"
	$(Q) $(PY) $(SCRIPTS)/fetch_nport_v2.py

fetch-dera-nport:
	@echo "--- Step 2 (alt): fetch_dera_nport (DERA ZIP bulk) ---"
	@echo "    Defaults to --all-missing. Override with ZIP=path/to/dir if pre-downloaded."
	$(Q) $(PY) $(SCRIPTS)/fetch_dera_nport.py --all-missing $(if $(ZIP),--zip $(ZIP),)

build-entities:
	@echo "--- Step 3: build_entities (entity MDM sync) ---"
	$(Q) $(PY) $(SCRIPTS)/build_entities.py

compute-flows:
	@echo "--- Step 4: compute_flows (investor_flows, ticker_flow_stats) ---"
	$(Q) $(PY) $(SCRIPTS)/compute_flows.py

fetch-market:
	@echo "--- Step 5: fetch_market (market_data, securities) ---"
	$(Q) $(PY) $(SCRIPTS)/fetch_market.py

build-summaries:
	@echo "--- Step 6: build_summaries (summary_by_parent) ---"
	$(Q) $(PY) $(SCRIPTS)/build_summaries.py

build-classifications:
	@echo "--- Step 7: build_classifications (manager_type, entity classifications) ---"
	$(Q) $(PY) $(SCRIPTS)/build_classifications.py

backup-db:
	@echo "--- Step 8: backup_db (EXPORT DATABASE) ---"
	$(Q) $(PY) $(SCRIPTS)/backup_db.py --no-confirm

validate:
	@echo "--- Step 9: validate_entities --prod ---"
	$(Q) $(PY) $(SCRIPTS)/validate_entities.py --prod

# ---------------------------------------------------------------------------
# Supplementary pipeline steps (not in quarterly-update)
# ---------------------------------------------------------------------------
fetch-13dg:
	$(Q) $(PY) $(SCRIPTS)/fetch_13dg.py

fetch-adv:
	$(Q) $(PY) $(SCRIPTS)/fetch_adv.py

fetch-ncen:
	$(Q) $(PY) $(SCRIPTS)/fetch_ncen.py

fetch-finra-short:
	$(Q) $(PY) $(SCRIPTS)/fetch_finra_short.py

build-managers:
	$(Q) $(PY) $(SCRIPTS)/build_managers.py

build-fund-classes:
	$(Q) $(PY) $(SCRIPTS)/build_fund_classes.py

build-cusip:
	$(Q) $(PY) $(SCRIPTS)/build_cusip.py

# ---------------------------------------------------------------------------
# Freshness + status gates
# ---------------------------------------------------------------------------
freshness:
	@$(PY) $(SCRIPTS)/check_freshness.py

status:
	@$(PY) $(SCRIPTS)/check_freshness.py --status-only
