# Simple P&L — income & expense tracker

[![Open the Web App](https://img.shields.io/badge/%F0%9F%8C%90_Open_the_Web_App-no_install_needed-1a7f4b?style=for-the-badge)](https://meow-woem.github.io/BusinessSimpleP-L-BS/)
[![Download for Windows](https://img.shields.io/badge/%E2%AC%87%EF%B8%8F_Download_for_Windows-SimplePL.exe-2456c4?style=for-the-badge)](https://github.com/Meow-woeM/BusinessSimpleP-L-BS/releases/latest/download/SimplePL.exe)

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

### Web app (nothing to install)

Click the **Open the Web App** button at the top of this page, or go to
https://meow-woem.github.io/BusinessSimpleP-L-BS/ — it's the same app, running
entirely in your browser. Your books are saved automatically in the browser
itself (nothing is uploaded to any server), and you can install it as an app:
look for the install icon in the address bar (Chrome/Edge) or "Add to Home
Screen" on a phone. It even works offline after the first visit.

Because the data lives in your browser, use **Settings → Download backup** for
safekeeping — the backup file is identical to the desktop app's format, so you
can move your books freely between the web app and `SimplePL.exe`. The browser
version's ledger engine is held to the exact same numbers as the desktop
engine by a parity test (`node webapp/ledger.test.mjs`) that runs before every
deploy.

### Standalone Windows app (no Python needed)

Click the **Download for Windows** button at the top of this page (it always
serves the newest build, from the [latest release](https://github.com/Meow-woeM/BusinessSimpleP-L-BS/releases/latest)).
Put `SimplePL.exe` anywhere (Desktop, a USB stick) and double-click it — your
browser opens with the app. Use the **Quit** button in the top-right to stop
it. Windows SmartScreen may warn on first run because the exe is unsigned:
click **More info → Run anyway**.

Behind the scenes, every push to the main branches rebuilds the exe on a
Windows runner via GitHub Actions (`Build Windows exe` workflow), runs the
full test suite on Windows, smoke-tests the built exe, and updates the
rolling `latest` release that the button points to.

Your data is saved in `ledger.db` next to the exe (or in `%APPDATA%\SimplePL`
if that folder isn't writable). Errors, if any, are logged to
`simplepl-error.log` in the same place.

To build the exe yourself on a Windows machine:

```bat
pip install -r requirements.txt pyinstaller
pyinstaller simplepl.spec
```

The result is `dist\SimplePL.exe`.

### Running from source

Requires Python 3.10+ (on Windows, install from https://www.python.org/downloads/
and check "Add python.exe to PATH" during setup).

**Windows:** double-click `run.bat`. It sets everything up on first run and
opens the app in your browser. Close the console window to stop the app.

**macOS / Linux:**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000 in your browser. Data is stored in `ledger.db`
(SQLite) next to the app; set the `LEDGER_DB` environment variable to use a
different path, and set `FLASK_DEBUG=1` to run with Flask's debugger enabled.

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
