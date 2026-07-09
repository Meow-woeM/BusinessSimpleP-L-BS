"""Posting logic and reports.

Every user action becomes a balanced journal entry: entry_lines.amount_cents
is positive for debits and negative for credits, and each transaction's lines
sum to zero. All reports are derived from those lines, so the balance sheet
balances by construction.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import db


class LedgerError(ValueError):
    """User-facing validation error."""


TXN_TYPE_LABELS = {
    "income": "Income received",
    "expense": "Expense paid",
    "owner_contribution": "Owner contribution",
    "owner_draw": "Owner draw",
    "loan_received": "Loan received",
    "loan_repayment": "Loan repayment",
    "asset_purchase": "Asset purchase",
}


def parse_amount(raw):
    """Parse a user-entered dollar amount into positive integer cents."""
    text = (raw or "").strip().replace(",", "").replace("$", "")
    if not text:
        raise LedgerError("Amount is required.")
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise LedgerError(f"'{raw}' is not a valid amount.")
    if value <= 0:
        raise LedgerError("Amount must be greater than zero.")
    cents = (value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if value != cents / 100:
        raise LedgerError("Amount can have at most 2 decimal places.")
    return int(cents)


def parse_date(raw):
    text = (raw or "").strip()
    if not text:
        raise LedgerError("Date is required.")
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise LedgerError(f"'{raw}' is not a valid date (use YYYY-MM-DD).")


def fmt_money(cents):
    """1234567 -> '12,345.67'; negatives as '-12,345.67'."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100:,}.{cents % 100:02d}"


def account_id(conn, code):
    row = conn.execute("SELECT id FROM accounts WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise LedgerError(f"Missing system account {code}. Reinitialize the database.")
    return row["id"]


def get_category(conn, category_id, expected_type):
    try:
        category_id = int(category_id)
    except (TypeError, ValueError):
        raise LedgerError("Choose a category.")
    row = conn.execute(
        "SELECT * FROM accounts WHERE id = ? AND type = ?", (category_id, expected_type)
    ).fetchone()
    if row is None:
        raise LedgerError(f"Choose a valid {expected_type} category.")
    return row


def build_lines(conn, txn_type, form):
    """Translate a simple form into balanced (account_id, amount_cents) lines.

    Returns (lines, category_name) — category_name is used to fill in a
    default description.
    """
    cash = account_id(conn, db.CASH)
    amount = parse_amount(form.get("amount"))
    category_name = None

    if txn_type == "income":
        cat_ref = form.get("income_category_id") or form.get("category_id")
        cat = get_category(conn, cat_ref, "income")
        category_name = cat["name"]
        lines = [(cash, amount), (cat["id"], -amount)]
    elif txn_type == "expense":
        cat_ref = form.get("expense_category_id") or form.get("category_id")
        cat = get_category(conn, cat_ref, "expense")
        category_name = cat["name"]
        lines = [(cat["id"], amount), (cash, -amount)]
    elif txn_type == "owner_contribution":
        lines = [(cash, amount), (account_id(conn, db.OWNER_CONTRIBUTIONS), -amount)]
    elif txn_type == "owner_draw":
        lines = [(account_id(conn, db.OWNER_DRAWS), amount), (cash, -amount)]
    elif txn_type == "loan_received":
        lines = [(cash, amount), (account_id(conn, db.LOANS_PAYABLE), -amount)]
    elif txn_type == "loan_repayment":
        interest_raw = (form.get("interest") or "").strip()
        interest = parse_amount(interest_raw) if interest_raw else 0
        if interest > amount:
            raise LedgerError("Interest portion cannot exceed the total payment.")
        principal = amount - interest
        lines = [(cash, -amount)]
        if principal:
            lines.append((account_id(conn, db.LOANS_PAYABLE), principal))
        if interest:
            lines.append((account_id(conn, db.INTEREST_EXPENSE), interest))
    elif txn_type == "asset_purchase":
        lines = [(account_id(conn, db.FIXED_ASSETS), amount), (cash, -amount)]
    else:
        raise LedgerError(f"Unknown transaction type '{txn_type}'.")

    assert sum(c for _, c in lines) == 0
    return lines, category_name


def insert_lines(conn, txn_id, lines):
    if sum(cents for _, cents in lines) != 0:
        raise LedgerError("Internal error: transaction does not balance.")
    conn.executemany(
        "INSERT INTO entry_lines (transaction_id, account_id, amount_cents) VALUES (?, ?, ?)",
        [(txn_id, acct, cents) for acct, cents in lines],
    )


def post_transaction(conn, txn_type, form):
    """Validate a form and write the transaction + lines. Returns the txn id."""
    txn_date = parse_date(form.get("date"))
    lines, category_name = build_lines(conn, txn_type, form)
    description = (form.get("description") or "").strip()
    if not description:
        description = category_name or TXN_TYPE_LABELS.get(txn_type, txn_type)
    with conn:
        cur = conn.execute(
            "INSERT INTO transactions (txn_date, txn_type, description) VALUES (?, ?, ?)",
            (txn_date, txn_type, description),
        )
        insert_lines(conn, cur.lastrowid, lines)
    return cur.lastrowid


def update_transaction(conn, txn_id, txn_type, form):
    """Re-derive and replace the lines for an existing transaction."""
    txn_date = parse_date(form.get("date"))
    lines, category_name = build_lines(conn, txn_type, form)
    description = (form.get("description") or "").strip()
    if not description:
        description = category_name or TXN_TYPE_LABELS.get(txn_type, txn_type)
    with conn:
        cur = conn.execute(
            "UPDATE transactions SET txn_date = ?, txn_type = ?, description = ? WHERE id = ?",
            (txn_date, txn_type, description, txn_id),
        )
        if cur.rowcount == 0:
            raise LedgerError("Transaction not found.")
        conn.execute("DELETE FROM entry_lines WHERE transaction_id = ?", (txn_id,))
        insert_lines(conn, txn_id, lines)


def delete_transaction(conn, txn_id):
    with conn:
        cur = conn.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))
    return cur.rowcount > 0


