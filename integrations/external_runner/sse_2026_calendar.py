"""2026 SSE session classification from 上证公告〔2025〕45号.

The closure list is the notice fetched on 2026-11-20. A date outside
2026-01-01 through 2026-12-31 is unknown. This module does not call an
exchange and does not treat a weekday as a session by itself.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

_DATA = json.loads(Path(__file__).with_name("calendars").joinpath("sse_2026_shangzheng_2025_45.json").read_text(encoding="utf-8"))
CALENDAR_ID = _DATA["calendar_id"]
COVERAGE_START = date.fromisoformat(_DATA["coverage_start"])
COVERAGE_END = date.fromisoformat(_DATA["coverage_end"])
CLOSURES = [
    (item["name"], date.fromisoformat(item["start"]), date.fromisoformat(item["end"]))
    for item in _DATA["closures"]
]
WEEKEND_WORKDAYS = {date.fromisoformat(item) for item in _DATA["state_council_weekend_workdays"]}


def classify_session(day: date) -> tuple[str, str]:
    """Return open, holiday, weekend, or unknown, and the reason to show."""
    if day < COVERAGE_START or day > COVERAGE_END:
        return (
            "unknown",
            "decision date "
            + day.isoformat()
            + " is outside "
            + CALENDAR_ID
            + " coverage "
            + COVERAGE_START.isoformat()
            + "/"
            + COVERAGE_END.isoformat()
            + ". No session was verified.",
        )
    for name, start, end in CLOSURES:
        if start <= day <= end:
            return (
                "holiday",
                "decision date "
                + day.isoformat()
                + " is inside the "
                + name
                + " closure "
                + start.isoformat()
                + "/"
                + end.isoformat()
                + " in 上证公告〔2025〕45号.",
            )
    if day.weekday() >= 5:
        extra = ""
        if day in WEEKEND_WORKDAYS:
            extra = " The State Council marks this weekend as a workday. That adjustment does not open the exchange."
        return (
            "weekend",
            "decision date "
            + day.isoformat()
            + " is Saturday or Sunday. Saturday and Sunday are not exchange sessions."
            + extra,
        )
    return (
        "open",
        "decision date "
        + day.isoformat()
        + " is a 2026 weekday outside the closures in 上证公告〔2025〕45号.",
    )


def coverage_line() -> str:
    return (
        "calendar_id: "
        + CALENDAR_ID
        + "\ncalendar_coverage: "
        + COVERAGE_START.isoformat()
        + "/"
        + COVERAGE_END.isoformat()
        + "\ncalendar_source: 上海证券交易所 上证公告〔2025〕45号"
    )


def _self_check() -> None:
    closed = [date(2026, 10, day) for day in (1, 2, 5, 6, 7)]
    for item in closed:
        status, _text = classify_session(item)
        if status != "holiday":
            raise RuntimeError(item.isoformat())
    if classify_session(date(2026, 10, 8))[0] != "open":
        raise RuntimeError("2026-10-08")
    if classify_session(date(2026, 10, 10))[0] != "weekend":
        raise RuntimeError("2026-10-10")
    if classify_session(date(2027, 1, 1))[0] != "unknown":
        raise RuntimeError("2027-01-01")


_self_check()
