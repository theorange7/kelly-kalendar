"""CLI entry point: kelly setup | kelly serve."""

from __future__ import annotations

import argparse
import getpass
import sys

from kelly import __version__


def cmd_setup(args: argparse.Namespace) -> None:
    from kelly.credentials import store_credentials

    print("Kelly — CalDAV credential setup")
    print("Credentials will be stored in your macOS Keychain.\n")

    principal_url = input("CalDAV Principal URL: ").strip()
    if not principal_url:
        print("Error: URL cannot be empty.", file=sys.stderr)
        sys.exit(1)

    username = input("Username: ").strip()
    if not username:
        print("Error: Username cannot be empty.", file=sys.stderr)
        sys.exit(1)

    password = getpass.getpass("Password: ")
    if not password:
        print("Error: Password cannot be empty.", file=sys.stderr)
        sys.exit(1)

    store_credentials(principal_url, username, password)
    print("\nCredentials stored in macOS Keychain.")
    print("Run 'kelly serve' to start the MCP server.")


def cmd_serve(args: argparse.Namespace) -> None:
    from kelly.server import run

    run()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kelly",
        description="Your calendar in Claude's context — a local MCP server for CalDAV.",
    )
    parser.add_argument("--version", action="version", version=f"kelly {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("setup", help="Store CalDAV credentials in macOS Keychain")
    subparsers.add_parser("serve", help="Start the MCP server (stdio transport)")

    parsed = parser.parse_args()

    if parsed.command == "setup":
        cmd_setup(parsed)
    elif parsed.command == "serve":
        cmd_serve(parsed)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
