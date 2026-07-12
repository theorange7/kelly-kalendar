"""Tests for kelly.caldav — CalDAV protocol logic with mocked HTTP."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from kelly.caldav import (
    CalDavError,
    discover_calendar_home,
    fetch_events,
    get_events,
    list_calendars,
)

PROPFIND_HOME_RESPONSE = b"""<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
  <d:response>
    <d:href>/caldav/index.php/principals/user123/</d:href>
    <d:propstat>
      <d:prop>
        <cal:calendar-home-set>
          <d:href>/caldav/index.php/calendars/user123/</d:href>
        </cal:calendar-home-set>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>"""

PROPFIND_CALENDARS_RESPONSE = b"""<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
  <d:response>
    <d:href>/caldav/index.php/calendars/user123/</d:href>
    <d:propstat>
      <d:prop>
        <d:displayname>Calendars</d:displayname>
        <d:resourcetype><d:collection/></d:resourcetype>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
  <d:response>
    <d:href>/caldav/index.php/calendars/user123/work/</d:href>
    <d:propstat>
      <d:prop>
        <d:displayname>Work</d:displayname>
        <d:resourcetype><d:collection/><cal:calendar/></d:resourcetype>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
  <d:response>
    <d:href>/caldav/index.php/calendars/user123/personal/</d:href>
    <d:propstat>
      <d:prop>
        <d:displayname>Personal</d:displayname>
        <d:resourcetype><d:collection/><cal:calendar/></d:resourcetype>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>"""

REPORT_EVENTS_RESPONSE = b"""<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
  <d:response>
    <d:href>/caldav/index.php/calendars/user123/work/event1.ics</d:href>
    <d:propstat>
      <d:prop>
        <d:getetag>"abc123"</d:getetag>
        <cal:calendar-data>BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:event-001@example.com
SUMMARY:Team Standup
LOCATION:Room 42
DTSTART:20250101T090000Z
DTEND:20250101T093000Z
END:VEVENT
END:VCALENDAR</cal:calendar-data>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>"""


def _report_response_at(start: datetime) -> bytes:
    """A single-event REPORT response with a dynamic DTSTART, for tests that go
    through get_events() (which windows against a live `now`)."""
    dtstart = start.strftime("%Y%m%dT%H%M%SZ")
    dtend = (start + timedelta(minutes=30)).strftime("%Y%m%dT%H%M%SZ")
    return (
        """<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
  <d:response>
    <d:href>/calendars/work/event-001.ics</d:href>
    <d:propstat>
      <d:prop>
        <d:getetag>"abc123"</d:getetag>
        <cal:calendar-data>BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:event-001@example.com
SUMMARY:Team Standup
LOCATION:Room 42
DTSTART:%s
DTEND:%s
END:VEVENT
END:VCALENDAR</cal:calendar-data>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>"""
        % (dtstart, dtend)
    ).encode("utf-8")


def _mock_session_response(status_code: int, content: bytes):
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.text = content.decode("utf-8")
    return resp


class TestDiscoverCalendarHome:
    def test_extracts_home_url(self):
        session = MagicMock()
        session.request.return_value = _mock_session_response(207, PROPFIND_HOME_RESPONSE)

        result = discover_calendar_home(session, "https://caldav.example.com/principals/user123/")

        assert result == "https://caldav.example.com/caldav/index.php/calendars/user123/"

    def test_raises_on_non_207(self):
        session = MagicMock()
        session.request.return_value = _mock_session_response(401, b"Unauthorized")

        with pytest.raises(CalDavError, match="HTTP 401"):
            discover_calendar_home(session, "https://caldav.example.com/principals/user123/")

    def test_raises_when_home_set_missing(self):
        empty_response = b"""<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/principals/user/</d:href>
    <d:propstat>
      <d:prop/>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>"""
        session = MagicMock()
        session.request.return_value = _mock_session_response(207, empty_response)

        with pytest.raises(CalDavError, match="calendar-home-set not found"):
            discover_calendar_home(session, "https://caldav.example.com/principals/user/")


class TestListCalendars:
    def test_lists_calendars_only(self):
        session = MagicMock()
        session.request.return_value = _mock_session_response(207, PROPFIND_CALENDARS_RESPONSE)

        calendars = list_calendars(session, "https://caldav.example.com/caldav/index.php/calendars/user123/")

        assert len(calendars) == 2
        assert calendars[0]["name"] == "Work"
        assert calendars[1]["name"] == "Personal"
        assert "/work/" in calendars[0]["href"]
        assert "/personal/" in calendars[1]["href"]


class TestFetchEvents:
    def test_parses_icalendar_event(self):
        session = MagicMock()
        session.request.return_value = _mock_session_response(207, REPORT_EVENTS_RESPONSE)

        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end = datetime(2025, 1, 2, tzinfo=timezone.utc)
        events = fetch_events(session, "https://caldav.example.com/calendars/work/", start, end)

        assert len(events) == 1
        assert events[0]["uid"] == "event-001@example.com"
        assert events[0]["summary"] == "Team Standup"
        assert events[0]["location"] == "Room 42"
        assert events[0]["all_day"] is False
        assert "2025-01-01" in events[0]["start"]

    def test_parses_attendees_organizer_description(self):
        body = b"""<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
  <d:response>
    <d:href>/caldav/index.php/calendars/user123/work/event2.ics</d:href>
    <d:propstat>
      <d:prop>
        <cal:calendar-data>BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:event-002@example.com