def txn_details(conn, txn_id):
    """Reconstruct the simple-form fields from a transaction's lines (for the
    edit form and CSV export)."""
    txn = conn.execute("SELECT * FROM transactions WHERE id = ?", (txn_id,)).fetchone()
    if txn is None:
        return None
    lines = conn.execute(
        """SELECT l.amount_cents, a.id AS account_id, a.code, a.type
           FROM entry_lines l JOIN accounts a ON a.id = l.account_id
           WHERE l.transaction_id = ?""",
        (txn_id,),
    ).fetchall()
    cash_line = next((l for l in lines if l["code"] == db.CASH), None)
    amount = abs(cash_line["amount_cents"]) if cash_line else 0
    category_id = None
    interest = 0
    if txn["txn_type"] in ("income", "expense"):
        cat_line = next((l for l in lines if l["type"] in ("income", "expense")), None)
        if cat_line:
            category_id = cat_line["account_id"]
    elif txn["txn_type"] == "loan_repayment":
        int_line = next((l for l in lines if l["code"] == db.INTEREST_EXPENSE), None)
        if int_line:
            interest = int_line["amount_cents"]
    return {
        "id": txn["id"],
        "date": txn["txn_date"],
        "type": txn["txn_type"],
        "description": txn["description"],
        "amount_cents": amount,
        "category_id": category_id,
        "interest_cents": interest,
    }


def list_transactions(conn, start=None, end=None, txn_type=None):
    """Transactions newest-first with the reconstructed amount/category."""
    where, params = [], []
    if start:
        where.append("t.txn_date >= ?")
        params.append(start)
    if end:
        where.append("t.txn_date <= ?")
        params.append(end)
    if txn_type:
        where.append("t.txn_type = ?")
        params.append(txn_type)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(
        f"""SELECT t.*,
              COALESCE((SELECT ABS(l.amount_cents) FROM entry_lines l
                 JOIN accounts a ON a.id = l.account_id
                WHERE l.transaction_id = t.id AND a.code = ?), 0) AS amount_cents,
              (SELECT a.name FROM entry_lines l
                 JOIN accounts a ON a.id = l.account_id
                WHERE l.transaction_id = t.id AND a.type IN ('income', 'expense')
                  AND t.txn_type IN ('income', 'expense')) AS category_name
            FROM transactions t {clause}
            ORDER BY t.txn_date DESC, t.id DESC""",
        [db.CASH] + params,
    ).fetchall()
    return rows


