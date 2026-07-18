"""Desktop entry point for the standalone build (and `python launcher.py`).

Starts the web app on localhost, opens the browser, and exits when the user
clicks Quit in the app. If the app is already running, it just opens a new
browser tab pointing at the existing instance instead of starting a second one.
"""

import os
import socket
import sys
import threading
import traceback
import urllib.request
import webbrowser

APP_NAME = "SimplePL"
FIRST_PORT = 5000


def frozen():
    return getattr(sys, "frozen", False)


def data_dir():
    """Where ledger.db and logs live.

    Next to the exe when that's writable (portable install); otherwise the
    per-user app-data folder. For a source checkout, the project directory.
    """
    if not frozen():
        return os.path.dirname(os.path.abspath(__file__))
    exe_dir = os.path.dirname(sys.executable)
    probe = os.path.join(exe_dir, ".write-probe")
    try:
        with open(probe, "w"):
            pass
        os.remove(probe)
        return exe_dir
    except OSError:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(base, APP_NAME)
        os.makedirs(path, exist_ok=True)
        return path


def our_app_on(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as resp:
            return b"simple-pl" in resp.read()
    except OSError:
        return False


def pick_port():
    """Return (port, already_running)."""
    for port in range(FIRST_PORT, FIRST_PORT + 20):
        if our_app_on(port):
            return port, True
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue  # someone else's server; try the next port
        return port, False
    raise RuntimeError("No free port found between 5000 and 5019.")


def main():
    port, already_running = pick_port()
    url = f"http://127.0.0.1:{port}"
    if already_running:
        webbrowser.open(url)
        return

    os.environ.setdefault("LEDGER_DB", os.path.join(data_dir(), "ledger.db"))

    from werkzeug.serving import make_server

    from app import create_app

    shutdown = threading.Event()
    app = create_app()
    app.config["SHUTDOWN_EVENT"] = shutdown
    server = make_server("127.0.0.1", port, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    webbrowser.open(url)
    try:
        shutdown.wait()
    except KeyboardInterrupt:
        pass
    server.shutdown()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # The frozen build has no console, so surface startup failures somewhere.
        log_path = os.path.join(data_dir(), "simplepl-error.log")
        try:
            with open(log_path, "a", encoding="utf-8") as log:
                log.write(traceback.format_exc() + "\n")
        except OSError:
            pass
        if os.name == "nt" and frozen():
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                0,
                f"Simple P&L could not start.\n\nDetails were written to:\n{log_path}",
                "Simple P&L",
                0x10,
            )
        raise
