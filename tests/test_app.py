"""Route-level tests through the Flask test client."""

import io
import json

import pytest


def add_txn(client, **fields):
    data = {"date": "2026-06-15", "description": ""}
    data.update({k: str(v) for k, v in fields.items()})
    return client.post("/transactions", data=data, follow_redirects=True)


def get_category_id(client, name):
    # Categories are stable seeds; fetch via the backup export.
    backup = json.loads(client.get("/export/backup.json").data)
    for acct in backup["accounts"]:
        if acct["name"] == name:
            return acct["code"]
    raise AssertionError(f"category {name} not found")


def test_index_redirects_to_transactions(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/transactions" in resp.headers["Location"]


def test_add_income_shows_in_history_and_pnl(client, conn):
    cat = conn.execute("SELECT id FROM accounts WHERE name = 'Sales'").fetchone()["id"]
    resp = add_txn(client, type="income", amount="1250.50", category_id=cat)
    assert resp.status_code == 200
    assert b"Transaction added." in resp.data
    assert b"1,250.50" in resp.data

    pnl = client.get("/pnl?start=2026-06-01&end=2026-06-30")
    assert b"1,250.50" in pnl.data
    assert b"Sales" in pnl.data


def test_add_expense_and_balance_sheet(client, conn):
    cat = conn.execute("SELECT id FROM accounts WHERE name = 'Rent'").fetchone()["id"]
    add_txn(client, type="owner_contribution", amount="1000")
    add_txn(client, type="expense", amount="300", category_id=cat)
    bs = client.get("/balance-sheet?as_of=2026-12-31")
    assert b"700.00" in bs.data  # cash 1000 - 300
    assert "✓ Balanced".encode() in bs.data


def test_invalid_amount_flashes_error(client):
    resp = add_txn(client, type="owner_contribution", amount="not-money")
    assert b"not a valid amount" in resp.data


@pytest.mark.parametrize("bad", ["nan", "inf", "1e30", "100000000000000000000"])
def test_pathological_amounts_flash_instead_of_500(client, bad):
    resp = add_txn(client, type="owner_contribution", amount=bad)
    assert resp.status_code == 200  # followed redirect back to the form
    assert b"not a valid amount" in resp.data or b"too large" in resp.data


def test_invalid_date_flashes_error(client):
    resp = add_txn(client, type="owner_contribution", amount="10", date="2026-99-99")
    assert b"not a valid date" in resp.data


def test_missing_category_flashes_error(client):
    resp = add_txn(client, type="income", amount="10")
    assert b"Choose a" in resp.data


def test_edit_transaction_flow(client, conn):
    cat = conn.execute("SELECT id FROM accounts WHERE name = 'Sales'").fetchone()["id"]
    add_txn(client, type="income", amount="100", category_id=cat, description="first")
    txn_id = conn.execute("SELECT id FROM transactions").fetchone()["id"]

    page = client.get(f"/transactions/{txn_id}/edit")
    assert page.status_code == 200
    assert b"100.00" in page.data

    resp = client.post(
        f"/transactions/{txn_id}/edit",
        data={
            "type": "income",
            "date": "2026-06-16",
            "amount": "175",
            "category_id": str(cat),
            "description": "updated",
        },
        follow_redirects=True,
    )
    assert b"Transaction updated." in resp.data
    assert b"175.00" in resp.data
    assert b"updated" in resp.data


def test_edit_missing_transaction_redirects(client):
    resp = client.get("/transactions/9999/edit", follow_redirects=True)
    assert b"Transaction not found." in resp.data


def test_delete_transaction(client, conn):
    add_txn(client, type="owner_contribution", amount="50")
    txn_id = conn.execute("SELECT id FROM transactions").fetchone()["id"]
    resp = client.post(f"/transactions/{txn_id}/delete", follow_redirects=True)
    assert b"Transaction deleted." in resp.data
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_transactions_filters(client, conn):
    cat = conn.execute("SELECT id FROM accounts WHERE name = 'Sales'").fetchone()["id"]
    add_txn(client, type="income", amount="111", category_id=cat, date="2026-01-15")
    add_txn(client, type="owner_draw", amount="222", date="2026-02-15")

    only_income = client.get("/transactions?type=income")
    assert b"111.00" in only_income.data
    assert b"222.00" not in only_income.data

    feb = client.get("/transactions?start=2026-02-01&end=2026-02-28")
    assert b"222.00" in feb.data
    assert b"111.00" not in feb.data


def test_pnl_presets(client):
    for preset in ("this_month", "last_month", "this_quarter", "this_year", "last_year", "all_time"):
        resp = client.get(f"/pnl?preset={preset}")
        assert resp.status_code == 200


def test_pnl_swapped_dates_are_normalized(client):
    resp = client.get("/pnl?start=2026-06-30&end=2026-06-01")
    assert resp.status_code == 200
    assert b"2026-06-01 to 2026-06-30" in resp.data


def test_add_category_via_form(client):
    resp = client.post(
        "/categories", data={"name": "Consulting", "type": "income"}, follow_redirects=True
    )
    assert b"Category added." in resp.data
    assert b"Consulting" in resp.data


def test_transactions_csv_export(client, conn):
    cat = conn.execute("SELECT id FROM accounts WHERE name = 'Rent'").fetchone()["id"]
    add_txn(client, type="expense", amount="1234.56", category_id=cat, description="June rent")
    resp = client.get("/export/transactions.csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    body = resp.data.decode()
    assert "June rent" in body
    assert "1234.56" in body
    assert "Rent" in body


def test_pnl_and_balance_sheet_csv_export(client, conn):
    cat = conn.execute("SELECT id FROM accounts WHERE name = 'Sales'").fetchone()["id"]
    add_txn(client, type="income", amount="500", category_id=cat)
    pnl = client.get("/export/pnl.csv?start=2026-06-01&end=2026-06-30")
    assert pnl.status_code == 200
    assert "Net Profit,500.00" in pnl.data.decode()
    bs = client.get("/export/balance-sheet.csv?as_of=2026-12-31")
    assert bs.status_code == 200
    assert "Retained Earnings,500.00" in bs.data.decode()


def test_backup_export_import_roundtrip_via_routes(client, conn):
    cat = conn.execute("SELECT id FROM accounts WHERE name = 'Sales'").fetchone()["id"]
    add_txn(client, type="income", amount="999.99", category_id=cat)
    backup = client.get("/export/backup.json")
    assert backup.status_code == 200

    resp = client.post(
        "/import",
        data={
            "confirm": "yes",
            "backup": (io.BytesIO(backup.data), "backup.json"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"Backup restored" in resp.data
    txns = client.get("/transactions")
    assert b"999.99" in txns.data


def test_import_requires_confirmation(client):
    resp = client.post(
        "/import",
        data={"backup": (io.BytesIO(b"{}"), "backup.json")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"confirmation box" in resp.data


def test_import_rejects_invalid_json(client):
    resp = client.post(
        "/import",
        data={"confirm": "yes", "backup": (io.BytesIO(b"not json"), "backup.json")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"not valid JSON" in resp.data


def test_import_rejects_foreign_json(client, conn):
    add_txn(client, type="owner_contribution", amount="10")
    resp = client.post(
        "/import",
        data={
            "confirm": "yes",
            "backup": (io.BytesIO(b'{"hello": "world"}'), "backup.json"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"not a backup created by this app" in resp.data
    # Existing data untouched.
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
