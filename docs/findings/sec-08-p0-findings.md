# sec-08-p0 — Phase 0 findings: central EDGAR identity config

_Prepared: 2026-04-21 — branch `sec-08-p0` off `main` HEAD `659f5c4`._

_Tracker: SYSTEM_AUDIT §8.1 MINOR-17 O-08._

Phase 0 is investigation only. No code writes and no DB writes were performed.

---

## §1. TL;DR

SEC EDGAR requires a descriptive `User-Agent` header on every request. The project currently hardcodes that identity string inline across **19 active scripts** (plus 2 indirect consumers and 2 retired scripts). There are **three distinct UA-string variants** in the tree today:

| Variant | Example | Count | Where |
|---|---|---|---|
| Canonical | `"13f-research serge.tismen@gmail.com"` | 13 spots (12 files) | `SEC_HEADERS` / `FINRA_HEADERS` / `USER_AGENT` / `set_identity` |
| Bare email | `"serge.tismen@gmail.com"` | 7 spots (7 files) | `SEC_UA` (curl `-H`), two `edgar.set_identity()` calls |
| Divergent prefix | `"13f-ownership-research serge.tismen@gmail.com"` | 1 spot | [`scripts/sec_shares_client.py:46`](scripts/sec_shares_client.py:46) |

The divergence is the audit finding: rotating the contact email today means editing ≥19 files and praying no variant is missed; a single script (`sec_shares_client.py`) silently advertises a different application name to SEC.

`scripts/config.py` **already exists** ([scripts/config.py:1-63](scripts/config.py)) as the centralized quarter config. It is the natural home for an `EDGAR_IDENTITY` constant plus helpers. No new file needed.

`edgartools` exposes `edgar.set_identity(str)` as a process-global setter; the 4 call sites today all pass a string literal. The central config can wrap that call behind a single `configure_edgar_identity()` function that scripts invoke once at startup (or lazily before first edgartools use).

**Phase 1 scope:** extend [`scripts/config.py`](scripts/config.py) with identity constants + helper, then convert 19 active scripts + 2 indirect consumers to import from it. Mechanical edit, low risk, zero behavior change when UA strings are normalized to the canonical variant.

---

## §2. Full inventory

### §2.1 Active scripts (direct literal)

| # | File | Line | Current literal | Mechanism | Variant |
|---|---|---|---|---|---|
| 1 | [`scripts/fetch_adv.py`](scripts/fetch_adv.py:38) | 38 | `"13f-research serge.tismen@gmail.com"` | `SEC_HEADERS = {"User-Agent": …}` | canonical |
| 2 | [`scripts/entity_sync.py`](scripts/entity_sync.py:433) | 433 | `"13f-research serge.tismen@gmail.com"` | `SEC_HEADERS = {…}` | canonical |
| 3 | [`scripts/fetch_13dg.py`](scripts/fetch_13dg.py:44) | 44 | `"serge.tismen@gmail.com"` | `edgar.set_identity(…)` (lazy `_init_edgar`) | bare |
| 3 | [`scripts/fetch_13dg.py`](scripts/fetch_13dg.py:52) | 52 | `"13f-research serge.tismen@gmail.com"` | `SEC_HEADERS = {…}` | canonical |
| 4 | [`scripts/auto_resolve.py`](scripts/auto_resolve.py:33) | 33 | `"13f-research serge.tismen@gmail.com"` | `SEC_HEADERS = {…}` | canonical |
| 5 | [`scripts/resolve_agent_names.py`](scripts/resolve_agent_names.py:31) | 31 | `"serge.tismen@gmail.com"` | `SEC_UA` → curl `-H "User-Agent: {SEC_UA}"` | bare |
| 6 | [`scripts/reparse_all_nulls.py`](scripts/reparse_all_nulls.py:30) | 30 | `"serge.tismen@gmail.com"` | `SEC_UA` → curl `-H` | bare |
| 7 | [`scripts/sec_shares_client.py`](scripts/sec_shares_client.py:46) | 46 | `"13f-ownership-research serge.tismen@gmail.com"` | `USER_AGENT` → `session.headers.update(…)` | **divergent** |
| 8 | [`scripts/fetch_13f.py`](scripts/fetch_13f.py:20) | 20 | `"13f-research serge.tismen@gmail.com"` | `SEC_HEADERS = {…}` | canonical |
| 9 | [`scripts/fetch_nport_v2.py`](scripts/fetch_nport_v2.py:89) | 89 | `"13f-research serge.tismen@gmail.com"` | `SEC_HEADERS = {…}` | canonical |
| 9 | [`scripts/fetch_nport_v2.py`](scripts/fetch_nport_v2.py:429) | 429 | `"13f-research serge.tismen@gmail.com"` | `set_identity(…)` (local import in method) | canonical |
| 10 | [`scripts/fetch_dera_nport.py`](scripts/fetch_dera_nport.py:166) | 166 | `"13f-research serge.tismen@gmail.com"` | `USER_AGENT` → `headers = {"User-Agent": USER_AGENT}` | canonical |
| 11 | [`scripts/pipeline/discover.py`](scripts/pipeline/discover.py:172) | 172 | `"13f-research serge.tismen@gmail.com"` | `set_identity(…)` (local import) | canonical |
| 12 | [`scripts/fetch_ncen.py`](scripts/fetch_ncen.py:67) | 67 | `"13f-research serge.tismen@gmail.com"` | `SEC_HEADERS = {…}` | canonical |
| 13 | [`scripts/reparse_13d.py`](scripts/reparse_13d.py:33) | 33 | `"serge.tismen@gmail.com"` | `SEC_UA` → curl `-H` | bare |
| 14 | [`scripts/admin_bp.py`](scripts/admin_bp.py:468) | 468 | `"serge.tismen@gmail.com"` | `edgar.set_identity(…)` (inline in Flask handler) | bare |
| 15 | [`scripts/resolve_names.py`](scripts/resolve_names.py:28) | 28 | `"serge.tismen@gmail.com"` | `SEC_UA` → curl `-H` (2 call sites) | bare |
| 16 | [`scripts/enrich_tickers.py`](scripts/enrich_tickers.py:28) | 28 | `"13f-research serge.tismen@gmail.com"` | `SEC_HEADERS = {…}` | canonical |
| 17 | [`scripts/fetch_finra_short.py`](scripts/fetch_finra_short.py:36) | 36 | `"13f-research serge.tismen@gmail.com"` | `FINRA_HEADERS = {…}` (FINRA, not SEC — same UA string) | canonical |
| 18 | [`scripts/resolve_bo_agents.py`](scripts/resolve_bo_agents.py:39) | 39 | `"serge.tismen@gmail.com"` | `SEC_UA` → `urllib.request.Request(headers=…)` + curl `-H` | bare |
| 19 | [`scripts/fetch_13dg_v2.py`](scripts/fetch_13dg_v2.py:73) | 73 | `"13f-research serge.tismen@gmail.com"` | `SEC_HEADERS = {…}` | canonical |

