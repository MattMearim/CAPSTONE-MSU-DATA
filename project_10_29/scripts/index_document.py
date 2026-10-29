#!/usr/bin/env python
"""Upload an original document through the same managed store as the UI."""
import argparse
from pathlib import Path
from frib_ds.bootstrap import get_services


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--title')
    parser.add_argument('--version')
    parser.add_argument('--approved', action='store_true', help='Explicitly authorize indexing as approved reference material')
    args = parser.parse_args()
    metadata = get_services().documents.upload(args.path.name, args.path.read_bytes(), args.approved, args.title, args.version)
    print(f"Stored {metadata['document_id']}; indexed {metadata['indexed_chunks']} approved chunks")


if __name__ == '__main__':
    main()
