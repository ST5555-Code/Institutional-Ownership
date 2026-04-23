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
        fetch-13f load-13f fetch-nport fetch-dera-nport \
        build-entities compute-flows fetch-market \
        build-summaries build-classifications \
        backup-db validate \
        freshness status \
        fetch-13dg fetch-adv fetch-ncen fetch-finra-short \
        promote-adv \
        build-managers build-fund-classes build-cusip \
        schema-parity-check \
        rotate-logs rotate-logs-dry \
        audit-read-sites

help:
	@echo "13F pipeline targets:"
	@echo ""
	@echo "  Primary:"
	@echo "    make quarterly-update     — run the full 9-step quarterly sequence"
	@echo "    make status               — print last-run timestamps from data_freshness"
	@echo "    make freshness            — gate: fail if any critical table is stale"
	@echo ""
	@echo "  Individual pipeline steps (runnable standalone):"
	@echo "    make fetch-13f            — Step 1a: download 13F quarterly ZIPs"
	@echo "    make load-13f             — Step 1b: load 13F TSVs into holdings_v2 (QUARTER=YYYYQn optional)"
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
	@echo "  Phase 2 pre-flight:"
	@echo "    make schema-parity-check  — validate staging↔prod L3 schema parity"
	@echo ""
	@echo "  Maintenance:"
	@echo "    make rotate-logs          — compress logs >7d, delete >90d (see MAINTENANCE.md)"
	@echo "    make rotate-logs-dry      — print rotation actions without executing"
	@echo ""
	@echo "  Supplementary:"
	@echo "    make fetch-13dg           — 13D/G beneficial ownership"
	@echo "    make fetch-adv            — Form ADV pull (staging; prints run_id)"
	@echo "    make promote-adv          — ADV staging → prod (RUN_ID=<adv_run_id> required)"
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
	$(MAKE) load-13f
	$(MAKE) fetch-nport
	$(MAKE) build-entities
	$(MAKE) compute-flows
	$(MAKE) fetch-market
	$(MAKE) build-summaries
	$(MAKE) build-classifications
	@# promote-adv is gated on ADV_RUN_ID because fetch-adv (staging) is
	@# not itself in quarterly-update — run it separately, capture the
	@# run_id it prints, then re-invoke: make quarterly-update ADV_RUN_ID=...
	@if [ -n "$(ADV_RUN_ID)" ]; then \
		$(MAKE) promote-adv RUN_ID=$(ADV_RUN_ID); \
	else \
		echo "--- skip promote-adv (pass ADV_RUN_ID=<run_id> from fetch-adv to include) ---"; \
	fi
	$(MAKE) backup-db
	$(MAKE) validate
	@echo "=== 13F quarterly-update complete ==="

# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------
fetch-13f:
	@echo "--- Step 1a: fetch_13f (download quarterly 13F ZIPs) ---"
	$(Q) $(PY) $(SCRIPTS)/fetch_13f.py

load-13f:
	@echo "--- Step 1b: load_13f (TSVs → holdings_v2, filings, filings_deduped, other_managers) ---"
	$(Q) $(PY) $(SCRIPTS)/load_13f.py $(if $(QUARTER),--quarter $(QUARTER),)

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
	$(Q) $(PY) $(SCRIPTS)/pipeline/load_adv.py --staging

promote-adv:
	@echo "--- load_adv auto-approve (ADV staging → prod) ---"
	$(Q) $(PY) $(SCRIPTS)/pipeline/load_adv.py --auto-approve

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

# ---------------------------------------------------------------------------
# Phase 2 pre-flight: schema parity between prod and staging L3 tables.
# Exit non-zero halts Phase 2. See docs/BLOCK_SCHEMA_DIFF_FINDINGS.md §6.
# ---------------------------------------------------------------------------
schema-parity-check:
	@echo "--- Schema parity: prod ↔ staging (L3) ---"
	@$(PY) $(SCRIPTS)/pipeline/validate_schema_parity.py

# ---------------------------------------------------------------------------
# Maintenance — log rotation (see MAINTENANCE.md → "Log Rotation").
# Standalone target: run weekly, or before quarterly-update when logs/ is
# over ~50MB. Policy: compress >7d, delete >90d.
# ---------------------------------------------------------------------------
rotate-logs:
	@$(SCRIPTS)/rotate_logs.sh

rotate-logs-dry:
	@$(SCRIPTS)/rotate_logs.sh --dry-run

# ---------------------------------------------------------------------------
# mig-07 Mode 1 — on-demand read-site inventory audit. Scans scripts/ and
# web/react-app/src/ for SQL and API-field read sites and writes a CSV
# report to data/reports/read_site_inventory.csv. Run before dropping or
# renaming a column to find every read site.
# ---------------------------------------------------------------------------
audit-read-sites:
	$(Q) $(PY) $(SCRIPTS)/hygiene/audit_read_sites.py --csv
