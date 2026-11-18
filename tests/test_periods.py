import json
from datetime import date

import pytest

from odoo_client.errors import SafetyError
from odoo_client.periods import window

WEDNESDAY = date(2026, 11, 18)


def span(preset, today=WEDNESDAY):
    result = window(preset, "Europe/Paris", today=today)
    return result["first_day"], result["last_day"]


def test_last_month_uses_utc_bounds_across_the_october_clock_change():
    result = window("last-month", "Europe/Paris", today=WEDNESDAY, field="invoice_date")
    assert (result["first_day"], result["last_day"], result["days"]) == ("2026-10-01", "2026-10-31", 31)
    assert result["utc_start"] == "2026-09-30 22:00:00"
    assert result["utc_end_exclusive"] == "2026-10-31 23:00:00"
    assert result["date_domain"] == [["invoice_date", ">=", "2026-10-01"], ["invoice_date", "<=", "2026-10-31"]]
    assert result["datetime_domain"] == [
        ["invoice_date", ">=", "2026-09-30 22:00:00"], ["invoice_date", "<", "2026-10-31 23:00:00"]]


@pytest.mark.parametrize("preset, expected", [
    ("today", ("2026-11-18", "2026-11-18")),
    ("yesterday", ("2026-11-17", "2026-11-17")),
    ("last-7-days", ("2026-11-11", "2026-11-17")),
    ("last-30-days", ("2026-10-19", "2026-11-17")),
    ("this-week", ("2026-11-16", "2026-11-18")),
    ("last-week", ("2026-11-09", "2026-11-15")),
    ("this-month", ("2026-11-01", "2026-11-18")),
    ("this-quarter", ("2026-10-01", "2026-11-18")),
    ("last-quarter", ("2026-07-01", "2026-09-30")),
    ("this-year", ("2026-01-01", "2026-11-18")),
    ("last-year", ("2025-01-01", "2025-12-31")),
])
def test_presets(preset, expected):
    assert span(preset) == expected


def test_year_boundaries():
    assert span("last-month", date(2027, 1, 10)) == ("2026-12-01", "2026-12-31")
    assert span("last-quarter", date(2027, 2, 1)) == ("2026-10-01", "2026-12-31")
    assert span("last-week", date(2027, 1, 3)) == ("2026-12-21", "2026-12-27")


def test_custom_window_and_its_errors():
    result = window(None, "Europe/Paris", today=WEDNESDAY, first=date(2026, 1, 1), last=date(2026, 3, 31))
    assert (result["period"], result["days"]) == ("custom", 90)
    with pytest.raises(SafetyError, match="on or before"):
        window(None, "Europe/Paris", first=date(2026, 3, 1), last=date(2026, 2, 1))
    with pytest.raises(SafetyError, match="together"):
        window(None, "Europe/Paris", first=date(2026, 3, 1))
    with pytest.raises(SafetyError, match="not both"):
        window("last-month", "Europe/Paris", first=date(2026, 3, 1), last=date(2026, 3, 2))
    with pytest.raises(SafetyError, match="Give a period"):
        window(None, "Europe/Paris")


def test_cli_period_needs_no_odoo_settings_and_follows_odoo_tz(run, monkeypatch):
    monkeypatch.setenv("ODOO_TZ", "America/New_York")
    code, out, err = run(["period", "yesterday", "--today", "2026-03-09", "--field", "date_order"])
    assert code == 0, err
    data = json.loads(out)
    assert data["timezone"] == "America/New_York"
    assert (data["utc_start"], data["utc_end_exclusive"]) == ("2026-03-08 05:00:00", "2026-03-09 04:00:00")
    assert data["datetime_domain"][0] == ["date_order", ">=", "2026-03-08 05:00:00"]


def test_cli_period_rejects_a_bad_time_zone(run, monkeypatch):
    monkeypatch.setenv("ODOO_TZ", "Nowhere/Town")
    code, out, err = run(["period", "today"])
    assert code == 1 and "ODOO_TZ" in err


def test_cli_period_rejects_a_bad_date(run):
    code, out, err = run(["period", "--from", "2026-13-01", "--to", "2026-12-31"])
    assert code == 1 and "--from must be a date" in err
