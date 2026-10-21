"""The app's notion of "today". Cloud Run runs in UTC; set APP_TIMEZONE (e.g. Asia/Kolkata) so
recurring entries and defaults use your calendar day."""
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo


def today() -> date:
    return datetime.now(ZoneInfo(os.environ.get("APP_TIMEZONE", "UTC").strip() or "UTC")).date()
