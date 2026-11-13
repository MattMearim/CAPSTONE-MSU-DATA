#!/usr/bin/env python
"""Generate a portable JSON event without initializing any AI component."""
import argparse
import json
from pathlib import Path
from frib_ds.generator.registry import GeneratorRegistry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('domain', choices=['rf', 'mechanical', 'plc'])
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--overrides', default='{}', help='Scenario overrides as a JSON object')
    parser.add_argument('--output', type=Path, help='Write a new JSON file; existing files are never overwritten')
    parser.add_argument('--store', action='store_true', help='Also preserve the event in the local application')
    args = parser.parse_args()
    try:
        overrides = json.loads(args.overrides)
        if not isinstance(overrides, dict):
            raise ValueError('--overrides must be a JSON object')
        event = GeneratorRegistry().for_domain(args.domain).generate(args.seed, overrides)
        if args.store:
            from frib_ds.config import get_config
            from frib_ds.storage.files import EventFileStore
            from frib_ds.storage.sqlite import SQLiteRepository
            config = get_config()
            EventFileStore(config.event_dir).save(event)
            repo = SQLiteRepository(config.database_path)
            repo.save_event(event)
            repo.record_audit('create', 'event', event.event_id, {'source': 'standalone_generator'})
        payload = event.model_dump_json(indent=2)
        if args.output:
            with args.output.open('x', encoding='utf-8') as output:
                output.write(payload)
            print(f'Wrote {args.output.resolve()}')
        else:
            print(payload)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f'Could not generate event: {exc}\n')


if __name__ == '__main__':
    main()
