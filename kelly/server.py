"""Kelly MCP server — exposes CalDAV calendar data as tools for Claude."""

from __future__ import annotations

import sys
from typing import Optional

import requests
from fastmcp import FastMCP
from requests.auth import HTTPDigestAuth

from kelly import __version__
from kelly.caldav import (
    CalDavError,
    discover_calendar_home,
    get_events,
    list_calendars as _discover_calendars,
)
from kelly.credentials import CredentialError, load_credentials

mcp = FastMCP(
    "kelly",
    instructions=(
        "Kelly is your calendar assistant — a local MCP server that reads "
        "your CalDAV schedule so Claude can help you plan your day."
    ),
    version=__version__,
)


def _get_credentials() -> tuple[str, str, str]:
    try:
        return load_credentials()
    except CredentialError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


@mcp.tool
def check_connection() -> dict:
    """Verify that CalDAV credentials are configured and the server is reachable."""
    principal_url, username, password = _get_credentials()
    session = requests.Session()
    session.auth = HTTPDigestAuth(username, password)
    try:
        home_set_url = discover_calendar_home(session, principal_url)
        calendars = _discover_calendars(session, home_set_url)
    except (CalDavError, requests.RequestException) as e:
        return {"status": "error", "message": str(e)}
    return {
        "status": "ok",
        "principal": principal_url,
        "calendars": len(calendars),
    }


@mcp.tool
def list_calendars() -> list[dict]:
    """List the calendars available under the configured CalDAV principal."""
    principal_url, username, password = _get_credentials()
    session = requests.Session()
    session.auth = HTTPDigestAuth(username, password)
    try:
        home_set_url = discover_calendar_home(session, principal_url)
        calendars = _discover_calendars(session, home_set_url)
    except (CalDavError, requests.RequestException) as e:
        return [{"error": str(e)}]
    return [{"name": c["name"]} for c in calendars]


@mcp.tool
def list_upcoming_events(days: int = 7, calendar: Optional[str] = None) -> list[dict]:
    """
    Fetch upcoming calendar events.

    Args:
        days: How many days ahead to fetch (default 7).
        calendar: Optional substring to filter calendars by name (case-insensitive).
    """
    principal_url, username, password = _get_credentials()
    try:
        events = get_events(
            principal_url,
            username,
            password,
            days=days,
            calendar_filter=calendar,
        )
    except (CalDavError, requests.RequestException) as e:
        return [{"error": str(e)}]
    return events


def run():
    """Start the MCP server (stdio transport)."""
    _get_credentials()
    mcp.run()
