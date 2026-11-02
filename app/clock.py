from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import get_settings


def today() -> date:
    """„Heute“ in der Zeitzone des Haushalts, unabhängig von der Serverzeitzone."""
    return datetime.now(ZoneInfo(get_settings().timezone)).date()
