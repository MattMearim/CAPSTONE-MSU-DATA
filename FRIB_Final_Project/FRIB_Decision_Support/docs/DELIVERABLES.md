# Full project delivery

The source distribution contains the four-level decision-support application, API, Windows launcher, beginner setup guide, three demonstration domains, ready-to-import datasets, fictional sample documents, schema/OpenAPI contracts, tests, Docker configuration and validation documents.

## Run

Extract the ZIP. Open the extracted `FRIB_Decision_Support` folder and double-click **Start FRIB.cmd**. First-time installation requires Python 3.11+ and internet; ordinary demo mode requires no model service. Keep the launcher open and press Ctrl+C to stop.

## Project areas

| Deliverable | Contents |
|---|---|
| Synthetic engineering generator | `src/frib_ds/generator`, scenario settings, standalone CLI, JSON/CSV examples |
| Standard interface specification | Pydantic models, `contracts`, `docs/openapi.json`, API guide |
| Four-level core | Original evidence storage, numerical processing, approved-document retrieval, hypothesis/draft generation, atomic human-review publication |
| Operator interface | Dataset generation/import/library, evidence file manager, document library, assistant, review forms, reviewed wiki, settings/history/help |
| Validation | Domain numerical tests, API lifecycle/restart tests, UI tests, startup portability tests, validation report and remaining sponsor work |
| Deployment | One-command local startup, Dockerfiles/Compose, provider configuration and replacement guide |

The ZIP intentionally contains fresh runnable source rather than this computer's environment and runtime records. It excludes `.venv`, local databases, original private uploads, model caches, logs and secrets. The existing project's runtime records remain in place.

`SHA256SUMS.txt` inside the ZIP verifies every included source file. An adjacent `.zip.sha256` verifies the whole archive. Rebuild with `python scripts/package_project.py <output.zip>`.

See `docs/REQUIREMENTS_MATRIX.md` for exact coverage and `docs/VALIDATION_REPORT.md` for verified results and untested deployment/model work.
