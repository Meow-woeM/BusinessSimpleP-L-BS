"""Unit tests for money parsing, posting, and report math."""

import pytest

import accounting
import db
from accounting import LedgerError


def income_cat(conn):
    return conn.execute("SELECT id FROM accounts WHERE code = '4000'").fetchone()["id"]


def expense_cat(conn):
    return conn.execute("SELECT id FROM accounts WHERE code = '5000'").fetchone()["id"]


def post(conn, txn_type, **fields):
    form = {"date": fields.pop("date", "2026-06-15"), "description": ""}
    form.update({k: str(v) for k, v in fields.items()})
    return accounting.post_transaction(conn, txn_type, form)


# ---------------------------------------------------------------------------
# parse_amount


@pytest.mark.parametrize(
    "raw,cents",
    [
        ("10", 1000),
        ("10.5", 1050),
        ("10.55", 1055),
        ("$1,234.56", 123456),
        (" 0.01 ", 1),
    ],
)
def test_parse_amount_valid(raw, cents):
    assert accounting.parse_amount(raw) == cents


@pytest.mark.parametrize("raw", ["", "  ", "abc", "10.555", "0", "-5", "1e3.2", None])
def test_parse_amount_invalid(raw):
    with pytest.raises(LedgerError):
        accounting.parse_amount(raw)


def test_parse_date_rejects_garbage():
    with pytest.raises(LedgerError):
        accounting.parse_date("2026-13-40")
    with pytest.raises(LedgerError):
        accounting.parse_date("June 1")
    assert accounting.parse_date("2026-02-28") == "2026-02-28"


def test_fmt_money():
    assert accounting.fmt_money(123456789) == "1,234,567.89"
    assert accounting.fmt_money(-50) == "-0.50"
    assert accounting.fmt_money(0) == "0.00"


# ---------------------------------------------------------------------------
# Posting: every transaction type produces balanced lines


ALL_TYPES = [
    ("income", {"amount": "100", "category_id": "income"}),
    ("expense", {"amount": "40", "category_id": "expense"}),
    ("owner_contribution", {"amount": "500"}),
    ("owner_draw", {"amount": "200"}),
    ("loan_received", {"amount": "1000"}),
    ("loan_repayment", {"amount": "110", "interest": "10"}),
    ("asset_purchase", {"amount": "300"}),
]


@pytest.mark.parametrize("txn_type,fields", ALL_TYPES)
def test_every_type_balances(conn, txn_type, fields):
    fields = dict(fields)
    if fields.get("category_id") == "income":
        fields["category_id"] = income_cat(conn)
    elif fields.get("category_id") == "expense":
        fields["category_id"] = expense_cat(conn)
    txn_id = post(conn, txn_type, **fields)
    total = conn.execute(
        "SELECT SUM(amount_cents) FROM entry_lines WHERE transaction_id = ?", (txn_id,)
    ).fetchone()[0]
    assert total == 0


def test_income_hits_cash_and_category(conn):
    txn_id = post(conn, "income", amount="250.75", category_id=income_cat(conn))
    lines = {
        row["code"]: row["amount_cents"]
        for row in conn.execute(
            """SELECT a.code, l.amount_cents FROM entry_lines l
               JOIN accounts a ON a.id = l.account_id WHERE l.transaction_id = ?""",
            (txn_id,),
        )
    }
    assert lines == {db.CASH: 25075, "4000": -25075}


def test_loan_repayment_splits_principal_and_interest(conn):
    post(conn, "loan_received", amount="1000")
    txn_id = post(conn, "loan_repayment", amount="110", interest="10")
    lines = {
        row["code"]: row["amount_cents"]
        for row in conn.execute(
            """SELECT a.code, l.amount_cents FROM entry_lines l
               JOIN accounts a ON a.id = l.account_id WHERE l.transaction_id = ?""",
            (txn_id,),
        )
    }
    assert lines == {db.CASH: -11000, db.LOANS_PAYABLE: 10000, db.INTEREST_EXPENSE: 1000}


