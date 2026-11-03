class TSEMarketError(Exception):
    """Base exception."""

class DataSourceError(TSEMarketError):
    """TSETMC unavailable or response malformed."""

class InstrumentNotFound(TSEMarketError):
    """Ticker or identifier not in TDA."""

class AmbiguousTicker(TSEMarketError):
    """Ticker shared by multiple instrument identifiers."""
