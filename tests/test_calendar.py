import pytest
from datetime import datetime, timezone
from plugins.calendar.calendar import Calendar


def test_fetch_ics_events_color_padding_and_error_resilience(monkeypatch):
    cal = Calendar({"id": "calendar"})

    sample_ics = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Example Corp.//EN
BEGIN:VEVENT
UID:uid1@example.com
DTSTAMP:20261001T120000Z
DTSTART:20261006T140000Z
DTEND:20261006T150000Z
SUMMARY:Event 1
END:VEVENT
END:VCALENDAR"""

    def mock_fetch(url):
        if url == "https://bad.url/fail.ics":
            raise RuntimeError("Network error")
        import icalendar
        return icalendar.Calendar.from_ical(sample_ics)

    monkeypatch.setattr(cal, "fetch_calendar", mock_fetch)

    urls = [
        "https://good1.url/cal.ics",
        "https://bad.url/fail.ics",
        "https://good2.url/cal.ics"
    ]
    # Provide only 1 color for 3 URLs
    colors = ["#123456"]

    start = datetime(2026, 10, 6, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 7, 0, 0, tzinfo=timezone.utc)

    events = cal.fetch_ics_events(urls, colors, timezone.utc, start, end)

    # 2 valid events should be returned despite 1 failing URL
    assert len(events) == 2
    assert events[0]["title"] == "Event 1"
    assert events[0]["backgroundColor"] == "#123456"
    # Second successful event gets an automatic padded color
    assert events[1]["backgroundColor"] != "#123456"