def test_loan_repayment_interest_cannot_exceed_total(conn):
    with pytest.raises(LedgerError):
        post(conn, "loan_repayment", amount="100", interest="150")


def test_income_rejects_expense_category(conn):
    with pytest.raises(LedgerError):
        post(conn, "income", amount="100", category_id=expense_cat(conn))


def test_unknown_type_rejected(conn):
    with pytest.raises(LedgerError):
        post(conn, "nonsense", amount="100")


def test_failed_post_writes_nothing(conn):
    with pytest.raises(LedgerError):
        post(conn, "income", amount="100", category_id="99999")
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM entry_lines").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Update / delete


def test_update_replaces_lines(conn):
    txn_id = post(conn, "income", amount="100", category_id=income_cat(conn))
    accounting.update_transaction(
        conn,
        txn_id,
        "expense",
        {"date": "2026-06-20", "amount": "80", "category_id": str(expense_cat(conn)), "description": "now an expense"},
    )
    details = accounting.txn_details(conn, txn_id)
    assert details["type"] == "expense"
    assert details["amount_cents"] == 8000
    assert details["date"] == "2026-06-20"
    line_count = conn.execute("SELECT COUNT(*) FROM entry_lines").fetchone()[0]
    assert line_count == 2


def test_failed_update_leaves_transaction_intact(conn):
    txn_id = post(conn, "income", amount="100", category_id=income_cat(conn))
    with pytest.raises(LedgerError):
        accounting.update_transaction(
            conn, txn_id, "income", {"date": "2026-06-20", "amount": "bogus", "category_id": str(income_cat(conn))}
        )
    details = accounting.txn_details(conn, txn_id)
    assert details["amount_cents"] == 10000
    assert details["date"] == "2026-06-15"


def test_delete_removes_lines(conn):
    txn_id = post(conn, "income", amount="100", category_id=income_cat(conn))
    assert accounting.delete_transaction(conn, txn_id)
    assert conn.execute("SELECT COUNT(*) FROM entry_lines").fetchone()[0] == 0
    assert not accounting.delete_transaction(conn, txn_id)


# ---------------------------------------------------------------------------
# Reports


def seed_books(conn):
    post(conn, "owner_contribution", amount="5000", date="2026-01-01")
    post(conn, "loan_received", amount="2000", date="2026-01-05")
    post(conn, "asset_purchase", amount="1500", date="2026-01-10")
    post(conn, "income", amount="3000", category_id=income_cat(conn), date="2026-02-01")
    post(conn, "expense", amount="800", category_id=expense_cat(conn), date="2026-02-10")
    post(conn, "loan_repayment", amount="550", interest="50", date="2026-02-15")
    post(conn, "owner_draw", amount="400", date="2026-03-01")


def test_pnl_math(conn):
    seed_books(conn)
    report = accounting.pnl(conn, "2026-01-01", "2026-12-31")
    assert report["total_income"] == 300000
    # 800 rent + 50 loan interest
    assert report["total_expenses"] == 85000
    assert report["net_profit"] == 215000
    names = {row["name"] for row in report["expenses"]}
    assert names == {"Rent", "Interest Expense"}


def test_pnl_respects_period(conn):
    seed_books(conn)
    jan = accounting.pnl(conn, "2026-01-01", "2026-01-31")
    assert jan["total_income"] == 0
    assert jan["total_expenses"] == 0
    feb = accounting.pnl(conn, "2026-02-01", "2026-02-28")
    assert feb["total_income"] == 300000
    assert feb["total_expenses"] == 85000


def test_balance_sheet_math(conn):
    seed_books(conn)
    report = accounting.balance_sheet(conn, "2026-12-31")
    by_name = {row["name"]: row["amount"] for row in report["assets"]}
    # Cash: 5000 + 2000 - 1500 + 3000 - 800 - 550 - 400 = 6750
    assert by_name["Cash"] == 675000
    assert by_name["Equipment & Other Assets"] == 150000
    assert report["total_assets"] == 825000
    # Loans: 2000 - 500 principal = 1500
    assert report["total_liabilities"] == 150000
    eq = {row["name"]: row["amount"] for row in report["equity"]}
    assert eq["Owner Contributions"] == 500000
    assert eq["Owner Draws"] == -40000
    assert eq["Retained Earnings"] == 215000
    assert report["total_equity"] == 675000
    assert report["balanced"]


