from frib_ds.ai_settings import preferences_dir, _guard, _write_json_file
from frib_ds.quality_agent_models import QualityAgentSettings


def read_quality_settings(config_dir):
    path = preferences_dir(config_dir) / 'quality-agent.json'
    _guard(path)
    if not path.exists():
        return QualityAgentSettings()
    if path.stat().st_size > 16000:
        raise ValueError('Quality-agent settings are too large.')
    return QualityAgentSettings.model_validate_json(path.read_text(encoding='utf-8'))


def save_quality_settings(config_dir, settings):
    _write_json_file(preferences_dir(config_dir) / 'quality-agent.json', settings.model_dump(mode='json'))
