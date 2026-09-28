"""racinglines mcp  ->  the MCP server (docs/mcp.md): stdio by default, or --http on 127.0.0.1:8100/mcp with a bearer token."""

import argparse


def main(argv=None):
    ap = argparse.ArgumentParser(prog="racinglines mcp", description=__doc__)
    ap.add_argument("--db", help="database URL (default $DATABASE_URL, else the local one)")
    ap.add_argument("--http", action="store_true", help="serve streamable HTTP (needs RACINGLINES_MCP_TOKEN) instead of stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--no-jobs", action="store_true", help="don't run the Lab's job worker here (leave queued jobs to the web app)")
    a = ap.parse_args(argv)
    try:
        import mcp  # noqa: F401
    except ImportError:
        print("The MCP server needs the `mcp` package: pip install -r requirements.txt")
        return 2
    if a.db:
        import os
        os.environ["DATABASE_URL"] = a.db
    from racinglines.mcp.server import serve
    serve(http=a.http, host=a.host, port=a.port, jobs_worker=not a.no_jobs)
    return 0


if __name__ == "__main__":
    main()
