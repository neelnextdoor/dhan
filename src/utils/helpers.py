from __future__ import annotations

from datetime import datetime, time


def ist_now() -> datetime:
    """Return current IST time (UTC+5:30). Naive datetime for simplicity."""
    import pytz
    try:
        return datetime.now(pytz.timezone("Asia/Kolkata")).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def parse_time(t: str) -> time:
    return time.fromisoformat(t)


def format_currency(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}₹{value:,.2f}"


def format_pct(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"
