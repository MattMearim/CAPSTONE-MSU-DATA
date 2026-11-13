"""Small workspace display preferences, separate from model and evidence settings."""
import json
import os
from pathlib import Path
import tempfile

from frib_ds.ai_settings import preferences_dir
from frib_ds.config import get_config


def _path():
    return preferences_dir(get_config().config_dir) / 'ui-preferences.json'


def resource_visibility():
    try:
        value=json.loads(_path().read_text(encoding='utf-8')).get('live_resources',True)
        return value if isinstance(value,bool) else True
    except (OSError,ValueError,AttributeError):
        return True


def save_resource_visibility(visible):
    target=_path(); target.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=target.parent,suffix='.tmp',delete=False) as stream:
            temporary=Path(stream.name)
            json.dump({'live_resources':bool(visible)},stream,indent=2)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary,target)
    finally:
        if temporary and temporary.exists(): temporary.unlink()
