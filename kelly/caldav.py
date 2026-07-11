"""CalDAV protocol logic: discovery, listing, and event fetching."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin

import requests
from icalendar import Calendar
from requests.auth import HTTPDigestAuth

NS = {
    "d": "DAV:",
    "cal": "urn:ietf:params:xml:ns:caldav",
}


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


def fetch_events(session: requests.Session, calendar_url: str, start: datetime, end: datetime) -> list[dict]:
    body = f"""<?xml version="1.0" encoding="utf-8" ?>
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <d:getetag/>
    <c:calendar-data/>
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
            events.append({
                "uid": str(component.get("uid", "")),
                "summary": str(component.get("summary", "")),
                "location": str(component.get("location", "")),
                "start": _serialize_dt(dtstart.dt) if dtstart else None,
                "end": _serialize_dt(dtend.dt) if dtend else None,
                "all_day": isinstance(dtstart.dt, date) and not isinstance(dtstart.dt, datetime) if dtstart else False,
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
