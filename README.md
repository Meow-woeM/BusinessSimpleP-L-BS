# Simple P&L — income & expense tracker

A small, single-user bookkeeping app for a small business. You enter income,
expenses, owner contributions/draws, loans, and asset purchases through simple
forms; the app maintains a proper double-entry ledger behind the scenes, so the
**Profit & Loss** report and **Balance Sheet** are always accurate and always
balance — on a **cash basis** (income counts when received, expenses when paid).

## Features

- **Transactions** — add, edit, delete, and filter seven kinds of entries:
  income received, expense paid, owner contribution, owner draw, loan received,
  loan repayment (with optional interest split), and asset purchase.
- **Profit & Loss** — income and expenses by category for any period, with
  one-click presets (this month, last month, this quarter, this year, last
  year, all time) or a custom date range.
- **Balance Sheet** — assets, liabilities, and equity (contributions, draws,
  retained earnings) as of any date, with a built-in balance check.
- **Categories** — sensible defaults included; add your own income or expense
  categories in Settings.
- **Backup & restore** — download all data as JSON and restore it later;
  export transactions and both reports as CSV.

All amounts are stored as integer cents (no floating-point drift), and every
transaction is written atomically as a balanced journal entry.

## Getting started

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000 in your browser. Data is stored in `ledger.db`
(SQLite) next to the app; set the `LEDGER_DB` environment variable to use a
different path.

## Running tests

```bash
pytest
```

## How the bookkeeping works

Each form submission is posted as a balanced journal entry against a small
fixed chart of accounts:

| You enter…          | Debit                    | Credit              |
| ------------------- | ------------------------ | ------------------- |
| Income received     | Cash                     | Income category     |
| Expense paid        | Expense category         | Cash                |
| Owner contribution  | Cash                     | Owner Contributions |
| Owner draw          | Owner Draws              | Cash                |
| Loan received       | Cash                     | Loans Payable       |
| Loan repayment      | Loans Payable + Interest | Cash                |
| Asset purchase      | Equipment & Other Assets | Cash                |

Because every entry balances, the balance sheet identity
(Assets = Liabilities + Equity) holds by construction, with net profit to date
appearing as Retained Earnings.
