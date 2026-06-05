def normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper()


def require_ticker(ticker: str) -> str:
    normalized_ticker = normalize_ticker(ticker)
    if not normalized_ticker:
        raise ValueError("Ticker is required.")
    return normalized_ticker
