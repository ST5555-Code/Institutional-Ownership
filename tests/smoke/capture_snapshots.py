#!/usr/bin/env python3
"""Capture response JSON snapshots for Phase 0-B2 smoke tests.

Runs each endpoint in `endpoints.ENDPOINTS` against the committed fixture
DB and writes the response to `tests/fixtures/responses/<name>.json`.

Usage:
    python tests/smoke/capture_snapshots.py          # dry — warn on existing
    python tests/smoke/capture_snapshots.py --update # overwrite existing

This script intentionally requires an explicit --update flag. Snapshots are
the source of truth for test_smoke_response_equality() and should only be
regenerated after an intentional schema change, not on test failure.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIXTURE_DB = ROOT / "tests" / "fixtures" / "13f_fixture.duckdb"
SNAP_DIR = ROOT / "tests" / "fixtures" / "responses"
MIG_027 = ROOT / "scripts" / "migrations" / "027_unified_holdings_view.py"
MIG_028 = (
    ROOT / "scripts" / "migrations"
    / "028_unified_holdings_quarter_dimension.py"
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--update", action="store_true",
                    help="Overwrite existing snapshots")
    args = ap.parse_args()

    if not FIXTURE_DB.exists():
        sys.exit(f"fixture missing: {FIXTURE_DB} — run scripts/build_fixture.py first")

    SNAP_DIR.mkdir(parents=True, exist_ok=True)

    # CP-5.2: apply migrations 027 + 028 to a tmp copy so captured
    # responses reflect the entity-keyed Register reader path. The
    # committed fixture has tables only; views are migration-managed.
    tmp_dir = Path(tempfile.mkdtemp(prefix="capture_snapshots_"))
    tmp_db = tmp_dir / "fixture_with_views.duckdb"
    shutil.copy(FIXTURE_DB, tmp_db)
    boot = duckdb.connect(str(tmp_db))
    boot.execute(
        "CREATE TABLE IF NOT EXISTS schema_versions ("
        "  version VARCHAR PRIMARY KEY, "
        "  notes VARCHAR, "
        "  applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    boot.close()
    _load(MIG_027, "mig027").run_migration(
        str(tmp_db), dry_run=False, skip_guards=True
    )
    _load(MIG_028, "mig028").run_migration(
        str(tmp_db), dry_run=False, skip_guards=True
    )
    os.environ["DB_PATH_OVERRIDE"] = str(tmp_db)
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from fastapi.testclient import TestClient  # noqa: E402
    import app as app_module  # noqa: E402 — needs env set first
    from tests.smoke.endpoints import ENDPOINTS  # noqa: E402

    client = TestClient(app_module.app)

    for name, path in ENDPOINTS.items():
        out = SNAP_DIR / f"{name}.json"
        if out.exists() and not args.update:
            print(f"[capture] skip {name} (exists, pass --update to overwrite)")
            continue
        resp = client.get(path)
        if resp.status_code != 200:
            sys.exit(f"[capture] {name} {path} → HTTP {resp.status_code}: {resp.content[:300]!r}")
        body = resp.json()
        if body is None:
            sys.exit(f"[capture] {name} {path} → non-JSON or empty body")
        out.write_text(json.dumps(body, indent=2, default=str, sort_keys=False) + "\n")
        print(f"[capture] wrote {out.relative_to(ROOT)} ({out.stat().st_size:,} B)")


if __name__ == "__main__":
    main()
