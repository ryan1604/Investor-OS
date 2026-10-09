import pytest

from app.config import Settings, get_settings


@pytest.fixture
def isolated_settings(monkeypatch, tmp_path):
    backend = tmp_path / "backend"
    backend.mkdir()
    monkeypatch.chdir(backend)
    get_settings.cache_clear()
    yield backend
    get_settings.cache_clear()


def test_flex_settings_load_local_and_parent_values(isolated_settings, monkeypatch):
    (isolated_settings / ".env").write_text(
        'IBKR_FLEX_TOKEN="local-test-token"\n', encoding="utf-8"
    )
    (isolated_settings.parent / ".env").write_text(
        "IBKR_FLEX_TOKEN=parent-test-token\nIBKR_FLEX_QUERY_ID='12345'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("IBKR_FLEX_TOKEN", "environment-test-token")
    settings = get_settings()
    assert settings.ibkr_flex_token.get_secret_value() == "local-test-token"
    assert settings.ibkr_flex_query_id == "12345"
    assert settings.ibkr_flex_configured
    assert "local-test-token" not in repr(settings)
    assert "ibkr_flex_token" not in settings.model_dump()
    assert "local-test-token" not in settings.model_dump_json()


@pytest.mark.parametrize("contents", [
    "", "IBKR_FLEX_TOKEN=test-token\n", "IBKR_FLEX_QUERY_ID=12345\n",
    'IBKR_FLEX_TOKEN=""\nIBKR_FLEX_QUERY_ID=12345\n',
    'IBKR_FLEX_TOKEN="   "\nIBKR_FLEX_QUERY_ID=12345\n',
])
def test_missing_or_partial_flex_configuration_is_disabled(isolated_settings, contents):
    (isolated_settings / ".env").write_text(contents, encoding="utf-8")
    assert not get_settings().ibkr_flex_configured


def test_flex_environment_alone_does_not_enable_sync(isolated_settings, monkeypatch):
    monkeypatch.setenv("IBKR_FLEX_TOKEN", "environment-test-token")
    monkeypatch.setenv("IBKR_FLEX_QUERY_ID", "12345")
    assert not get_settings().ibkr_flex_configured
    assert not Settings().ibkr_flex_configured


def test_blank_local_token_does_not_fall_back_to_parent(isolated_settings):
    (isolated_settings / ".env").write_text("IBKR_FLEX_TOKEN=\n", encoding="utf-8")
    (isolated_settings.parent / ".env").write_text(
        "IBKR_FLEX_TOKEN=parent-test-token\nIBKR_FLEX_QUERY_ID=12345\n",
        encoding="utf-8",
    )
    assert not get_settings().ibkr_flex_configured


def test_alpha_vantage_api_key_uses_dotenv_not_environment(monkeypatch, isolated_settings):
    (isolated_settings / ".env").write_text(
        "ALPHA_VANTAGE_API_KEY=file-key\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "env-key")

    assert get_settings().alpha_vantage_api_key == "file-key"


def test_alpha_vantage_api_key_loads_from_dotenv(isolated_settings):
    (isolated_settings / ".env").write_text(
        "OTHER=value\nALPHA_VANTAGE_API_KEY='file-key'\n",
        encoding="utf-8",
    )

    assert get_settings().alpha_vantage_api_key == "file-key"
