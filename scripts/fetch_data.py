#!/usr/bin/env python3
"""Download the public datasets listed in data/sources.json.

Usage (from the repo root):
    python3 scripts/fetch_data.py            # download anything missing
    python3 scripts/fetch_data.py --force    # re-download everything
    python3 scripts/fetch_data.py --only skab

Files land in data/external/<source id>/ and are ignored by git.
Uses only the Python standard library.
"""
import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "sources.json"
OUT = ROOT / "data" / "external"


def fetch(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "capstone-fetch/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    dest.write_bytes(data)
    return hashlib.sha256(data).hexdigest(), len(data)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="re-download existing files")
    ap.add_argument("--only", help="fetch a single source id")
    args = ap.parse_args()

    sources = json.loads(MANIFEST.read_text())["sources"]
    if args.only:
        sources = [s for s in sources if s["id"] == args.only]
        if not sources:
            sys.exit(f"No source with id {args.only!r} in {MANIFEST}")

    failed = 0
    for src in sources:
        folder = OUT / src["id"]
        log_path = folder / "_download_log.json"
        log = json.loads(log_path.read_text()) if log_path.exists() else {}
        print(f"{src['id']}: {src['title']}  [{src['license']}]")
        for rel in src["files"]:
            dest = folder / rel
            if dest.exists() and not args.force:
                continue
            url = src["base_url"] + rel
            try:
                sha, size = fetch(url, dest)
            except Exception as exc:  # keep going; report at the end
                failed += 1
                print(f"  FAILED {rel}: {exc}")
                continue
            log[rel] = {
                "url": url,
                "sha256": sha,
                "bytes": size,
                "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            print(f"  got {rel} ({size:,} bytes)")
        folder.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps(log, indent=2) + "\n")
    if failed:
        sys.exit(f"{failed} file(s) failed to download")
    print("Done.")


if __name__ == "__main__":
    main()