**19 active files, 21 literal occurrences.**

### §2.2 Active scripts (indirect consumers — no literal)

These already import `SEC_HEADERS` from `entity_sync`; they only need their import statement retargeted at `config.py` once `entity_sync` itself is converted.

| File | Line | Usage |
|---|---|---|
| [`scripts/resolve_long_tail.py`](scripts/resolve_long_tail.py:131) | 131 | `session.headers.update(entity_sync.SEC_HEADERS)` |
| [`scripts/resolve_adv_ownership.py`](scripts/resolve_adv_ownership.py:98) | 98 | `session.headers.update(entity_sync.SEC_HEADERS)` |

Also: [`scripts/resolve_long_tail.py:22`](scripts/resolve_long_tail.py:22) has the email in a docstring ("SEC API identity: serge.tismen@gmail.com"). Docstring-only, no code impact.

### §2.3 Retired scripts (out of scope)

Under `scripts/retired/`, do **not** modify — kept for historical reference:

| File | Line | Literal | Mechanism |
|---|---|---|---|
| `scripts/retired/fetch_nport.py` | 49 | canonical | `SEC_HEADERS` |
| `scripts/retired/fetch_nport.py` | 105 | canonical | `set_identity` |
| `scripts/retired/build_cusip_legacy.py` | 48 | canonical | `SEC_HEADERS` |

### §2.4 Non-code mentions (out of scope)

- `docs/SYSTEM_ATLAS_2026_04_17.md`, `docs/findings/2026-04-19-rewrite-build-shares-history.md`, `docs/findings/2026-04-19-block-schema-diff.md`, `docs/findings/obs-02-p0-findings.md`, `README.md`, `config/schema_parity_accept.yaml`, `tests/pipeline/test_validate_schema_parity.py:304` — all documentation or reviewer-name references, not EDGAR UA usage.

---

## §3. `scripts/config.py` current state

The file exists (63 lines) and currently exports quarter metadata only: `QUARTERS`, `LATEST_QUARTER`, `QUARTER_URLS`, `QUARTER_REPORT_DATES`, `QUARTER_SNAPSHOT_DATES`, `FLOW_PERIODS`, `SUBADVISER_EXCLUSIONS`. No identity/networking concerns yet.

Extending it keeps "edit-one-file-per-quarter-or-rotation" uniform and avoids introducing a second config module.

