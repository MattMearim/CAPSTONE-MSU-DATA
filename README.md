# Field-Agnostic Four-Level Human-Supervised Decision-Support System

MSU ECE capstone, Fall 2026. Sponsor: Facility for Rare Isotope Beams (FRIB).

A proof-of-concept that helps a human operator analyze an operational event.
It never acts on its own: every summary passes through an
Approve / Correct / Escalate gate.

| Level | What it does | Folder |
|---|---|---|
| 1 | Ingestion and provenance | `ingestion/` |
| 2 | Cleaning, alignment, FFT, plotting | `processing/` |
| 3 | Retrieval over procedures and manuals (RAG) | `rag/` |
| 4 | Draft summaries, hypothesis ranking, human review gate | `knowledge/` |

## Repository layout

| Folder | Contents |
|---|---|
| `schemas/` | The data contract: JSON Schemas for the three input types, plus examples |
| `generator/` | Synthetic Engineering Data Generator (not written yet) |
| `ingestion/` | Level 1 |
| `processing/` | Level 2 |
| `rag/` | Level 3 |
| `knowledge/` | Level 4 |
| `dashboard/` | Streamlit interface |
| `data/external/` | Downloaded public datasets (not committed to git) |
| `tests/` | Automated checks |
| `docs/` | Design notes and data-source survey |

## The data contract

Everything entering the system is one of three record types, and every
record carries the same provenance block.

- `schemas/timeseries.schema.json`: sampled signals
- `schemas/event_log.schema.json`: discrete state changes, alarms, interlocks
- `schemas/document.schema.json`: procedures and manuals
- `schemas/provenance.schema.json`: source, asset, operating mode, configuration, timestamps

No schema contains a field tied to one engineering domain. The domain is a
free-text label in `provenance.asset.domain` and nothing may branch on it.
See `docs/schema_overview.md`.

## Running the checks

```
pip install -r requirements.txt
pytest
```

## Stack

Python, Streamlit, ChromaDB, SentenceTransformers, Ollama, SQLite,
Docker Compose. Everything runs locally at no cost.
