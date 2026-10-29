#!/usr/bin/env python
"""Add fictional demo data idempotently. Run only in a demonstration workspace."""
import hashlib
from pathlib import Path
from frib_ds.bootstrap import get_services


def main():
    services = get_services()
    for seed, domain in enumerate(['rf', 'mechanical', 'plc'], start=41):
        event = services.generators.for_domain(domain).generate(seed)
        event.event_id = f'DEMO-{domain.upper()}-{seed}'
        event.metadata['dataset_name'] = f'DEMO ONLY - {domain.upper()}'
        if not services.repo.get_event(event.event_id):
            services.files.save(event)
            services.repo.save_event(event)
            services.repo.save_analysis(services.processors.get(domain).process(event))
            services.repo.record_audit('create', 'event', event.event_id, {'source':'demo_seed'})
            print('Seeded', event.event_id)
    catalog = services.repo.list_documents()
    samples = Path(__file__).resolve().parents[1] / 'sample_docs'
    for path in samples.glob('*.md'):
        contents = path.read_bytes()
        checksum = hashlib.sha256(contents).hexdigest()
        if any(row['checksum'] == checksum and row['approved'] for row in catalog):
            continue
        metadata = services.documents.upload(path.name, contents, approved=True, title=path.stem, version='DEMO-ONLY')
        print('Indexed fictional demo document', metadata['document_id'])
    print('Ready. All bundled procedures are fictional and for demonstration only.')


if __name__ == '__main__':
    main()