---

## §4. `edgartools` identity mechanism

`edgartools` exposes a process-global setter:

```python
from edgar import set_identity
set_identity("Name contact@example.com")
```

Four call sites today:
- [`scripts/fetch_13dg.py:44`](scripts/fetch_13dg.py:44) — lazy-init helper `_init_edgar()`
- [`scripts/fetch_nport_v2.py:429`](scripts/fetch_nport_v2.py:429) — local import inside a method
- [`scripts/pipeline/discover.py:172`](scripts/pipeline/discover.py:172) — local import inside `discover()`
- [`scripts/admin_bp.py:468`](scripts/admin_bp.py:468) — inline inside a Flask POST handler

Because `set_identity` is process-global and idempotent, the central config can wrap it in a helper (`configure_edgar_identity()`) that each script calls once before first edgartools use. Alternatively, config.py can call it unconditionally at import time — but that forces every importer (including scripts that never touch edgartools) to pay the import cost and any side effects. The **explicit helper** pattern is preferred.

---

## §5. Proposed `config.py` extension (pseudocode)

```python
# scripts/config.py — append below existing quarter config

# --- SEC EDGAR identity (sec-08) --------------------------------------

EDGAR_CONTACT_EMAIL = "serge.tismen@gmail.com"
EDGAR_APP_NAME      = "13f-research"
EDGAR_IDENTITY      = f"{EDGAR_APP_NAME} {EDGAR_CONTACT_EMAIL}"

# Header dict for requests / urllib / curl shell-outs.
SEC_HEADERS = {"User-Agent": EDGAR_IDENTITY}

# FINRA uses the same contact string; exported separately for call-site
# clarity (and so a future FINRA rotation doesn't require grep).
FINRA_HEADERS = {"User-Agent": EDGAR_IDENTITY}

def configure_edgar_identity() -> None:
    """Set the process-global edgartools identity. Idempotent."""
    from edgar import set_identity   # local import; edgartools is optional
    set_identity(EDGAR_IDENTITY)
```

Key decisions:
- **One canonical string**, normalized to the 13-of-21 majority (`"13f-research serge.tismen@gmail.com"`). This changes the UA string for `sec_shares_client.py` (previously `"13f-ownership-research …"`) and for the 7 bare-email SEC_UA spots. SEC accepts either — both carry the contact email — but the change is a behavior delta worth flagging in the Phase 1 commit.
- **Explicit helper** for edgartools, not auto-call at import time — keeps config.py side-effect-free and avoids importing `edgar` for scripts that don't need it.
- **No `os.getenv` indirection** yet — rotation is rare (single developer, personal email), and env-var lookup would make it harder to grep the actual identity in logs. Can be added later without breaking callers.

---

## §6. Proposed per-script change pattern

### Pattern A — `requests`/`urllib` header dicts (13 spots)

```python
# BEFORE
SEC_HEADERS = {"User-Agent": "13f-research serge.tismen@gmail.com"}

# AFTER
from scripts.config import SEC_HEADERS
```

If the script has no other `from scripts.config import …`, add the import next to its siblings. Otherwise fold `SEC_HEADERS` into the existing import list.

### Pattern B — curl `-H` shell-outs (`SEC_UA` style, 4 spots)

```python
# BEFORE
SEC_UA = "serge.tismen@gmail.com"
subprocess.run(["curl", "-H", f"User-Agent: {SEC_UA}", url])

# AFTER
from scripts.config import EDGAR_IDENTITY
subprocess.run(["curl", "-H", f"User-Agent: {EDGAR_IDENTITY}", url])
```

(Or keep a local `SEC_UA = EDGAR_IDENTITY` alias if minimizing diff noise is preferred.)

### Pattern C — edgartools `set_identity` (4 spots)

```python
# BEFORE
from edgar import set_identity
set_identity("13f-research serge.tismen@gmail.com")

# AFTER
from scripts.config import configure_edgar_identity
configure_edgar_identity()
```

### Pattern D — indirect consumers (2 spots)

```python
# BEFORE
from scripts import entity_sync
session.headers.update(entity_sync.SEC_HEADERS)

# AFTER
from scripts.config import SEC_HEADERS
session.headers.update(SEC_HEADERS)
```

---

## §7. Files to touch in Phase 1

**Edit (21 files):**