def pnl(conn, start, end):
    """Profit & loss for txn_date in [start, end]."""
    rows = conn.execute(
        """SELECT a.id, a.name, a.type, a.code, SUM(l.amount_cents) AS total
           FROM entry_lines l
           JOIN accounts a ON a.id = l.account_id
           JOIN transactions t ON t.id = l.transaction_id
           WHERE a.type IN ('income', 'expense') AND t.txn_date >= ? AND t.txn_date <= ?
           GROUP BY a.id ORDER BY a.code""",
        (start, end),
    ).fetchall()
    income = [
        {"name": r["name"], "amount": -r["total"]}
        for r in rows
        if r["type"] == "income" and r["total"] != 0
    ]
    expenses = [
        {"name": r["name"], "amount": r["total"]}
        for r in rows
        if r["type"] == "expense" and r["total"] != 0
    ]
    total_income = sum(i["amount"] for i in income)
    total_expenses = sum(e["amount"] for e in expenses)
    return {
        "income": income,
        "expenses": expenses,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "net_profit": total_income - total_expenses,
    }


def balance_sheet(conn, as_of):
    """Balance sheet as of a date (inclusive)."""
    rows = conn.execute(
        """SELECT a.id, a.code, a.name, a.type, SUM(l.amount_cents) AS total
           FROM entry_lines l
           JOIN accounts a ON a.id = l.account_id
           JOIN transactions t ON t.id = l.transaction_id
           WHERE t.txn_date <= ?
           GROUP BY a.id ORDER BY a.code""",
        (as_of,),
    ).fetchall()

    assets, liabilities, equity = [], [], []
    retained = 0
    for r in rows:
        total = r["total"] or 0
        if r["type"] == "asset":
            # Always show Cash, even at zero.
            if total != 0 or r["code"] == db.CASH:
                assets.append({"name": r["name"], "amount": total})
        elif r["type"] == "liability":
            if total != 0:
                liabilities.append({"name": r["name"], "amount": -total})
        elif r["type"] == "equity":
            if total != 0:
                # Owner Draws carries a debit balance; -total shows it as a
                # negative line inside equity.
                equity.append({"name": r["name"], "amount": -total})
        else:  # income / expense roll into retained earnings
            retained -= total

    # Ensure Cash appears even before any transaction exists.
    if not any(a["name"] == "Cash" for a in assets):
        assets.append({"name": "Cash", "amount": 0})

    equity.append({"name": "Retained Earnings", "amount": retained})
    total_assets = sum(a["amount"] for a in assets)
    total_liabilities = sum(l["amount"] for l in liabilities)
    total_equity = sum(e["amount"] for e in equity)
    return {
        "assets": assets,
        "liabilities": liabilities,
        "equity": equity,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "total_equity": total_equity,
        "balanced": total_assets == total_liabilities + total_equity,
    }


def categories(conn, cat_type):
    return conn.execute(
        "SELECT * FROM accounts WHERE type = ? ORDER BY code", (cat_type,)
    ).fetchall()


def add_category(conn, name, cat_type):
    name = (name or "").strip()
    if not name:
        raise LedgerError("Category name is required.")
    if cat_type not in ("income", "expense"):
        raise LedgerError("Category type must be income or expense.")
    dup = conn.execute(
        "SELECT 1 FROM accounts WHERE type = ? AND LOWER(name) = LOWER(?)",
        (cat_type, name),
    ).fetchone()
    if dup:
        raise LedgerError(f"A {cat_type} category named '{name}' already exists.")
    # Codes 4000-4999 are income, 5000-5999 expenses; pick the next free code.
    lo, hi = ("4000", "4999") if cat_type == "income" else ("5000", "5999")
    row = conn.execute(
        "SELECT MAX(CAST(code AS INTEGER)) FROM accounts WHERE code >= ? AND code <= ?",
        (lo, hi),
    ).fetchone()
    next_code = (row[0] or int(lo) - 1) + 1
    if next_code > int(hi):
        raise LedgerError("No category codes left in this range.")
    with conn:
        conn.execute(
            "INSERT INTO accounts (code, name, type, is_system) VALUES (?, ?, ?, 0)",
            (str(next_code), name, cat_type),
        )


