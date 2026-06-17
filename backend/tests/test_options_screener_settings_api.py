from fastapi.testclient import TestClient

from conftest import make_api


def test_settings_api_returns_global_defaults(tmp_path):
    api = make_api(
        options_screeners_database_path=tmp_path / "options-screeners.sqlite3",
    )

    with TestClient(api) as client:
        response = client.get("/options-screeners/settings")

    assert response.status_code == 200
    assert response.json() == {
        "ticker_lists": {"csp_cc": [], "cs": []},
        "filters": {
            "csp": default_filters(),
            "cc": default_filters(),
            "cs": {
                **default_filters(),
                "strategy_types": [
                    "put_credit_spread",
                    "call_credit_spread",
                ],
                "spread_widths": [5.0],
            },
        },
    }


def test_ticker_list_endpoints_share_csp_cc_and_keep_cs_separate(tmp_path):
    api = make_api(
        options_screeners_database_path=tmp_path / "options-screeners.sqlite3",
    )

    with TestClient(api) as client:
        csp_cc_response = client.put(
            "/options-screeners/settings/ticker-lists/csp_cc",
            json={"tickers": [" aapl,MSFT ", "aapl\nBRK.b"]},
        )
        cs_response = client.put(
            "/options-screeners/settings/ticker-lists/cs",
            json={"tickers": ["SPY QQQ"]},
        )
        settings_response = client.get("/options-screeners/settings")

    assert csp_cc_response.json() == {
        "list_name": "csp_cc",
        "tickers": ["AAPL", "MSFT", "BRK.B"],
    }
    assert cs_response.json()["tickers"] == ["SPY", "QQQ"]
    assert settings_response.json()["ticker_lists"] == {
        "csp_cc": ["AAPL", "MSFT", "BRK.B"],
        "cs": ["SPY", "QQQ"],
    }


def test_ticker_list_endpoint_saves_unqualified_but_well_formed_tickers(tmp_path):
    api = make_api(
        options_screeners_database_path=tmp_path / "options-screeners.sqlite3",
    )

    with TestClient(api) as client:
        response = client.put(
            "/options-screeners/settings/ticker-lists/csp_cc",
            json={"tickers": ["NOTAREALTICKER"]},
        )

    assert response.status_code == 200
    assert response.json()["tickers"] == ["NOTAREALTICKER"]


def test_filter_endpoints_save_independently_and_validate_ranges(tmp_path):
    api = make_api(
        options_screeners_database_path=tmp_path / "options-screeners.sqlite3",
    )

    with TestClient(api) as client:
        csp_response = client.put(
            "/options-screeners/settings/filters/csp",
            json={**default_filters(), "minimum_annualized_return": 18},
        )
        cs_response = client.put(
            "/options-screeners/settings/filters/cs",
            json={
                **default_filters(),
                "strategy_types": ["call_credit_spread"],
                "spread_widths": [1, 2.5],
            },
        )
        invalid_range_response = client.put(
            "/options-screeners/settings/filters/cc",
            json={**default_filters(), "minimum_dte": 46},
        )
        invalid_cs_response = client.put(
            "/options-screeners/settings/filters/cs",
            json={
                **default_filters(),
                "strategy_types": [],
                "spread_widths": [5],
            },
        )
        settings_response = client.get("/options-screeners/settings")

    assert csp_response.status_code == 200
    assert cs_response.status_code == 200
    assert invalid_range_response.status_code == 422
    assert invalid_cs_response.status_code == 422
    assert settings_response.json()["filters"]["csp"]["minimum_annualized_return"] == 18
    assert settings_response.json()["filters"]["cc"] == default_filters()
    assert settings_response.json()["filters"]["cs"]["strategy_types"] == [
        "call_credit_spread"
    ]


def test_settings_routes_are_not_account_scoped(tmp_path):
    api = make_api(
        options_screeners_database_path=tmp_path / "options-screeners.sqlite3",
    )

    with TestClient(api) as client:
        response = client.get(
            "/options-screeners/settings",
            params={"account": "DU1234567"},
        )

    assert response.status_code == 200
    assert "account" not in response.json()


def default_filters():
    return {
        "version": 1,
        "minimum_dte": 7,
        "maximum_dte": 45,
        "minimum_absolute_delta": 0.15,
        "maximum_absolute_delta": 0.3,
        "minimum_annualized_return": 10.0,
    }
