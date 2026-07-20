"""CalDAV protocol logic: discovery, listing, and event fetching."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin

import requests
from defusedxml import ElementTree as ET
from icalendar import Calendar
from requests.auth import HTTPDigestAuth

NS = {
    "d": "DAV:",
    "cal": "urn:ietf:params:xml:ns:caldav",
}

# Free-text event fields are attacker-influenceable (anyone who can send an
# invite controls them) and flow into the model's context. Cap their length to
# bound both prompt-injection payload size and context bloat / parser stress.
MAX_TEXT_FIELD = 2000

# Upper bound on the look-ahead window (~10 years) to avoid timedelta overflow
# and runaway recurrence expansion on the CalDAV server.
MAX_DAYS = 3650


def _text(component, key: str) -> str:
    """Coerce a VEVENT text property to a bounded plain string."""
    s = str(component.get(key, ""))
    return s if len(s) <= MAX_TEXT_FIELD else s[:MAX_TEXT_FIELD] + "…[truncated]"


class CalDavError(RuntimeError):
    pass


def _propfind(session: requests.Session, url: str, body: str, depth: str = "0") -> ET.Element:
    headers = {"Depth": depth, "Content-Type": "application/xml; charset=utf-8"}
    resp = session.request("PROPFIND", url, data=body, headers=headers, timeout=15)
    if resp.status_code != 207:
        raise CalDavError(f"PROPFIND {url} failed: HTTP {resp.status_code}: {resp.text[:300]}")
    return ET.fromstring(resp.content)


def discover_calendar_home(session: requests.Session, principal_url: str) -> str:
    body = """<?xml version="1.0" encoding="utf-8" ?>
<d:propfind xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <cal:calendar-home-set/>
  </d:prop>
</d:propfind>"""
    root = _propfind(session, principal_url, body, depth="0")
    href_el = root.find(".//cal:calendar-home-set/d:href", NS)
    if href_el is None or not href_el.text:
        raise CalDavError("calendar-home-set not found in PROPFIND response — check the principal URL")
    return urljoin(principal_url, href_el.text)


def list_calendars(session: requests.Session, home_set_url: str) -> list[dict]:
    body = """<?xml version="1.0" encoding="utf-8" ?>
<d:propfind xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <d:displayname/>
    <d:resourcetype/>
  </d:prop>
</d:propfind>"""
    root = _propfind(session, home_set_url, body, depth="1")
    calendars = []
    for response in root.findall("d:response", NS):
        href_el = response.find("d:href", NS)
        if href_el is None:
            continue
        resourcetype = response.find(".//d:resourcetype", NS)
        is_calendar = resourcetype is not None and resourcetype.find("cal:calendar", NS) is not None
        if not is_calendar:
            continue
        name_el = response.find(".//d:displayname", NS)
        name = name_el.text if name_el is not None and name_el.text else "(unnamed)"
        calendars.append({"href": urljoin(home_set_url, href_el.text), "name": name})
    return calendars


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _serialize_dt(value) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _to_utc(value) -> datetime | None:
    """Normalize a VEVENT date/datetime to an aware UTC datetime for windowing.

    A bare date (all-day) becomes UTC midnight; a naive datetime is assumed UTC.
    """
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    return None


def _email(value) -> str:
    """Strip a leading mailto: (case-insensitive) from a CalDAV address value."""
    s = str(value).strip()
    return s[7:] if s.lower().startswith("mailto:") else s


def _parse_person(value) -> dict | None:
    """Normalize an ORGANIZER/ATTENDEE address into {name, email[, status, role]}.

    CN → name, PARTSTAT → status (accepted/declined/tentative/needs-action),
    ROLE → role (req/opt participant). status/role are only present on ATTENDEEs.
    """
    if value is None:
        return None
    params = getattr(value, "params", {}) or {}
    person = {
        "name": str(params["CN"]) if "CN" in params else None,
        "email": _email(value),
    }
    if "PARTSTAT" in params:
        person["status"] = str(params["PARTSTAT"])
    if "ROLE" in params:
        person["role"] = str(params["ROLE"])
    return person


def _parse_attendees(component) -> list[dict]:
    """Extract the ATTENDEE list from a VEVENT (single or repeated property)."""
    raw = component.get("attendee")
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    return [p for p in (_parse_person(a) for a in items) if p is not None]


def fetch_events(session: requests.Session, calendar_url: str, start: datetime, end: datetime) -> list[dict]:
    body = f"""<?xml version="1.0" encoding="utf-8" ?>
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <d:getetag/>
    <c:calendar-data>
      <c:expand start="{_fmt(start)}" end="{_fmt(end)}"/>
    </c:calendar-data>
  </d:prop>
  <c:filter>
    <c:comp-filter name="VCALENDAR">
      <c:comp-filter name="VEVENT">
        <c:time-range start="{_fmt(start)}" end="{_fmt(end)}"/>
      </c:comp-filter>
    </c:comp-filter>
  </c:filter>
