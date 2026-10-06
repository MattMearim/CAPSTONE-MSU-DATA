"""Command line for the synthetic generator.

    python3 -m generator                       # 30 events, seed 42
    python3 -m generator --seed 7 --events 90
    python3 -m generator --domains rf plc
    python3 -m generator --domains rf --scenario field_collapse --events 5
    python3 -m generator --list
"""
import argparse
from pathlib import Path

from . import engine


def main():
    ap = argparse.ArgumentParser(prog="python3 -m generator", description="Synthetic Engineering Data Generator")
    ap.add_argument("--seed", type=int, default=42, help="same seed gives identical output (default 42)")
    ap.add_argument("--events", type=int, default=30, help="number of operational events (default 30)")
    ap.add_argument("--domains", nargs="+", help="limit to these domains (default: all)")
    ap.add_argument("--scenario", help="force one scenario id")
    ap.add_argument("--start", default="2026-01-05T08:00:00", help="timestamp of the first event (UTC)")
    ap.add_argument("--out", help="output folder (default data/generated/seed-<seed>)")
    ap.add_argument("--list", action="store_true", help="list domains and scenarios, then exit")
    args = ap.parse_args()

    if args.list:
        for name, dom in engine.load_domains().items():
            print(f"{name}: {len(dom['channels'])} channels")
            for s in dom["scenarios"]:
                print(f"  {s['id']:<28} {s.get('description', '')}")
        return

    records, manifest = engine.generate(seed=args.seed, events=args.events, domains=args.domains,
                                        scenario=args.scenario, start=args.start)
    root = Path(__file__).resolve().parent.parent
    out = engine.write(records, manifest, args.out or root / "data" / "generated" / f"seed-{args.seed}")
    c = manifest["counts"]
    print(f"{c['events']} events, {c['documents']} documents, {c['records']} records -> {out}")
    by = {}
    for e in manifest["events"]:
        by[(e["domain"], e["scenario"])] = by.get((e["domain"], e["scenario"]), 0) + 1
    for (d, s), n in sorted(by.items()):
        print(f"  {d:<11} {s:<28} {n}")


if __name__ == "__main__":
    main()
