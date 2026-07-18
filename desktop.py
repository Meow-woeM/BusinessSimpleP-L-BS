"""Desktop launcher: runs the app locally and opens it in a native window.

Uses pywebview for the window when available (the packaged Windows build
ships with it); otherwise falls back to the default web browser. Data lives
in the OS per-user data directory, not next to the executable, so upgrades
never touch the ledger.
"""

import os
import socket
import sys
import threading
import webbrowser

from werkzeug.serving import make_server


def data_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get(
            "XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share")
        )
    path = os.path.join(base, "SimplePL")
    os.makedirs(path, exist_ok=True)
    return path


def main():
    from app import create_app

    db_path = os.environ.get("LEDGER_DB") or os.path.join(data_dir(), "ledger.db")
    app = create_app(db_path=db_path)

    # Bind port 0 so two copies (or another dev server) never collide.
    server = make_server("127.0.0.1", 0, app, threaded=True)
    port = server.server_port
    url = f"http://127.0.0.1:{port}/"
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # A native window needs pywebview plus a system web engine; fall back to
    # the default browser when either is missing (common on bare Linux).
    # GTK exits the whole process when it can't open a display, so don't even
    # try the native window without one.
    has_display = sys.platform in ("win32", "darwin") or bool(
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    )
    windowed = False
    try:
        if not has_display:
            raise RuntimeError("no display")
        import webview

        webview.create_window(
            "Simple P&L", url, width=1150, height=820, min_size=(700, 500)
        )
        webview.start()
        windowed = True
    except Exception:
        pass

    if not windowed:
        print(f"Simple P&L running at {url} (Ctrl+C to quit)", flush=True)
        webbrowser.open(url)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
    server.shutdown()


if __name__ == "__main__":
    main()
