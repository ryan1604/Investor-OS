import re

TICKER_PATTERN = re.compile(r"^[A-Z0-9.-]+$")
TICKER_SEPARATOR_PATTERN = re.compile(r"[\s,]+")


def normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper()


def require_ticker(ticker: str) -> str:
    normalized_ticker = normalize_ticker(ticker)
    if not normalized_ticker:
        raise ValueError("Ticker is required.")
    return normalized_ticker


def parse_ticker_tokens(text: str) -> tuple[list[str], list[str]]:
    tickers: list[str] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for token in TICKER_SEPARATOR_PATTERN.split(text.strip()):
        if not token:
            continue
        ticker = normalize_ticker(token)
        if not TICKER_PATTERN.fullmatch(ticker):
            rejected.append(token)
            continue
        if ticker not in seen:
            seen.add(ticker)
            tickers.append(ticker)
    return tickers, rejected
