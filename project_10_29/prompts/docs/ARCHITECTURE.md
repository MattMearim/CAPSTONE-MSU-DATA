# Architecture

## Design objective

The application implements a field-agnostic, non-autonomous, human-supervised decision-support POC. The important separation is between **raw evidence**, **derived engineering information**, **retrieved procedural guidance**, **AI interpretation**, and **human-approved knowledge**.

```text
Source / Generator
      │
      ▼
┌──────────────────────┐
│ Level 1              │
│ Ingestion/Provenance │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ Level 2              │
│ Processing/Plots     │
└──────────┬───────────┘
           │            Approved documents
           │                   │
           ▼                   ▼
        Event context      RAG index
           │                   │
           └───────┬───────────┘
                   ▼
┌──────────────────────────┐
│ Level 3                  │
│ Grounded assistance      │
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│ Level 4                  │
│ Draft / hypotheses       │
└────────────┬─────────────┘
             ▼
       HUMAN DECISION
  Approve / Correct / Escalate
             │
             ▼
       Knowledge store
```

## Replaceable interfaces

- `EventGenerator` — synthetic domain scenarios
- `Processor` — domain-specific Level-2 analysis
- `EmbeddingProvider` — SentenceTransformers or alternatives
- `VectorStore` — ChromaDB or alternatives
- `LLMProvider` — Ollama, LM Studio, mock, or future providers
- `SQLiteRepository` — persistence implementation; replace behind repository methods
- FastAPI — stable backend boundary for the frontend

## Trust boundaries

1. Level 1 does not infer root cause.
2. Level 2 derives features but labels them as derived.
3. Level 3 must retrieve approved documents; no source means no authoritative procedural answer.
4. Level 4 produces a draft only.
5. Only human-approved or corrected drafts become searchable knowledge.

## Real deployment additions

Authentication, authorization, network security, backups, document-governance workflow, model governance, audit retention, sponsor-defined validation thresholds, and real facility data adapters are intentionally outside the demo POC until requirements are supplied.
