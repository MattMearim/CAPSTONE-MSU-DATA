#!/usr/bin/env python3
"""Convert everything in data/external/ into canonical records.

Usage (from the repo root):
    python3 scripts/convert_data.py

Writes one JSON file per record to data/converted/<source id>/ and prints a
summary. Run scripts/fetch_data.py first.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ingestion.adapters import convert_source  # noqa: E402


def main():
    sources = json.loads((ROOT / "data" / "sources.json").read_text())["sources"]
    total = 0
    for src in sources:
        out = ROOT / "data" / "converted" / src["id"]
        out.mkdir(parents=True, exist_ok=True)
        counts = {}
        for rec in convert_source(src, ROOT / "data" / "external"):
            (out / f"{rec['record_id']}.json").write_text(json.dumps(rec))
            counts[rec["record_type"]] = counts.get(rec["record_type"], 0) + 1
            total += 1
        print(f"{src['id']}: " + (", ".join(f"{n} {t}" for t, n in sorted(counts.items())) or "nothing found, run fetch_data.py"))
    print(f"{total} records written to data/converted/")


if __name__ == "__main__":
    main()