SUMMARY:Planning Sync
DESCRIPTION:Quarterly roadmap review.
DTSTART:20250101T090000Z
DTEND:20250101T093000Z
ORGANIZER;CN=Alice Boss:mailto:alice@example.com
ATTENDEE;CN=Alice Boss;PARTSTAT=ACCEPTED;ROLE=REQ-PARTICIPANT:mailto:alice@example.com
ATTENDEE;CN=Bob Dev;PARTSTAT=NEEDS-ACTION;ROLE=OPT-PARTICIPANT:mailto:bob@example.com
END:VEVENT
END:VCALENDAR</cal:calendar-data>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>"""
        session = MagicMock()
        session.request.return_value = _mock_session_response(207, body)

        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end = datetime(2025, 1, 2, tzinfo=timezone.utc)
        events = fetch_events(session, "https://caldav.example.com/calendars/work/", start, end)

        assert len(events) == 1
        ev = events[0]
        assert ev["description"] == "Quarterly roadmap review."
        assert ev["organizer"] == {"name": "Alice Boss", "email": "alice@example.com"}
        assert ev["attendees"] == [
            {"name": "Alice Boss", "email": "alice@example.com", "status": "ACCEPTED", "role": "REQ-PARTICIPANT"},
            {"name": "Bob Dev", "email": "bob@example.com", "status": "NEEDS-ACTION", "role": "OPT-PARTICIPANT"},
        ]

    def test_event_without_people_has_empty_defaults(self):
        session = MagicMock()
        session.request.return_value = _mock_session_response(207, REPORT_EVENTS_RESPONSE)

        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end = datetime(2025, 1, 2, tzinfo=timezone.utc)
        events = fetch_events(session, "https://caldav.example.com/calendars/work/", start, end)

        assert events[0]["organizer"] is None
        assert events[0]["attendees"] == []
        assert events[0]["description"] == ""

    def test_clamps_events_outside_window(self):
        """Recurrence overrides outside [start, end] are dropped even if the
        server ignores <c:expand> and returns their real (out-of-window) dates."""
        start = datetime(2026, 7, 12, tzinfo=timezone.utc)
        end = start + timedelta(days=7)
        in_win = (start + timedelta(days=1)).strftime("%Y%m%dT%H%M%SZ")
        out_win = (start + timedelta(days=300)).strftime("%Y%m%dT%H%M%SZ")
        body = (
            """<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
  <d:response>
    <d:href>/calendars/work/series.ics</d:href>
    <d:propstat>
      <d:prop>
        <cal:calendar-data>BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:in@example.com
SUMMARY:In Window
DTSTART:%s
DTEND:%s
END:VEVENT
BEGIN:VEVENT
UID:out@example.com
SUMMARY:Out Of Window
DTSTART:%s
DTEND:%s
END:VEVENT
END:VCALENDAR</cal:calendar-data>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>"""
            % (in_win, in_win, out_win, out_win)
        ).encode("utf-8")

        session = MagicMock()
        session.request.return_value = _mock_session_response(207, body)
        events = fetch_events(session, "https://caldav.example.com/calendars/work/", start, end)

        assert [e["summary"] for e in events] == ["In Window"]


class TestGetEvents:
    def test_end_to_end_with_filter(self):
        home_response = _mock_session_response(207, PROPFIND_HOME_RESPONSE)
        cal_response = _mock_session_response(207, PROPFIND_CALENDARS_RESPONSE)
        # Event dated inside the live 7-day window so get_events()'s window clamp
        # keeps it — this test exercises the calendar filter, not date filtering.
        events_response = _mock_session_response(
            207, _report_response_at(datetime.now(timezone.utc) + timedelta(hours=1))
        )

        session = MagicMock()
        session.request.side_effect = [home_response, cal_response, events_response]

        with patch("kelly.caldav.requests.Session", return_value=session):
            events = get_events(
                "https://caldav.example.com/principals/user123/",
                "user",
                "pass",
                days=7,
                calendar_filter="Work",
            )

        assert len(events) == 1
        assert events[0]["calendar"] == "Work"

    def test_raises_when_no_calendars_match(self):
        home_response = _mock_session_response(207, PROPFIND_HOME_RESPONSE)
        cal_response = _mock_session_response(207, PROPFIND_CALENDARS_RESPONSE)

        session = MagicMock()
        session.request.side_effect = [home_response, cal_response]

        with patch("kelly.caldav.requests.Session", return_value=session):
            with pytest.raises(CalDavError, match="No matching calendars"):
                get_events(
                    "https://caldav.example.com/principals/user123/",
                    "user",
                    "pass",
                    calendar_filter="nonexistent",
                )
