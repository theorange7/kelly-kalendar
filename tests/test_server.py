"""Tests for kelly.server — MCP tool wrappers."""

from unittest.mock import patch

from kelly.caldav import CalDavError


MOCK_CREDS = ("https://caldav.example.com/principals/u/", "user", "pass")


class TestCheckConnection:
    def test_returns_ok_on_success(self):
        with patch("kelly.server.load_credentials", return_value=MOCK_CREDS):
            with patch("kelly.server.discover_calendar_home", return_value="https://caldav.example.com/cal/"):
                with patch("kelly.server._discover_calendars", return_value=[{"name": "Work"}, {"name": "Home"}]):
                    from kelly.server import check_connection
                    result = check_connection()

        assert result["status"] == "ok"
        assert result["calendars"] == 2

    def test_returns_error_on_caldav_failure(self):
        with patch("kelly.server.load_credentials", return_value=MOCK_CREDS):
            with patch("kelly.server.discover_calendar_home", side_effect=CalDavError("connection refused")):
                from kelly.server import check_connection
                result = check_connection()

        assert result["status"] == "error"
        # Generic message to the client; raw CalDAV detail stays host-side (F-08).
        assert "check_connection" in result["message"]
        assert "connection refused" not in result["message"]


class TestListCalendars:
    def test_returns_calendar_names(self):
        with patch("kelly.server.load_credentials", return_value=MOCK_CREDS):
            with patch("kelly.server.discover_calendar_home", return_value="https://caldav.example.com/cal/"):
                with patch("kelly.server._discover_calendars", return_value=[{"name": "Work"}, {"name": "Personal"}]):
                    from kelly.server import list_calendars
                    result = list_calendars()

        assert result == [{"name": "Work"}, {"name": "Personal"}]


class TestListUpcomingEvents:
    def test_returns_events(self):
        mock_events = [
            {"uid": "1", "summary": "Meeting", "start": "2025-01-01T09:00:00+00:00", "calendar": "Work"}
        ]
        with patch("kelly.server.load_credentials", return_value=MOCK_CREDS):
            with patch("kelly.server.get_events", return_value=mock_events):
                from kelly.server import list_upcoming_events
                result = list_upcoming_events(days=7, calendar="Work")

        assert len(result) == 1
        assert result[0]["summary"] == "Meeting"

    def test_returns_error_on_failure(self):
        with patch("kelly.server.load_credentials", return_value=MOCK_CREDS):
            with patch("kelly.server.get_events", side_effect=CalDavError("timeout")):
                from kelly.server import list_upcoming_events
                result = list_upcoming_events()

        # Generic, non-leaking message is returned to the client (F-08); the raw
        # CalDAV detail ("timeout") must not cross into the model's context.
        assert len(result) == 1
        assert "list_upcoming_events" in result[0]["error"]
        assert "timeout" not in result[0]["error"]

    def test_overflow_is_caught(self):
        with patch("kelly.server.load_credentials", return_value=MOCK_CREDS):
            with patch("kelly.server.get_events", side_effect=OverflowError("too big")):
                from kelly.server import list_upcoming_events
                result = list_upcoming_events(days=10**12)

        assert len(result) == 1 and "error" in result[0]
