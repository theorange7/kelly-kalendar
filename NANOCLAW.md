# Using Kelly with NanoClaw

This guide is for anyone who wants to give a [NanoClaw](https://github.com/) agent
read access to their calendar through Kelly. It explains the integration pattern,
why it's shaped the way it is, how to set it up, and the constraints that matter.

Kelly is a **read-only CalDAV** MCP server (Python / `uv` / FastMCP). Wired into a
NanoClaw agent, it gives the agent upcoming events with times, location,
description, organizer, and attendees (with per-invitee RSVP status).

Unlike a typical NanoClaw integration — where credentials are brokered by the
OneCLI gateway and the tool runs *inside* the agent container — Kelly runs as a
**host-side HTTP MCP server** that the container reaches over
`host.docker.internal`. This doc explains why, and how to wire it up.

> A companion copy of this doc lives in the NanoClaw tree at
> `docs/kelly-caldav-bridge.md`. This file is the same content from the Kelly
> repo's side, kept here so Kelly users can find it.

---

## Why a host bridge (the core constraint)

Kelly authenticates to its CalDAV backend with **HTTP Digest auth**
(`HTTPDigestAuth`). Digest is challenge-response: the real password must be
present *in the process that makes the request*. NanoClaw's OneCLI egress proxy
does static header-rewrite injection — it **cannot broker digest auth**.

If your requirement is **"keep the CalDAV credential out of the agent container"**
(a common NanoClaw goal), those two facts rule out running Kelly inside the
container with OneCLI injecting the secret. So:

- Kelly runs on the **host**, where your keychain (and thus the CalDAV
  credential) already lives.
- The agent container talks to it as a **remote HTTP MCP** over the Docker host
  gateway.
- Only calendar **data** crosses into the container. The CalDAV password never
  does — the container holds only a loopback bearer token.

> **Precise security claim:** the CalDAV *password* never enters the container.
> This is **not** "nothing leaves your machine" — your CalDAV backend is a remote
> server, so calendar data is already hosted off-box. The bridge just avoids
> putting the *credential* in the container.

---

## Architecture

```
NanoClaw agent container (Claude Agent SDK, Node/undici HTTP client)
      │  http://host.docker.internal:8787/mcp
      │  Authorization: Bearer <loopback token>
      ▼
serve_http.py  (host, 127.0.0.1:8787)
      │  raw-ASGI bearer-token gate  → 401 without a matching token
      │  FastMCP http_app(path=/mcp, allowed_hosts=[… host.docker.internal …])
      ▼
kelly.server (FastMCP tools)  →  kelly.caldav  →  HTTPDigestAuth
      ▼
your CalDAV backend   (remote; creds from macOS keychain / CALDAV_* env)
```

- **Bound to `127.0.0.1:8787`.** A loopback-bound host service *is* reachable
  from Docker Desktop for Mac containers via `host.docker.internal`, with **no
  LAN exposure**.
- **`allowed_hosts` must include `host.docker.internal`** or FastMCP's
  DNS-rebinding guard rejects the container's requests (400) based on the `Host`
  header it sends. `serve_http.py` sets this for you.
- **Bearer token isolation.** The token (in `.kelly_http_token`, gitignored)
  gates the port so that *only* the agent group whose MCP config carries the
  token can reach Kelly. Other agent-group containers on the same host cannot.

---

## What NanoClaw needs on its side

Reaching a host-side HTTP MCP server requires a NanoClaw that supports **http-type
MCP servers** and bypasses the OneCLI proxy for the local hop. If your NanoClaw
already has this, skip ahead. If not, the required pieces are:

| Piece | Why |
|-------|-----|
| `McpServerConfig` accepts an `http` variant (not just `stdio`) | The Claude Agent SDK already speaks `http` MCP natively (`McpHttpServerConfig`); the agent-runner's own type just has to allow it. |
| **`NO_PROXY` injection for local-bridge hosts** in the agent-runner | OneCLI sets `HTTP_PROXY`/`HTTPS_PROXY` + `NODE_USE_ENV_PROXY=1` but no `NO_PROXY`, so the request to `host.docker.internal` would otherwise tunnel through the gateway and fail. Add `host.docker.internal`/`localhost`/`127.0.0.1` to `NO_PROXY` for the SDK subprocess — scoped so real *remote* MCP servers still get credential injection. |
| `ncl groups config add-mcp-server --url / --headers` | To register an http-type MCP server on an agent group. |

The agent group's container config registers Kelly as:

```json
{ "type": "http",
  "url": "http://host.docker.internal:8787/mcp",
  "headers": { "Authorization": "Bearer <token>" } }
```

---

## Setup

Assumes this repo is cloned locally and CalDAV credentials are stored (macOS
keychain via `kelly setup`, or `CALDAV_*` env fallback).

1. **Generate a bearer token** into the gitignored file the launcher reads,
   and lock down its permissions so other local users can't read it:
   ```bash
   ( umask 077 && openssl rand -hex 32 > .kelly_http_token )
   chmod 600 .kelly_http_token
   ```
   The bridge **fails closed**: without a token it refuses to start rather than
   silently serving your calendar unauthenticated. (To run without auth on a
   fully trusted single-user host, set `KELLY_HTTP_ALLOW_NO_AUTH=1`.)
2. **Run the bridge** (loopback HTTP MCP on :8787):
   ```bash
   uv run python serve_http.py
   ```
   For persistence across reboot, use a launchd unit — see **Durability** below.
3. **Register the MCP server** on the target NanoClaw agent group:
   ```bash
   ncl groups config add-mcp-server --id <group-id> --name kelly \
     --url http://host.docker.internal:8787/mcp \
     --headers "{\"Authorization\":\"Bearer $(cat .kelly_http_token)\"}"
   ```
   No container restart is required if none is running — the next user message
   spawns a fresh container that picks up the config.

---

## Constraints & gotchas

- **Digest auth ⇒ host process.** This is the whole reason for the bridge. If
  your backend uses Basic auth, a simpler in-container path opens up (see
  *Future option*).
- **`allowed_hosts` must list `host.docker.internal`** — otherwise 400 from
  FastMCP's rebinding guard. `serve_http.py` handles this.
- **`NO_PROXY` must cover the local hop** — otherwise the container's request to
  `host.docker.internal` tunnels into the OneCLI gateway and fails. This is on
  the NanoClaw side (see the table above).
- **Loopback binding only.** Keep `KELLY_HTTP_HOST=127.0.0.1`. Binding to
  `0.0.0.0` would expose your calendar to the LAN.
- **Untrusted event content.** Event titles/descriptions come from anyone who
  can invite you and flow verbatim into the agent's context — treat them as
  untrusted input, and don't pair Kelly with an egress/write capability in the
  same agent unless that agent is network-sandboxed (see `THREAT-MODEL.md`, F-01).
- **Read-only.** Kelly exposes three tools and never writes to the calendar:
  `check_connection`, `list_calendars`, `list_upcoming_events`.

`serve_http.py` config via env: `KELLY_HTTP_HOST` (default `127.0.0.1`),
`KELLY_HTTP_PORT` (`8787`), `KELLY_HTTP_PATH` (`/mcp`), `KELLY_HTTP_TOKEN`
(else read from `.kelly_http_token` beside the script).

---

## Durability

The bridge is a **host process**. Run as a bare `nohup … serve_http.py`, it dies
on reboot/logout. For a supervised, auto-starting service, use a launchd unit
(`KeepAlive`, `RunAtLoad`) that runs `uv run python serve_http.py` in this repo
and reads the token from `.kelly_http_token`.

A launchd plist is **machine-specific** (hardcoded install paths), so no plist is
committed here — treat it as per-install setup you generate on each machine. A
minimal shape:

```xml
<!-- ~/Library/LaunchAgents/com.nanoclaw.kelly.plist -->
<key>ProgramArguments</key>
<array>
  <string>/usr/bin/env</string><string>uv</string>
  <string>run</string><string>python</string><string>serve_http.py</string>
</array>
<key>WorkingDirectory</key><string>/ABSOLUTE/PATH/TO/kelly-kalendar</string>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
```

---

## Event data shape

`list_upcoming_events(days=7, calendar=None)` returns a flat, start-sorted list.
Each event:

```jsonc
{
  "uid": "…",
  "summary": "Quarterly Planning",
  "location": "…",
  "description": "…",                       // full event body
  "start": "2026-07-14T09:00:00+00:00",
  "end":   "2026-07-14T10:00:00+00:00",
  "all_day": false,
  "organizer": { "name": "…", "email": "…" },
  "attendees": [                            // per-invitee RSVP
    { "name": "…", "email": "…",
      "status": "ACCEPTED",                 // PARTSTAT: ACCEPTED / NEEDS-ACTION / …
      "role":   "REQ-PARTICIPANT" }         // ROLE: REQ- / OPT-PARTICIPANT
  ],
  "calendar": "Work"
}
```

`organizer` is `null` and `attendees` is `[]` for events without those
properties (e.g. personal blocks with no invitees).

---

## Verifying

- **From the host**, drive the MCP handshake directly against the bridge
  (initialize → `tools/call list_upcoming_events`) with the bearer token, or use
  `check_connection` for a quick liveness probe. Expect no-token → 401,
  initialize → 200 + session, `tools/list` → 3 tools.
- NanoClaw ships an egress smoke test (`scripts/kelly-smoke.ts`) that reproduces
  the real container env (OneCLI proxy + MITM CA + `NODE_USE_ENV_PROXY`) and
  drives the full handshake without spawning an agent — useful to prove the
  `NO_PROXY` local-hop bypass works.
- **Acceptance:** message your agent *"what's on my calendar this week?"* or
  *"who's invited to <event>?"*

---

## Future option

If your CalDAV backend is reachable over HTTPS with **Basic auth**, Kelly could
be patched to Basic auth and run **in-container**, with OneCLI injecting the
`Authorization` header — removing the host process entirely. Only worth it if the
host process becomes a maintenance nuisance; the host bridge is proven and its
credential-isolation guarantee is identical.