</c:calendar-query>"""
    headers = {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"}
    resp = session.request("REPORT", calendar_url, data=body, headers=headers, timeout=20)
    if resp.status_code != 207:
        raise CalDavError(f"REPORT {calendar_url} failed: HTTP {resp.status_code}: {resp.text[:300]}")

    root = ET.fromstring(resp.content)
    events = []
    for response in root.findall("d:response", NS):
        cal_data_el = response.find(".//{urn:ietf:params:xml:ns:caldav}calendar-data")
        if cal_data_el is None or not cal_data_el.text:
            continue
        cal = Calendar.from_ical(cal_data_el.text)
        for component in cal.walk("VEVENT"):
            dtstart = component.get("dtstart")
            dtend = component.get("dtend")
            # Defensive window clamp: <c:expand> above asks the server to expand
            # recurrences into in-window instances, but a server that ignores it
            # returns recurrence overrides outside the window (their real dates).
            # Drop anything that doesn't overlap [start, end] so `days` is always
            # honored regardless of server behavior.
            ev_start = _to_utc(dtstart.dt) if dtstart else None
            ev_end = _to_utc(dtend.dt) if dtend else None
            if ev_start is not None and ev_start >= end:
                continue
            if ev_end is not None and ev_end <= start:
                continue
            events.append({
                "uid": str(component.get("uid", "")),
                "summary": _text(component, "summary"),
                "location": _text(component, "location"),
                "description": _text(component, "description"),
                "start": _serialize_dt(dtstart.dt) if dtstart else None,
                "end": _serialize_dt(dtend.dt) if dtend else None,
                "all_day": isinstance(dtstart.dt, date) and not isinstance(dtstart.dt, datetime) if dtstart else False,
                "organizer": _parse_person(component.get("organizer")),
                "attendees": _parse_attendees(component),
            })
    return events


def get_events(
    principal_url: str,
    username: str,
    password: str,
    days: int = 7,
    calendar_filter: str | None = None,
) -> list[dict]:
    """
    Fetch upcoming events across all matching calendars.
    Returns a flat, sorted list of event dicts.
    """
    # Clamp the window: `days` is model-chosen (and can be influenced by injected
    # event content). Reject nonsensical values and prevent a huge value from
    # overflowing timedelta (crash) or amplifying server-side recurrence expansion.
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise CalDavError("`days` must be an integer between 1 and 3650")
    days = max(1, min(days, MAX_DAYS))

    session = requests.Session()
    session.auth = HTTPDigestAuth(username, password)

    home_set_url = discover_calendar_home(session, principal_url)
    calendars = list_calendars(session, home_set_url)

    if calendar_filter:
        calendars = [c for c in calendars if calendar_filter.lower() in c["name"].lower()]

    if not calendars:
        raise CalDavError("No matching calendars found")

    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)

    all_events = []
    for cal in calendars:
        events = fetch_events(session, cal["href"], now, end)
        for e in events:
            e["calendar"] = cal["name"]
        all_events.extend(events)

    all_events.sort(key=lambda e: e["start"] or "")
    return all_events
