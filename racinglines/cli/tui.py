"""
racinglines tui                          the web app's screens in the terminal, on the hosted server (docs/tui.md)
racinglines tui --local [--db URL]       the same on this machine's database: `racinglines mcp` over stdio

Hosted sign-in is `--remote`'s (cli/remote.py): RACINGLINES_MCP_TOKEN, else the browser once, kept in
~/.config/racinglines/mcp-login.json. The sign-in happens here, before the screen opens, so its URL is readable.

    RACINGLINES_MCP_URL     the hosted server (default https://mcp.racinglines.bet/mcp); --mcp-url overrides it
    RACINGLINES_USER        the account preselected on the Paper tab; --user overrides it
"""

import argparse
import os
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="racinglines tui", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local", action="store_true", help="this machine's database through `racinglines mcp` (stdio)")
    ap.add_argument("--db", help="with --local: the database URL (default $DATABASE_URL, else the local one)")
    ap.add_argument("--no-jobs", action="store_true",
                    help="with --local: don't run the Lab's job worker here (leave queued jobs to the web app)")
    ap.add_argument("--mcp-url", dest="mcp_url", help="the hosted server (default RACINGLINES_MCP_URL or racinglines.bet)")
    ap.add_argument("--user", default=os.environ.get("RACINGLINES_USER"), help="account preselected on the Paper tab")
    ap.add_argument("--timeout", type=float, default=90, help="seconds to wait for one tool call (default 90)")
    a = ap.parse_args(list(argv or []))
    try:
        import textual  # noqa: F401
    except ImportError:
        print("The TUI needs the `textual` package: pip install -r requirements.txt")
        return 2

    from racinglines.cli import remote
    from racinglines.tui.app import RacinglinesApp
    from racinglines.tui.backend import ConnectionSettings, McpBackend, local_argv

    if a.local:
        settings = ConnectionSettings(stdio_argv=local_argv(a.db, a.no_jobs), timeout=a.timeout)
    else:
        server = remote.url(a.mcp_url)
        token = remote.token()
        if not token:
            # Sign in (or refresh the stored login) while the terminal is still a terminal: the browser URL and any
            # error print here, not under the full-screen app. Also prints the remote-access warning.
            try:
                remote.Session(server).close()
            except remote.RemoteError as ex:
                print(ex, file=sys.stderr)
                return 2
        else:
            remote.warn()
        settings = ConnectionSettings(url=server, token=token, timeout=a.timeout)
    RacinglinesApp(McpBackend(settings), user=a.user, remote_warning=None if a.local else remote.WARNING).run()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
