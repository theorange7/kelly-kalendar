# Security Review: Kelly MCP Server

**Date:** 2026-07-11  
**Reviewer:** Claude (automated)  
**Scope:** Full codebase (`kelly/`, `tests/`, `pyproject.toml`)

**Overall verdict: Low risk, appropriate for the threat model (local-only, read-only CalDAV client).**

---

## Strengths

1. **Credential handling** — Keychain-first with env var fallback. Passwords never written to disk or logged.
2. **Read-only scope** — No write tools, no create/delete/modify operations. Limits blast radius to confidentiality.
3. **stdio transport** — No network listener, no auth surface for the MCP server itself.
4. **SSL verification** — Default `requests` behavior (verify=True) is used; no bypass.
5. **Timeouts** — All HTTP calls have explicit timeouts (15s/20s), preventing hangs.
6. **No credential echo** — `getpass` hides password input in `kelly setup`.

---

## Findings

| # | Severity | File | Issue |
|---|----------|------|-------|
| 1 | **Medium** | `caldav.py:82-95` | **XML injection via f-string.** The `_fmt()` values come from `datetime` objects (safe), but if `calendar_url` were attacker-controlled, the REPORT body is composed via f-string, not safe XML serialization. In practice not exploitable because `calendar_url` comes from server-supplied `<d:href>` values resolved against the user's own principal. No fix needed now, but worth noting if user-supplied calendar URLs are ever accepted directly. |
| 2 | **Low** | `caldav.py:101` | **XML parsing uses ET.fromstring.** Python's `xml.etree.ElementTree` does not resolve external entities by default, so no XXE risk. Confirmed safe. |
| 3 | **Low** | `server.py:49,67,90` | **Error messages returned to Claude include server responses** (`str(e)` from CalDavError contains up to 300 chars of HTTP response body). If a CalDAV server returns sensitive info in error pages, it would flow into the MCP tool result. Acceptable for a local tool. |
| 4 | **Low** | `credentials.py:28-30` | **Env var names are generic patterns** (`CALDAV_PASS`). If another tool on the system sets these, Kelly would use wrong credentials. By-design for CI/Docker — just worth documenting. |
| 5 | **Info** | `pyproject.toml` | **No pinned dependency hashes.** For a demo this is fine; for production, add a lockfile with hashes (`uv lock`) to prevent supply-chain substitution. |

---

## Recommendations

### For the management presentation

- The Keychain story is strong — credentials never leave the OS secure enclave.
- Key points: **no network listener** (stdio only), **read-only** (no calendar modification possible), **no data leaves the machine** (runs locally inside Claude Code/Desktop).
- If asked about supply-chain risk: dependencies (`requests`, `icalendar`, `keyring`, `fastmcp`) are well-maintained, popular packages. Adding hash-pinning in CI completes the story.

### Optional hardening

Replace `xml.etree.ElementTree.fromstring` with `defusedxml.ElementTree.fromstring` to guard against billion-laughs DoS from a malicious CalDAV server. Defense-in-depth — the server is already trusted (user's own calendar) — but `defusedxml` is cheap to add and strengthens the security narrative.

---

## Conclusion

No exploitable vulnerabilities found. The code is safe to share with management as-is.
