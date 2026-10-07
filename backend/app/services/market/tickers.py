import re

# 1-7 letters/digits starting with a letter, plus an optional share-class suffix: AAPL, V, BRK.B, BF-B
_TICKER = re.compile(r"[A-Z][A-Z0-9]{0,6}(?:[.-][A-Z0-9]{1,3})?")


def normalize_ticker(raw: str) -> str:
    """Upper-case and validate a ticker symbol: ' brk.b ' -> 'BRK.B'. Raises ValueError if invalid."""
    ticker = raw.strip().upper()
    if not _TICKER.fullmatch(ticker):
        raise ValueError(f"Invalid ticker symbol: {raw!r}")
    return ticker
