"""Report windows in the report time zone (ODOO_TZ), with the UTC bounds that
Odoo datetime fields need."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from .errors import SafetyError

PRESETS = (
    "today",
    "yesterday",
    "last-7-days",
    "last-30-days",
    "this-week",
    "last-week",
    "this-month",
    "last-month",
    "this-quarter",
    "last-quarter",
    "this-year",
    "last-year",
)
SERVER_DATETIME = "%Y-%m-%d %H:%M:%S"
USAGE = (
    "Use date_domain for date fields (invoice_date, date, invoice_date_due) and datetime_domain for "
    "datetime fields (date_order, create_date), which Odoo stores in UTC. Report the window as "
    "first_day to last_day, with the time zone."
)


def _quarter_start(day: dt.date) -> dt.date:
    return dt.date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)


def date_range(preset: str, today: dt.date):
    one = dt.timedelta(days=1)
    if preset == "today":
        return today, today
    if preset == "yesterday":
        return today - one, today - one
    if preset == "last-7-days":
        return today - 7 * one, today - one
    if preset == "last-30-days":
        return today - 30 * one, today - one
    if preset == "this-week":
        return today - today.weekday() * one, today
    if preset == "last-week":
        monday = today - (today.weekday() + 7) * one
        return monday, monday + 6 * one
    if preset == "this-month":
        return today.replace(day=1), today
    if preset == "last-month":
        last = today.replace(day=1) - one
        return last.replace(day=1), last
    if preset == "this-quarter":
        return _quarter_start(today), today
    if preset == "last-quarter":
        last = _quarter_start(today) - one
        return _quarter_start(last), last
    if preset == "this-year":
        return dt.date(today.year, 1, 1), today
    if preset == "last-year":
        return dt.date(today.year - 1, 1, 1), dt.date(today.year - 1, 12, 31)
    raise SafetyError(f"Unknown period {preset!r} (use one of: {', '.join(PRESETS)}, or --from and --to).")


def parse_day(text: str, option: str) -> dt.date:
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        raise SafetyError(f"{option} must be a date like 2026-10-31.") from None


def window(preset=None, tz_name="Europe/Paris", today=None, first=None, last=None, field=None) -> dict:
    tz = ZoneInfo(tz_name)
    today = today or dt.datetime.now(tz).date()
    if preset and (first or last):
        raise SafetyError("Use either a period name or --from/--to, not both.")
    if first or last:
        if not (first and last):
            raise SafetyError("Use --from and --to together.")
        if first > last:
            raise SafetyError("--from must be on or before --to.")
        name = "custom"
    elif preset:
        first, last = date_range(preset, today)
        name = preset
    else:
        raise SafetyError("Give a period name (for example last-month) or --from and --to.")

    start = dt.datetime.combine(first, dt.time.min, tzinfo=tz).astimezone(dt.timezone.utc)
    end = dt.datetime.combine(last + dt.timedelta(days=1), dt.time.min, tzinfo=tz).astimezone(dt.timezone.utc)
    utc_start = start.strftime(SERVER_DATETIME)
    utc_end = end.strftime(SERVER_DATETIME)
    target = field or "FIELD"
    return {
        "period": name,
        "timezone": tz_name,
        "today": today.isoformat(),
        "first_day": first.isoformat(),
        "last_day": last.isoformat(),
        "days": (last - first).days + 1,
        "utc_start": utc_start,
        "utc_end_exclusive": utc_end,
        "date_domain": [[target, ">=", first.isoformat()], [target, "<=", last.isoformat()]],
        "datetime_domain": [[target, ">=", utc_start], [target, "<", utc_end]],
        "usage": USAGE,
    }
