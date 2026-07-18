"""Tests for the Google Sheet backup sync."""

import io
import json

import pytest

import db as dbmod
import sync


def post_income(client, amount="100", date="2026-07-01"):
    return client.post(
        "/transactions",
        data={
            "type": "income",
            "date": date,
            "amount": amount,
            "income_category_id": category_id(client, "Sales"),
        },
        follow_redirects=True,
    )


_category_cache = {}


def category_id(client, name):
    # Resolve a category id via the accounts table of the test app's DB.
    app = client.application
    key = (app.config["DB_PATH"], name)
    if key not in _category_cache:
        conn = dbmod.connect(app.config["DB_PATH"])
        row = conn.execute("SELECT id FROM accounts WHERE name = ?", (name,)).fetchone()
        conn.close()
        _category_cache[key] = row["id"]
    return _category_cache[key]


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_new_business_categories_seeded(conn):
    names = {r["name"] for r in conn.execute("SELECT name FROM accounts")}
    for expected in (
        "Cleaning Chemicals & Degreasers",
        "Water & Wastewater Disposal",
        "Fuel",
        "Vehicle Maintenance & Repairs",
        "Small Tools & Equipment",
        "Uniforms & Safety Gear",
        "Licenses & Permits",
        "Phone & Internet",
        "Merchant & Bank Fees",
        "Contract Labor",
    ):
        assert expected in names


def test_old_database_gains_new_seed_categories(tmp_path):
    path = str(tmp_path / "old.db")
    dbmod.init_db(path)
    conn = dbmod.connect(path)
    with conn:
        conn.execute("DELETE FROM accounts WHERE code = '5230'")  # simulate old DB
    conn.close()
    dbmod.init_db(path)
    conn = dbmod.connect(path)
    row = conn.execute("SELECT name FROM accounts WHERE code = '5230'").fetchone()
    conn.close()
    assert row is not None and row["name"] == "Fuel"


def test_build_payload_rows_and_restorable_backup(client, conn):
    post_income(client, amount="1234.56")
    payload = sync.build_payload(conn)
    assert payload["rows"] == [
        ["2026-07-01", "Income received", "Sales", "Sales", "1234.56"]
    ]
    backup = json.loads("".join(payload["backup_chunks"]))
    assert backup["format"] == "simple-pl-bs-backup"
    assert len(backup["transactions"]) == 1


def test_push_not_configured(conn):
    ok, message = sync.push(conn)
    assert not ok
    assert "not set up" in message


def test_push_success_records_status(client, conn, monkeypatch):
    post_income(client)
    dbmod.set_setting(conn, "sync_url", "https://script.google.com/macros/s/x/exec")
    sent = {}

    def fake_urlopen(request, timeout=None):
        sent["url"] = request.full_url
        sent["payload"] = json.loads(request.data.decode())
        return FakeResponse(b'{"ok": true, "rows": 1}')

    monkeypatch.setattr(sync.urllib.request, "urlopen", fake_urlopen)
    ok, message = sync.push(conn)
    assert ok, message
    assert sent["url"].startswith("https://script.google.com")
    assert len(sent["payload"]["rows"]) == 1
    cfg = sync.get_config(conn)
    assert cfg["last_sync_at"]
    assert cfg["last_error"] == ""
    assert not cfg["dirty"]


def test_push_network_failure_keeps_dirty(client, conn, monkeypatch):
    post_income(client)
    dbmod.set_setting(conn, "sync_url", "https://script.google.com/macros/s/x/exec")

    def fake_urlopen(request, timeout=None):
        raise sync.urllib.error.URLError("no internet")

    monkeypatch.setattr(sync.urllib.request, "urlopen", fake_urlopen)
    ok, message = sync.push(conn)
    assert not ok
    cfg = sync.get_config(conn)
    assert "Could not reach Google" in cfg["last_error"]
    assert cfg["dirty"]


def test_push_script_error_reported(client, conn, monkeypatch):
    post_income(client)
    dbmod.set_setting(conn, "sync_url", "https://script.google.com/macros/s/x/exec")
    monkeypatch.setattr(
        sync.urllib.request,
        "urlopen",
        lambda request, timeout=None: FakeResponse(
            b'{"ok": false, "error": "wrong sync token"}'
        ),
    )
    ok, message = sync.push(conn)
    assert not ok
    assert "wrong sync token" in message


def test_mutations_mark_ledger_dirty(client, conn):
    assert not sync.get_config(conn)["dirty"]
    post_income(client)
    assert sync.get_config(conn)["dirty"]


def test_save_sync_settings_roundtrip(client, conn):
    resp = client.post(
        "/settings/sync",
        data={"url": "https://script.google.com/macros/s/abc/exec", "token": "s3cret"},
        follow_redirects=True,
    )
    assert b"Sync now" in resp.data
    cfg = sync.get_config(conn)
    assert cfg["url"].endswith("/exec")
    assert cfg["token"] == "s3cret"
    # Clearing the URL turns sync off.
    resp = client.post("/settings/sync", data={"url": "", "token": ""}, follow_redirects=True)
    assert b"turned off" in resp.data
    assert sync.get_config(conn)["url"] == ""


def test_save_sync_settings_rejects_http(client):
    resp = client.post(
        "/settings/sync", data={"url": "http://not-secure.example/exec"}, follow_redirects=True
    )
    assert b"should start with https" in resp.data


def test_sync_now_route_reports_failure(client, monkeypatch):
    client.post(
        "/settings/sync",
        data={"url": "https://script.google.com/macros/s/abc/exec"},
        follow_redirects=True,
    )

    def fake_urlopen(request, timeout=None):
        raise sync.urllib.error.URLError("offline")

    monkeypatch.setattr(sync.urllib.request, "urlopen", fake_urlopen)
    resp = client.post("/sync-now", follow_redirects=True)
    assert b"Could not reach Google" in resp.data


def test_settings_page_shows_sync_section(client):
    resp = client.get("/settings")
    assert b"Google Sheet backup" in resp.data
    assert b"Apps Script web app URL" in resp.data
    assert b"function doPost" in resp.data  # script is embedded for copy/paste
