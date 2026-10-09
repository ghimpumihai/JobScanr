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


