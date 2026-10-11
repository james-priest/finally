from fastapi import HTTPException

from app.services.market import normalize_ticker


def parse_ticker(raw: str) -> str:
    """Normalize a ticker from a request; an invalid one is a 422, like any other bad input."""
    try:
        return normalize_ticker(raw)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