# ---------------------------------------------------------------------------
# Backup / restore


def export_backup(conn):
    accounts = [
        dict(r)
        for r in conn.execute("SELECT code, name, type, is_system FROM accounts ORDER BY code")
    ]
    txns = []
    for t in conn.execute("SELECT * FROM transactions ORDER BY id"):
        lines = conn.execute(
            """SELECT a.code AS account_code, l.amount_cents
               FROM entry_lines l JOIN accounts a ON a.id = l.account_id
               WHERE l.transaction_id = ? ORDER BY l.id""",
            (t["id"],),
        ).fetchall()
        txns.append(
            {
                "date": t["txn_date"],
                "type": t["txn_type"],
                "description": t["description"],
                "lines": [dict(l) for l in lines],
            }
        )
    return {
        "format": "simple-pl-bs-backup",
        "version": 1,
        "exported_on": date.today().isoformat(),
        "accounts": accounts,
        "transactions": txns,
    }


def import_backup(conn, data):
    """Replace ALL data with the contents of a backup. Validates first."""
    if not isinstance(data, dict) or data.get("format") != "simple-pl-bs-backup":
        raise LedgerError("This file is not a backup created by this app.")
    accounts = data.get("accounts")
    txns = data.get("transactions")
    if not isinstance(accounts, list) or not isinstance(txns, list):
        raise LedgerError("Backup file is malformed.")

    valid_types = {"asset", "liability", "equity", "income", "expense"}
    codes = set()
    for a in accounts:
        if not isinstance(a, dict) or not a.get("code") or not a.get("name"):
            raise LedgerError("Backup contains an invalid account.")
        if a.get("type") not in valid_types:
            raise LedgerError(f"Account '{a.get('name')}' has an invalid type.")
        if a["code"] in codes:
            raise LedgerError(f"Backup contains duplicate account code {a['code']}.")
        codes.add(a["code"])
    for required in (db.CASH,):
        if required not in codes:
            raise LedgerError("Backup is missing the Cash account.")

    for i, t in enumerate(txns, 1):
        if not isinstance(t, dict):
            raise LedgerError(f"Transaction #{i} is malformed.")
        parse_date(t.get("date"))
        if t.get("type") not in TXN_TYPE_LABELS:
            raise LedgerError(f"Transaction #{i} has an unknown type.")
        lines = t.get("lines")
        if not isinstance(lines, list) or not lines:
            raise LedgerError(f"Transaction #{i} has no lines.")
        total = 0
        for l in lines:
            if (
                not isinstance(l, dict)
                or l.get("account_code") not in codes
                or not isinstance(l.get("amount_cents"), int)
                or l["amount_cents"] == 0
            ):
                raise LedgerError(f"Transaction #{i} has an invalid line.")
            total += l["amount_cents"]
        if total != 0:
            raise LedgerError(f"Transaction #{i} does not balance.")

    with conn:
        conn.execute("DELETE FROM entry_lines")
        conn.execute("DELETE FROM transactions")
        conn.execute("DELETE FROM accounts")
        for a in accounts:
            conn.execute(
                "INSERT INTO accounts (code, name, type, is_system) VALUES (?, ?, ?, ?)",
                (a["code"], a["name"], a["type"], 1 if a.get("is_system") else 0),
            )
        id_by_code = {
            r["code"]: r["id"] for r in conn.execute("SELECT id, code FROM accounts")
        }
        for t in txns:
            cur = conn.execute(
                "INSERT INTO transactions (txn_date, txn_type, description) VALUES (?, ?, ?)",
                (t["date"], t["type"], str(t.get("description") or "")),
            )
            conn.executemany(
                "INSERT INTO entry_lines (transaction_id, account_id, amount_cents) VALUES (?, ?, ?)",
                [
                    (cur.lastrowid, id_by_code[l["account_code"]], l["amount_cents"])
                    for l in t["lines"]
                ],
            )
    return len(txns)
