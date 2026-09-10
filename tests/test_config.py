from src.config.settings import load_settings


def test_load_settings_reads_environment(monkeypatch):
    monkeypatch.setenv("APP_NAME", "graphone-intelligence-pipeline")
    monkeypatch.setenv("ENVIRONMENT", "development")

    settings = load_settings()

    assert settings.app_name == "graphone-intelligence-pipeline"
    assert settings.environment == "development"


def test_load_settings_uses_defaults():
    settings = load_settings()

    assert settings.log_level == "INFO"
    assert settings.max_concurrency == 8
