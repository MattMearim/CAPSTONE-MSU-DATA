"""Pure file-to-contract conversion. Callers own persistence and originals."""
from __future__ import annotations

from .common import TABULAR_SUFFIXES, validate_upload


def inspect_upload(filename: str, contents: bytes) -> dict:
    suffix = validate_upload(filename, contents)
    if suffix in TABULAR_SUFFIXES:
        from .tabular import inspect_csv
        return inspect_csv(filename, contents)
    from .narrative import inspect_document
    return inspect_document(filename, contents)


def build_event(filename: str, contents: bytes, options: dict | None = None):
    suffix = validate_upload(filename, contents)
    if options is not None and not isinstance(options, dict):
        raise ValueError("Import options must be a JSON object.")
    options = options or {}
    if suffix in TABULAR_SUFFIXES:
        from .tabular import build_csv
        return build_csv(filename, contents, options)
    from .narrative import build_document
    return build_document(filename, contents, options)
