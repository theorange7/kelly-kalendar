# kelly

> Your calendar in Claude's context — a local MCP server for CalDAV.
>
> **Status:** working prototype

## What it does

Kelly gives Claude read access to your CalDAV calendar so it can help you plan your day, check for conflicts, summarize your week, or answer questions about your schedule — without you copy-pasting events.

- Runs **locally** on your machine — credentials never leave your device
- Stores credentials securely in **macOS Keychain**
- **Read-only** — Kelly can't create, modify, or delete events

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Your machine                                       │
│                                                     │
│  ┌──────────────┐   stdio   ┌──────────────────┐   │
│  │ Claude       │◄─────────►│ kelly            │   │
│  │ Desktop/Code │           │ (MCP server)     │   │
│  └──────────────┘           └────────┬─────────┘   │
│                                      │              │
│                              macOS Keychain         │
│                              (credentials)          │
└──────────────────────────────┼──────────────────────┘
                               │ HTTPS (Digest auth)
                               ▼
                     ┌───────────────────┐
                     │ CalDAV server     │
                     │ (Pixel/SabreDAV)  │
                     └───────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (Python package manager)

### Install

```bash
git clone <this-repo>
cd kelly
uv sync
```

### Store credentials

```bash
kelly setup
```

You'll be prompted for your CalDAV principal URL, username, and password. These are stored in macOS Keychain — not in any file.

### Add to Claude Desktop

Add this to your Claude Desktop MCP config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "kelly": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/kelly", "kelly", "serve"]
    }
  }
}
```

### Add to Claude Code

```bash
claude mcp add kelly -- uv run --directory /path/to/kelly kelly serve
```

### Verify

Ask Claude: *"Check my calendar connection"* — it should call the `check_connection` tool and report success.

## Available Tools

| Tool | Description |
|------|-------------|
| `check_connection` | Verify CalDAV credentials and server connectivity |
| `list_calendars` | List available calendars under your principal |
| `list_upcoming_events` | Fetch events for the next N days, optionally filtered by calendar name |

## Security Model

| Aspect | Detail |
|--------|--------|
| Credential storage | macOS Keychain (primary), env vars (fallback for CI/Docker) |
| Transport | stdio only — no network listener, no exposed ports |
| Scope | Read-only — no calendar mutations possible |
| Network | Outbound HTTPS to your CalDAV server only |
| Dependencies | Minimal: requests, icalendar, fastmcp, keyring |

### Environment variable fallback

If you can't use Keychain (CI, Docker, Linux), set these instead:

```bash
export CALDAV_PRINCIPAL_URL="https://caldav.example.com/principals/you/"
export CALDAV_USER="your-username"
export CALDAV_PASS="your-password"
```

## Development

### Run tests

```bash
uv run pytest
```

### Project structure

```
kelly/
├── __init__.py        # Package version
├── cli.py             # CLI: kelly setup | kelly serve
├── server.py          # FastMCP server + tool definitions
├── caldav.py          # CalDAV protocol (PROPFIND, REPORT, iCal parsing)
└── credentials.py     # Keychain/env credential loading
tests/
├── test_caldav.py     # CalDAV logic tests (mocked HTTP)
├── test_server.py     # MCP tool tests
└── test_credentials.py # Credential fallback tests
```
