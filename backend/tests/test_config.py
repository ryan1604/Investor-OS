from app.config import alpha_vantage_api_key


def test_alpha_vantage_api_key_uses_dotenv_not_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "ALPHA_VANTAGE_API_KEY=file-key\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "env-key")

    assert alpha_vantage_api_key() == "file-key"


def test_alpha_vantage_api_key_loads_from_dotenv(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "OTHER=value\nALPHA_VANTAGE_API_KEY='file-key'\n",
        encoding="utf-8",
    )

    assert alpha_vantage_api_key() == "file-key"