1. `scripts/config.py` — extend with §5 block
2. `scripts/fetch_adv.py` — pattern A
3. `scripts/entity_sync.py` — pattern A
4. `scripts/fetch_13dg.py` — patterns A + C (2 edits)
5. `scripts/auto_resolve.py` — pattern A
6. `scripts/resolve_agent_names.py` — pattern B
7. `scripts/reparse_all_nulls.py` — pattern B
8. `scripts/sec_shares_client.py` — pattern A (also normalizes UA prefix)
9. `scripts/fetch_13f.py` — pattern A
10. `scripts/fetch_nport_v2.py` — patterns A + C (2 edits)
11. `scripts/fetch_dera_nport.py` — pattern A
12. `scripts/pipeline/discover.py` — pattern C
13. `scripts/fetch_ncen.py` — pattern A
14. `scripts/reparse_13d.py` — pattern B
15. `scripts/admin_bp.py` — pattern C
16. `scripts/resolve_names.py` — pattern B
17. `scripts/enrich_tickers.py` — pattern A
18. `scripts/fetch_finra_short.py` — pattern A (FINRA_HEADERS)
19. `scripts/resolve_bo_agents.py` — pattern B
20. `scripts/fetch_13dg_v2.py` — pattern A
21. `scripts/resolve_long_tail.py` — pattern D
22. `scripts/resolve_adv_ownership.py` — pattern D

(21 files in addition to `config.py` itself = 22 files total. Matches REMEDIATION_PLAN §8.1 "~22 scripts" estimate.)

**Do not touch:** `scripts/retired/*`, docs, fixtures, README.

**Tests/CI:** add a smoke test asserting (a) `SEC_HEADERS["User-Agent"] == EDGAR_IDENTITY`, (b) `EDGAR_IDENTITY` contains `"@"`, (c) `configure_edgar_identity()` runs without raising when `edgar` is importable. A grep-based lint step (`scripts/check_edgar_identity.sh`) can enforce "no `User-Agent` literal outside `scripts/config.py` and `scripts/retired/`" in CI — nice-to-have, not required for Phase 1 sign-off.

---

## §8. Risks / notes

1. **UA-string normalization is a behavior delta.** After Phase 1, SEC logs will see a consistent `"13f-research serge.tismen@gmail.com"` UA across all paths. `sec_shares_client.py` loses its `"13f-ownership-research …"` prefix; eight bare-email spots gain the `"13f-research "` prefix. SEC rate-limits per UA+IP; changing UA does not reset per-IP rate-limit buckets, but a brand-new UA may be treated as a new bucket for per-UA limits. Low-risk for this project (single IP, low QPS), but worth calling out in the Phase 1 PR.
2. **`admin_bp.py` identity call is inside a Flask handler.** Because `set_identity` is process-global, calling `configure_edgar_identity()` once at blueprint import time is sufficient; the per-request call can be deleted. Phase 1 should pick one (prefer module-level) rather than leaving both.
3. **`edgartools` is an optional dep** for some entrypoints. `configure_edgar_identity()` imports `edgar` lazily inside the function so `scripts/config.py` stays importable in environments that don't install edgartools (e.g., the web app if it were trimmed).
4. **FINRA uses the same UA.** `fetch_finra_short.py` targets `regsho.finra.org`, not `sec.gov`. Exporting `FINRA_HEADERS` as a separate name preserves call-site clarity — a future FINRA-specific rotation won't surprise SEC consumers.
5. **No secret exposure.** The contact email is public-by-design (SEC requires it in the UA header). No env-var/secret-manager work needed.
6. **Circular-import check required.** `scripts/config.py` is currently a leaf module (no internal imports). Adding `configure_edgar_identity()` keeps it leaf-only because the `edgar` import is inside the function. Pattern A/B/C edits all import *from* `scripts.config`, not the other way round, so no cycles are introduced. Verify in Phase 1 with `python -c "import scripts.config"` plus a dry import of each converted script.
7. **Indirect consumers (§2.2) must be converted in the same PR as `entity_sync.py`** — otherwise `resolve_long_tail.py` and `resolve_adv_ownership.py` break when `entity_sync.SEC_HEADERS` is removed. Keep them in one commit.

---

## §9. Phase 1 checklist (preview, not executed here)

- [ ] Append §5 block to `scripts/config.py`
- [ ] Convert 21 consumer files per §6 patterns
- [ ] Delete now-redundant `SEC_HEADERS`/`SEC_UA`/`USER_AGENT`/`FINRA_HEADERS` literals in each
- [ ] Add smoke test `tests/test_config_edgar_identity.py`
- [ ] Run `python -c "import scripts.config; import scripts.entity_sync; …"` for each converted script
- [ ] Run existing test suite; no functional deltas expected
- [ ] Grep `grep -rn "User-Agent.*@" scripts/ --include="*.py" | grep -v retired/ | grep -v config.py` → expect **zero matches**
- [ ] Open PR `sec-08`; link this findings doc; call out the UA-normalization behavior delta
