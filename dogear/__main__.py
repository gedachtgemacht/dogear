"""Command line entry point: `python -m dogear` or the `dogear` script.

    dogear                 serve the UI on http://127.0.0.1:7870
    dogear --port 8000     another port
    dogear --root ~/code   default project directory for new sessions
    dogear --open          open the UI in the default browser once it is up
"""
import argparse
import os
import threading
import webbrowser

import uvicorn


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="dogear", description="Local coding agent with a live workspace.")
    p.add_argument("--port", type=int, default=int(os.environ.get("DOGEAR_PORT", 7870)), help="UI port (default 7870)")
    p.add_argument("--root", help="default project directory for new sessions")
    p.add_argument("--open", action="store_true", help="open the UI in your browser once the server is up")
    p.add_argument("--reload", action="store_true", help="restart on code changes (development)")
    a = p.parse_args(argv)
    if a.root:
        os.environ["DOGEAR_ROOT"] = os.path.abspath(os.path.expanduser(a.root))
    url = f"http://127.0.0.1:{a.port}"
    if a.open:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"dogear: {url}")
    # The UI is reachable from this machine only: the server binds to the loopback address and the
    # WebSocket checks the Origin header, so no other web page can drive the agent.
    uvicorn.run("dogear.server:app", host="127.0.0.1", port=a.port, reload=a.reload, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
