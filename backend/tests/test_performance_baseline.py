from pathlib import Path

from app.config import Settings


def test_baseline_finishes_with_all_databases_isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from scripts import performance_baseline

    create_app = performance_baseline.create_app

    def create_isolated_app(settings, overrides):
        paths = [
            Path(getattr(settings, name))
            for name in Settings.model_fields
            if name.endswith("_database_path")
        ]
        assert all(path.is_absolute() for path in paths)
        assert len({path.parent for path in paths}) == 1
        assert all(path.parent.name.startswith("investor-os-baseline-") for path in paths)
        assert all(path.parent.is_dir() for path in paths)
        return create_app(settings, overrides)

    monkeypatch.setattr(performance_baseline, "create_app", create_isolated_app)
    metrics = performance_baseline.run_baseline(
        iterations=1, position_count=5, chain_rows=5,
    )

    assert len(metrics["http"]) == 6
    assert len(metrics["websocket"]) == 4
    assert len(metrics["concurrent_http"]) == 7
    assert all(
        result["status_counts"] == {"200": 4}
        for result in metrics["concurrent_http"].values()
    )
    assert list(tmp_path.rglob("*.sqlite3")) == []
