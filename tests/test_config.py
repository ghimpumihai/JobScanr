import importlib
import sys
from pathlib import Path


def test_default_production(monkeypatch):
    monkeypatch.delenv("DB_ENV", raising=False)
    monkeypatch.setattr(sys, "argv", ["app"])
    import config
    importlib.reload(config)
    assert config.DB_ENV == "production"


def test_staging_flag(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["app", "--staging"])
    import config
    importlib.reload(config)
    assert config.DB_ENV == "staging"


def test_db_env_staging(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["app"])
    monkeypatch.setenv("DB_ENV", "staging")
    import config
    importlib.reload(config)
    assert config.DB_ENV == "staging"


def test_explicit_load_environment(monkeypatch):
    import config
    env_prod = config.load_environment(staging=False)
    assert env_prod == "production"
    assert config.DB_ENV == "production"

    env_stage = config.load_environment(staging=True)
    assert env_stage == "staging"
    assert config.DB_ENV == "staging"




def test_default_profile_loaded():
    import config
    assert "titles" in config.PROFILE
    assert "levels" in config.PROFILE
    assert "software engineer" in config.PROFILE["titles"]


def test_load_profile_custom_path(tmp_path):
    import json
    import config

    custom = {"titles": ["rust engineer"], "levels": ["senior"]}
    profile_file = tmp_path / "custom_profile.json"
    profile_file.write_text(json.dumps(custom))

    loaded = config.load_profile(profile_file)
    assert loaded == custom
    assert config.PROFILE == custom


def test_load_profile_env_var(tmp_path, monkeypatch):
    import json
    import config

    custom = {"titles": ["go engineer"], "levels": ["staff"]}
    profile_file = tmp_path / "env_profile.json"
    profile_file.write_text(json.dumps(custom))

    monkeypatch.setenv("PROFILE_PATH", str(profile_file))
    loaded = config.load_profile()
    assert loaded == custom
    assert config.PROFILE == custom


def test_load_profile_cli_arg(tmp_path, monkeypatch):
    import json
    import config

    custom = {"titles": ["devops engineer"], "levels": ["lead"]}
    profile_file = tmp_path / "cli_profile.json"
    profile_file.write_text(json.dumps(custom))

    monkeypatch.delenv("PROFILE_PATH", raising=False)
    monkeypatch.setattr(sys, "argv", ["app", "--profile", str(profile_file)])
    loaded = config.load_profile()
    assert loaded == custom
    assert config.PROFILE == custom


def test_load_profile_missing_fallback(tmp_path):
    import config
    missing = tmp_path / "non_existent.json"
    loaded = config.load_profile(missing)
    assert loaded == config.DEFAULT_PROFILE