def test_balance_sheet_as_of_excludes_later_transactions(conn):
    seed_books(conn)
    report = accounting.balance_sheet(conn, "2026-01-31")
    # Only contribution, loan, asset purchase so far.
    by_name = {row["name"]: row["amount"] for row in report["assets"]}
    assert by_name["Cash"] == 550000
    assert report["total_liabilities"] == 200000
    eq = {row["name"]: row["amount"] for row in report["equity"]}
    assert eq["Retained Earnings"] == 0
    assert report["balanced"]


def test_balance_sheet_empty_books_shows_cash_zero(conn):
    report = accounting.balance_sheet(conn, "2026-01-01")
    assert report["total_assets"] == 0
    assert any(a["name"] == "Cash" for a in report["assets"])
    assert report["balanced"]


def test_balance_sheet_always_balances_regardless_of_data(conn):
    seed_books(conn)
    for as_of in ("2026-01-01", "2026-02-14", "2026-02-15", "2026-06-30"):
        assert accounting.balance_sheet(conn, as_of)["balanced"]


# ---------------------------------------------------------------------------
# Categories


def test_add_category_and_duplicate_rejected(conn):
    accounting.add_category(conn, "Consulting", "income")
    row = conn.execute(
        "SELECT * FROM accounts WHERE name = 'Consulting'"
    ).fetchone()
    assert row["type"] == "income"
    assert 4000 <= int(row["code"]) <= 4999
    with pytest.raises(LedgerError):
        accounting.add_category(conn, "consulting", "income")
    with pytest.raises(LedgerError):
        accounting.add_category(conn, "", "income")
    with pytest.raises(LedgerError):
        accounting.add_category(conn, "Stuff", "asset")


# ---------------------------------------------------------------------------
# Backup / restore


def test_backup_roundtrip_preserves_reports(conn):
    seed_books(conn)
    accounting.add_category(conn, "Consulting", "income")
    before_pnl = accounting.pnl(conn, "2026-01-01", "2026-12-31")
    before_bs = accounting.balance_sheet(conn, "2026-12-31")

    backup = accounting.export_backup(conn)
    # Wipe by importing into the same DB (import replaces everything).
    count = accounting.import_backup(conn, backup)
    assert count == 7

    after_pnl = accounting.pnl(conn, "2026-01-01", "2026-12-31")
    after_bs = accounting.balance_sheet(conn, "2026-12-31")
    assert after_pnl == before_pnl
    assert after_bs == before_bs


def test_import_rejects_unbalanced_transaction(conn):
    backup = accounting.export_backup(conn)
    backup["transactions"].append(
        {
            "date": "2026-01-01",
            "type": "income",
            "description": "bad",
            "lines": [{"account_code": db.CASH, "amount_cents": 100}],
        }
    )
    with pytest.raises(LedgerError, match="does not balance"):
        accounting.import_backup(conn, backup)
    # Nothing was destroyed by the failed import.
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] > 0


def test_import_rejects_wrong_format(conn):
    with pytest.raises(LedgerError):
        accounting.import_backup(conn, {"format": "something-else"})
    with pytest.raises(LedgerError):
        accounting.import_backup(conn, [1, 2, 3])


def test_import_rejects_unknown_account_code(conn):
    backup = accounting.export_backup(conn)
    backup["transactions"].append(
        {
            "date": "2026-01-01",
            "type": "income",
            "description": "bad",
            "lines": [
                {"account_code": "9999", "amount_cents": 100},
                {"account_code": db.CASH, "amount_cents": -100},
            ],
        }
    )
    with pytest.raises(LedgerError):
        accounting.import_backup(conn, backup)
