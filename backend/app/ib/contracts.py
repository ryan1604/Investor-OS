from datetime import date

from ibapi.contract import Contract

from app.tickers import normalize_ticker


def clean_ib_float(value: float | None) -> float | None:
    if value is None:
        return None
    if abs(value) > 1e100:
        return None
    return value


def clean_ib_price(value: float) -> float | None:
    cleaned_value = clean_ib_float(value)
    if cleaned_value is None or cleaned_value <= 0:
        return None
    return cleaned_value


def market_data_contract(contract: Contract) -> Contract:
    next_contract = Contract()
    next_contract.conId = contract.conId
    next_contract.symbol = contract.symbol
    next_contract.secType = contract.secType
    next_contract.lastTradeDateOrContractMonth = contract.lastTradeDateOrContractMonth
    next_contract.strike = contract.strike
    next_contract.right = contract.right
    next_contract.multiplier = contract.multiplier
    next_contract.exchange = contract.exchange or "SMART"
    next_contract.primaryExchange = contract.primaryExchange
    next_contract.currency = contract.currency
    next_contract.localSymbol = contract.localSymbol
    next_contract.tradingClass = contract.tradingClass
    return next_contract



def clean_ib_int(value: int | float) -> int | None:
    cleaned_value = clean_ib_float(float(value))
    if cleaned_value is None or cleaned_value < 0:
        return None
    return int(cleaned_value)


def parse_ib_bar_date(raw_date: str) -> date | None:
    if len(raw_date) >= 8 and raw_date[:8].isdigit():
        return date.fromisoformat(
            f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}",
        )

    try:
        return date.fromisoformat(raw_date[:10])
    except ValueError:
        return None


def format_ib_expiration(expiration: str) -> str | None:
    if len(expiration) != 8 or not expiration.isdigit():
        return None

    return f"{expiration[:4]}-{expiration[4:6]}-{expiration[6:8]}"


def us_equity_contract(ticker: str) -> Contract:
    contract = Contract()
    contract.symbol = normalize_ticker(ticker)
    contract.secType = "STK"
    contract.exchange = "SMART"
    contract.currency = "USD"
    return contract


def us_option_contract(
    ticker: str,
    *,
    expiration: str,
    strike: float,
    right: str,
) -> Contract:
    contract = Contract()
    contract.symbol = normalize_ticker(ticker)
    contract.secType = "OPT"
    contract.exchange = "SMART"
    contract.currency = "USD"
    contract.lastTradeDateOrContractMonth = expiration.replace("-", "")
    contract.strike = strike
    contract.right = right
    contract.multiplier = "100"
    return contract


def us_option_universe_contract(
    ticker: str,
    *,
    expiration: str,
    right: str,
) -> Contract:
    contract = us_option_contract(
        ticker,
        expiration=expiration,
        strike=0,
        right=right,
    )
    return contract


def us_put_option_universe_contract(
    ticker: str,
    *,
    expiration: str,
) -> Contract:
    return us_option_universe_contract(
        ticker,
        expiration=expiration,
        right="P",
    )
