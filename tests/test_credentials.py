"""Tests for kelly.credentials — Keychain/env fallback logic."""

from unittest.mock import patch

import pytest

from kelly.credentials import CredentialError, load_credentials, store_credentials

SERVICE_NAME = "kelly"


class TestLoadCredentials:
    def test_loads_from_keychain(self):
        def mock_get(service, key):
            return {
                "principal_url": "https://caldav.example.com/principals/user/",
                "username": "alice",
                "password": "secret",
            }.get(key)

        with patch("kelly.credentials.keyring.get_password", side_effect=mock_get):
            url, user, pw = load_credentials()

        assert url == "https://caldav.example.com/principals/user/"
        assert user == "alice"
        assert pw == "secret"

    def test_falls_back_to_env_vars(self):
        with patch("kelly.credentials.keyring.get_password", return_value=None):
            env = {
                "CALDAV_PRINCIPAL_URL": "https://caldav.example.com/p/",
                "CALDAV_USER": "bob",
                "CALDAV_PASS": "pw123",
            }
            with patch.dict("os.environ", env, clear=False):
                url, user, pw = load_credentials()

        assert url == "https://caldav.example.com/p/"
        assert user == "bob"
        assert pw == "pw123"

    def test_raises_when_nothing_configured(self):
        with patch("kelly.credentials.keyring.get_password", return_value=None):
            env = {}
            with patch.dict("os.environ", env, clear=True):
                with pytest.raises(CredentialError, match="No CalDAV credentials found"):
                    load_credentials()

    def test_keychain_partial_falls_through_to_env(self):
        """If Keychain has only some keys, fall through to env vars."""
        def mock_get(service, key):
            if key == "principal_url":
                return "https://caldav.example.com/"
            return None

        with patch("kelly.credentials.keyring.get_password", side_effect=mock_get):
            env = {
                "CALDAV_PRINCIPAL_URL": "https://env.example.com/",
                "CALDAV_USER": "envuser",
                "CALDAV_PASS": "envpw",
            }
            with patch.dict("os.environ", env, clear=False):
                url, user, pw = load_credentials()

        assert url == "https://env.example.com/"
        assert user == "envuser"


class TestStoreCredentials:
    def test_stores_all_three_values(self):
        with patch("kelly.credentials.keyring.set_password") as mock_set:
            store_credentials("https://example.com/", "user1", "pass1")

        assert mock_set.call_count == 3
        mock_set.assert_any_call(SERVICE_NAME, "principal_url", "https://example.com/")
        mock_set.assert_any_call(SERVICE_NAME, "username", "user1")
        mock_set.assert_any_call(SERVICE_NAME, "password", "pass1")
