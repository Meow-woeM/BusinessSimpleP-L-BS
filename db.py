"""Database connection, schema, and seed data for the ledger."""

import sqlite3

from flask import g

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('asset', 'liability', 'equity', 'income', 'expense')),
    is_system INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY,
    txn_date TEXT NOT NULL CHECK (txn_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    txn_type TEXT NOT NULL CHECK (txn_type IN (
        'income', 'expense', 'owner_contribution', 'owner_draw',
        'loan_received', 'loan_repayment', 'asset_purchase'
    )),
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS entry_lines (
    id INTEGER PRIMARY KEY,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    amount_cents INTEGER NOT NULL CHECK (amount_cents != 0)
);

CREATE INDEX IF NOT EXISTS idx_lines_txn ON entry_lines(transaction_id);
CREATE INDEX IF NOT EXISTS idx_lines_account ON entry_lines(account_id);
CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(txn_date);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# System accounts are the fixed skeleton the hidden double-entry posts against.
# Income/expense accounts double as user-facing categories.
SEED_ACCOUNTS = [
    ("1000", "Cash", "asset", 1),
    ("1500", "Equipment & Other Assets", "asset", 1),
    ("2000", "Loans Payable", "liability", 1),
    ("3000", "Owner Contributions", "equity", 1),
    ("3100", "Owner Draws", "equity", 1),
    ("4000", "Sales", "income", 0),
    ("4100", "Services", "income", 0),
    ("4900", "Other Income", "income", 0),
    ("5000", "Rent", "expense", 0),
    ("5100", "Utilities", "expense", 0),
    ("5200", "Supplies", "expense", 0),
    ("5210", "Cleaning Chemicals & Degreasers", "expense", 0),
    ("5220", "Water & Wastewater Disposal", "expense", 0),
    ("5230", "Fuel", "expense", 0),
    ("5240", "Vehicle Maintenance & Repairs", "expense", 0),
    ("5250", "Small Tools & Equipment", "expense", 0),
    ("5260", "Uniforms & Safety Gear", "expense", 0),
    ("5270", "Licenses & Permits", "expense", 0),
    ("5280", "Phone & Internet", "expense", 0),
    ("5290", "Merchant & Bank Fees", "expense", 0),
    ("5300", "Payroll", "expense", 0),
    ("5310", "Contract Labor", "expense", 0),
    ("5400", "Insurance", "expense", 0),
    ("5500", "Advertising & Marketing", "expense", 0),
    ("5600", "Software & Subscriptions", "expense", 0),
    ("5800", "Interest Expense", "expense", 1),
    ("5900", "Other Expense", "expense", 0),
]

# Codes the posting logic relies on.
CASH = "1000"
FIXED_ASSETS = "1500"
LOANS_PAYABLE = "2000"
OWNER_CONTRIBUTIONS = "3000"
OWNER_DRAWS = "3100"
INTEREST_EXPENSE = "5800"


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path):
    """Create the schema and seed accounts.

    INSERT OR IGNORE keys on the unique account code, so databases created by
    older versions pick up newly added seed categories without touching
    existing rows. User-added categories can't collide: add_category always
    allocates codes above the highest seeded code in its range.
    """
    conn = connect(db_path)
    try:
        with conn:
            conn.executescript(SCHEMA)
            conn.executemany(
                "INSERT OR IGNORE INTO accounts (code, name, type, is_system) VALUES (?, ?, ?, ?)",
                SEED_ACCOUNTS,
            )
    finally:
        conn.close()


def get_setting(conn, key, default=""):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None else default


def set_setting(conn, key, value):
    with conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )


def get_db():
    """Per-request connection, closed by the app's teardown handler."""
    from flask import current_app

    if "db" not in g:
        g.db = connect(current_app.config["DB_PATH"])
    return g.db


def close_db(exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()
