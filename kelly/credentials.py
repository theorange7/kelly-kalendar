"""Credential loading: macOS Keychain first, env vars as fallback."""

from __future__ import annotations

import os

import keyring

SERVICE_NAME = "kelly"


class CredentialError(RuntimeError):
    pass


def load_credentials() -> tuple[str, str, str]:
    """
    Load CalDAV credentials. Tries macOS Keychain first, then env vars.
    Returns (principal_url, username, password).
    """
    principal_url = keyring.get_password(SERVICE_NAME, "principal_url")
    username = keyring.get_password(SERVICE_NAME, "username")
    password = keyring.get_password(SERVICE_NAME, "password")

    if all([principal_url, username, password]):
        return principal_url, username, password

    principal_url = os.environ.get("CALDAV_PRINCIPAL_URL")
    username = os.environ.get("CALDAV_USER")
    password = os.environ.get("CALDAV_PASS")

    if all([principal_url, username, password]):
        return principal_url, username, password

    raise CredentialError(
        "No CalDAV credentials found. Either:\n"
        "  1. Run 'kelly setup' to store them in macOS Keychain, or\n"
        "  2. Set CALDAV_PRINCIPAL_URL, CALDAV_USER, CALDAV_PASS environment variables."
    )


def store_credentials(principal_url: str, username: str, password: str) -> None:
    """Store CalDAV credentials in macOS Keychain."""
    keyring.set_password(SERVICE_NAME, "principal_url", principal_url)
    keyring.set_password(SERVICE_NAME, "username", username)
    keyring.set_password(SERVICE_NAME, "password", password)
