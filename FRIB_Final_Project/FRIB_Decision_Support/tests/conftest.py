"""Keep all unit tests isolated from the user's permanent AI installation."""
import pytest


@pytest.fixture(autouse=True)
def isolated_shared_ai_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIB_AI_HOME", str(tmp_path / "shared-ai"))
    # Existing bootstrap tests exercise disposable environments; only tests
    # explicitly covering publication should enable permanent Python storage.
    monkeypatch.setenv("FRIB_PERSISTENT_PYTHON", "0")
    monkeypatch.setenv('FRIB_AI_PROFILE_ROOT', str(tmp_path / 'ai-preferences'))
    monkeypatch.delenv('FRIB_DEPENDENCIES_DIR', raising=False)
