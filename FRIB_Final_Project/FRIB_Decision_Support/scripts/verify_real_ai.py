"""Exercise real embeddings and cited model generation using disposable app data.

Requires SETUP_LOCAL_AI.command and a running Ollama server. The FRIB launcher
starts the server automatically. No test double or provider override is used.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--procedure", type=Path, required=True)
    parser.add_argument("--options", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from fastapi.testclient import TestClient
    from frib_ds.local_ai import configured_environment, validate_real_providers
    from frib_ds.config import get_config
    from frib_ds.bootstrap import get_services
    from frib_ds.api.main import app
    options = json.loads(args.options.read_text())
    before = os.environ.get("FRIB_DATA_DIR")
    try:
        with tempfile.TemporaryDirectory(prefix="frib-real-ai-check-") as scratch:
            os.environ["FRIB_DATA_DIR"] = str(Path(scratch) / "data")
            get_config.cache_clear()
            get_services.cache_clear()
            with configured_environment():
                validate_real_providers(get_config().models)
                report = {"checked_at": datetime.now(timezone.utc).isoformat(), "scope": "Real Ollama generation and MiniLM embeddings; isolated temporary event and procedure library", "providers": {key: get_config().models[key] for key in ("llm", "embeddings")}}
                with TestClient(app) as client:
                    def checked(response):
                        if response.status_code != 200:
                            raise RuntimeError(f"HTTP {response.status_code}: {response.text}")
                        return response.json()

                    report["health"] = checked(client.get("/health"))
                    assert report["health"]["llm_provider"] == "ollama"
                    assert report["health"]["embedding_provider"] == "sentence_transformers"
                    imported = checked(client.post("/ingestion/import", files={"file": (args.dataset.name, args.dataset.read_bytes(), "text/csv")}, data={"options": json.dumps(options)}))
                    event_id = imported["event"]["event_id"]
                    report["signal_count"] = len(imported["event"]["signals"])
                    report["analysis"] = checked(client.post(f"/events/{event_id}/analyze"))
                    procedure = checked(client.post("/documents/index", files={"file": (args.procedure.name, args.procedure.read_bytes(), "text/markdown")}, data={"approved": "true", "title": "Chernobyl leak response - FICTIONAL TRAINING", "version": "TRAINING-1.0"}))
                    question = "How should the response team address the Chernobyl leak in this fictional training scenario? Cite the procedure, explain the observations, and state whether the cause is confirmed or the leak is fixed."
                    report["rag"] = checked(client.post("/rag/query", json={"question": question, "event_id": event_id}))
                    answer = report["rag"]
                    assert answer["mode"] == "llm" and answer["grounded"] and answer["interpretation"], answer
                    assert answer["sources"] and all(s["document_id"] == procedure["document_id"] for s in answer["sources"]), answer
                    assert "[S1]" in answer["answer"], answer
                    report["draft"] = checked(client.post(f"/events/{event_id}/draft"))
                    assert report["draft"]["generated_by"].startswith("configured_llm"), report["draft"]
                    assert report["draft"]["status"] == "draft"
                report["passed"] = True
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, indent=2) + "\n")
                print(json.dumps({"passed": True, "answer_mode": answer["mode"], "source_count": len(answer["sources"]), "draft_mode": report["draft"]["generated_by"], "output": str(args.output)}))
    finally:
        get_services.cache_clear()
        get_config.cache_clear()
        if before is None:
            os.environ.pop("FRIB_DATA_DIR", None)
        else:
            os.environ["FRIB_DATA_DIR"] = before


if __name__ == "__main__":
    main()
