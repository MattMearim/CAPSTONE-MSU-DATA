#!/usr/bin/env python
import json
from pathlib import Path
from frib_ds.models import EngineeringEvent, AnalysisResult, RAGResponse, KnowledgeDraft, ReviewRecord
from frib_ds.quality_agent_models import AgentResponse, QualityAgentSettings

OUT=Path('contracts'); OUT.mkdir(exist_ok=True)
items={
    'event.schema.json': EngineeringEvent,
    'analysis.schema.json': AnalysisResult,
    'rag.schema.json': RAGResponse,
    'knowledge.schema.json': KnowledgeDraft,
    'review.schema.json': ReviewRecord,
    'quality-agent-response.schema.json': AgentResponse,
    'quality-agent-settings.schema.json': QualityAgentSettings,
}
for name, model in items.items():
    (OUT/name).write_text(json.dumps(model.model_json_schema(),indent=2),encoding='utf-8')
    print('wrote',OUT/name)
