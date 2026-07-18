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
- **Categories** — defaults tuned for a service business (fuel, cleaning
  chemicals, water & disposal, vehicle maintenance, and more); add your own
  income or expense categories in Settings.
- **Google Sheet backup** — after every change, the app pushes all
  transactions plus a full restorable backup to a Google Sheet in your Google
  Drive, so a computer failure can't lose your books. See below.
- **Backup & restore** — download all data as JSON and restore it later;
  export transactions and both reports as CSV.
- **Desktop app** — a one-file Windows app (no install needed), or run
  `python desktop.py` on any OS for a desktop window.

All amounts are stored as integer cents (no floating-point drift), and every
transaction is written atomically as a balanced journal entry.

## Getting started (Windows desktop app — easiest)

1. Go to this repo's **Releases** page (or the latest "Build Windows app" run
   under Actions) and download `SimplePL.exe`.
2. Double-click it. Windows SmartScreen may warn because the app is unsigned —
   click **More info → Run anyway**.
3. That's it. Your books are saved to `%APPDATA%\SimplePL\ledger.db`
   automatically.

## Getting started (from source)

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python desktop.py                # desktop window (or: python app.py for browser mode)
```

In browser mode (`python app.py`), open http://127.0.0.1:5000 and data is
stored in `ledger.db` next to the app (override with the `LEDGER_DB`
environment variable). The desktop launcher stores data in your OS user-data
folder instead.

## Google Sheet backup (recommended)

The app can keep a live copy of your books in a Google Sheet in your own
Google Drive — every add/edit/delete re-uploads all transactions and a full
restorable backup a couple of seconds later. Setup takes ~5 minutes and needs
only a normal Google account:

1. In Google Drive, create a new **Google Sheet** (e.g. "Business Ledger").
2. In the sheet: **Extensions → Apps Script**, delete the starter code, paste
   the contents of [`apps_script.gs`](apps_script.gs), and save.
3. **Deploy → New deployment → Web app**, "Execute as: **Me**", "Who has
   access: **Anyone**", then Deploy and Authorize it.
4. Copy the Web app URL into **Settings → Google Sheet backup** in the app,
   Save, then click **Sync now** and watch your transactions appear.

The same instructions (and the script itself) are shown inside the app on the
Settings page. To recover after a computer failure: on the sheet's **Backup**
tab, copy column A (row 2 down) into a file named `backup.json`, then use
**Settings → Restore from backup** in a fresh copy of the app.

If the computer is offline, changes are marked pending and pushed the next
time the app starts (or after the next change once you're back online).

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
