"""Local, deterministic ingestion of mixed tabular and narrative evidence."""
from .service import build_event, inspect_upload

__all__ = ["build_event", "inspect_upload"]
