"""Backup sync to a Google Sheet via a Google Apps Script webhook.

The sheet's owner pastes a small Apps Script (see apps_script.gs) into their
spreadsheet and deploys it as a web app; the app POSTs the full ledger state
to that URL after every change. Pushing the complete state each time keeps the
sheet correct through edits and deletes, and the payload doubles as a real
backup: the "Backup" tab holds a restorable JSON export.

Pushes run on a short debounce timer in a daemon thread so the UI never waits
on Google. A `sync_dirty` flag in settings survives restarts, so changes made
while offline are pushed the next time the app starts.
"""

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone

import db

# Google Sheets caps cells at 50,000 characters; stay well under it.
CHUNK_SIZE = 40000

DEBOUNCE_SECONDS = 2.0

_lock = threading.Lock()
_timers = {}


def get_config(conn):
    return {
        "url": db.get_setting(conn, "sync_url").strip(),
        "token": db.get_setting(conn, "sync_token").strip(),
        "last_sync_at": db.get_setting(conn, "sync_last_at"),
        "last_error": db.get_setting(conn, "sync_last_error"),
        "dirty": db.get_setting(conn, "sync_dirty") == "1",
    }


def save_config(conn, url, token):
    url = (url or "").strip()
    if url and not url.startswith("https://"):
        from accounting import LedgerError

        raise LedgerError("The Apps Script URL should start with https://")
    db.set_setting(conn, "sync_url", url)
    db.set_setting(conn, "sync_token", (token or "").strip())


def mark_dirty(conn):
    db.set_setting(conn, "sync_dirty", "1")


def build_payload(conn):
    """Full ledger state: readable transaction rows + restorable JSON backup."""
    import accounting

    rows = []
    for t in accounting.list_transactions(conn):
        amount = accounting.fmt_money(t["amount_cents"]).replace(",", "")
        rows.append(
            [
                t["txn_date"],
                accounting.TXN_TYPE_LABELS.get(t["txn_type"], t["txn_type"]),
                t["description"],
                t["category_name"] or "",
                amount,
            ]
        )
    backup_json = json.dumps(accounting.export_backup(conn))
    chunks = [
        backup_json[i : i + CHUNK_SIZE] for i in range(0, len(backup_json), CHUNK_SIZE)
    ]
    return {
        "token": db.get_setting(conn, "sync_token").strip(),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "rows": rows,
        "backup_chunks": chunks,
    }


def push(conn):
    """Send the current state to the configured webhook. Returns (ok, message).

    Never raises: failures are recorded in settings and shown in the UI, and
    the dirty flag stays set so the next change (or restart) retries.
    """
    cfg = get_config(conn)
    if not cfg["url"]:
        return False, "Google Sheet sync is not set up yet."
    payload = json.dumps(build_payload(conn)).encode("utf-8")
    request = urllib.request.Request(
        cfg["url"], data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        # Apps Script answers POSTs with a 302 to a one-time content URL;
        # urllib follows it as a GET, which returns doPost's actual output.
        with urllib.request.urlopen(request, timeout=45) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, ValueError) as err:
        return _record_failure(conn, f"Could not reach Google: {err}")
    try:
        result = json.loads(body)
    except json.JSONDecodeError:
        result = None
    if not isinstance(result, dict) or not result.get("ok"):
        detail = result.get("error") if isinstance(result, dict) else body[:200]
        return _record_failure(conn, f"Google Sheet script reported a problem: {detail}")
    db.set_setting(conn, "sync_last_at", datetime.now().strftime("%Y-%m-%d %H:%M"))
    db.set_setting(conn, "sync_last_error", "")
    db.set_setting(conn, "sync_dirty", "0")
    return True, "Google Sheet updated."


def _record_failure(conn, message):
    db.set_setting(conn, "sync_last_error", message)
    db.set_setting(conn, "sync_dirty", "1")
    return False, message


def schedule_push(db_path, delay=DEBOUNCE_SECONDS):
    """Debounced background push; rapid edits collapse into one upload."""
    conn = db.connect(db_path)
    try:
        configured = bool(db.get_setting(conn, "sync_url").strip())
    finally:
        conn.close()
    if not configured:
        return
    with _lock:
        existing = _timers.get(db_path)
        if existing is not None:
            existing.cancel()
        timer = threading.Timer(delay, _run_push, args=(db_path,))
        timer.daemon = True
        _timers[db_path] = timer
        timer.start()


def _run_push(db_path):
    with _lock:
        _timers.pop(db_path, None)
    conn = db.connect(db_path)
    try:
        push(conn)
    finally:
        conn.close()
