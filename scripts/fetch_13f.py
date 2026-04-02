#!/usr/bin/env python3
"""
fetch_13f.py — Download and extract SEC 13F quarterly data sets.

Run: python3 scripts/fetch_13f.py
"""

import os
import time
import zipfile
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw")
EXTRACT_DIR = os.path.join(BASE_DIR, "data", "extracted")

SEC_HEADERS = {"User-Agent": "13f-research serge.tismen@gmail.com"}
SEC_DELAY = 0.5

from config import QUARTER_URLS as QUARTERS
from db import crash_handler


def download_quarter(quarter, url):
    """Download a single quarter ZIP."""
    zip_path = os.path.join(RAW_DIR, f"{quarter}_form13f.zip")

    # Skip if already downloaded
    if os.path.exists(zip_path) and os.path.getsize(zip_path) > 1000:
        print(f"  {quarter}: Already downloaded ({os.path.getsize(zip_path) / 1_000_000:.1f} MB), skipping")
        return zip_path

    print(f"  {quarter}: Downloading...")
    r = requests.get(url, headers=SEC_HEADERS, timeout=300, stream=True)
    r.raise_for_status()

    total = int(r.headers.get("Content-Length", 0))
    downloaded = 0
    with open(zip_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=1_000_000):
            f.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                pct = downloaded / total * 100
                print(f"    {downloaded / 1_000_000:.1f} / {total / 1_000_000:.1f} MB ({pct:.0f}%)", end="\r")
    print(f"  {quarter}: Downloaded {downloaded / 1_000_000:.1f} MB                    ")
    time.sleep(SEC_DELAY)
    return zip_path


def verify_and_extract(quarter, zip_path):
    """Verify ZIP integrity and extract to quarter folder."""
    extract_to = os.path.join(EXTRACT_DIR, quarter)
    os.makedirs(extract_to, exist_ok=True)

    # Check if already extracted
    existing = os.listdir(extract_to)
    tsv_files = [f for f in existing if f.upper().endswith(".TSV")]
    if len(tsv_files) >= 2:
        print(f"  {quarter}: Already extracted ({len(tsv_files)} TSV files), skipping")
        return extract_to

    # Verify ZIP
    try:
        z = zipfile.ZipFile(zip_path)
        bad = z.testzip()
        if bad:
            raise zipfile.BadZipFile(f"Corrupt file in ZIP: {bad}")
    except zipfile.BadZipFile as e:
        print(f"  {quarter}: ZIP verification FAILED — {e}")
        print("    Deleting corrupt file, will need re-download")
        os.remove(zip_path)
        return None

    # Extract
    file_list = z.namelist()
    print(f"  {quarter}: Extracting {len(file_list)} files...")
    z.extractall(extract_to)
    z.close()

    # List extracted files
    for f in sorted(os.listdir(extract_to)):
        fpath = os.path.join(extract_to, f)
        size = os.path.getsize(fpath) / 1_000_000
        print(f"    {f} ({size:.1f} MB)")

    return extract_to


def main():
    print("=" * 60)
    print("SCRIPT 3 — fetch_13f.py")
    print("=" * 60)

    results = {}
    for quarter, url in QUARTERS.items():
        print(f"\n--- {quarter} ---")
        zip_path = download_quarter(quarter, url)
        if zip_path:
            extract_path = verify_and_extract(quarter, zip_path)
            results[quarter] = extract_path
        else:
            results[quarter] = None

    # Summary
    print("\n--- Summary ---")
    for quarter, path in results.items():
        if path:
            files = os.listdir(path)
            print(f"  {quarter}: OK — {len(files)} files in {path}")
        else:
            print(f"  {quarter}: FAILED")

    failed = [q for q, p in results.items() if p is None]
    if failed:
        print(f"\nWARNING: Failed quarters: {failed}")
        print("Re-run this script to retry downloads.")
    else:
        print("\nAll 4 quarters downloaded and extracted successfully.")


if __name__ == "__main__":
    crash_handler("fetch_13f")(main)
