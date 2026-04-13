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
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIXTURE_DB = ROOT / "tests" / "fixtures" / "13f_fixture.duckdb"
SNAP_DIR = ROOT / "tests" / "fixtures" / "responses"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--update", action="store_true",
                    help="Overwrite existing snapshots")
    args = ap.parse_args()

    if not FIXTURE_DB.exists():
        sys.exit(f"fixture missing: {FIXTURE_DB} — run scripts/build_fixture.py first")

    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["DB_PATH_OVERRIDE"] = str(FIXTURE_DB)
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
