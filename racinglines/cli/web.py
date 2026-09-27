"""racinglines web  ->  the web app on http://127.0.0.1:8000 (WEB_HOST / WEB_PORT to change)."""

import os

import uvicorn


def main(argv=None):
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8000"))
    if host not in ("127.0.0.1", "localhost"):
        print(f"WARNING: listening on {host}. The app can place exchange orders; keep it behind a private network or the tunnel.")
    uvicorn.run("racinglines.web.app:app", host=host, port=port, reload=os.environ.get("WEB_RELOAD") == "1")


if __name__ == "__main__":
    main()
