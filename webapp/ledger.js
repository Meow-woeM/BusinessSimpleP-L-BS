/* Ledger engine for the browser version of Simple P&L.
 *
 * Mirrors accounting.py exactly: every user action becomes a balanced journal
 * entry (amount_cents positive = debit, negative = credit; each transaction's
 * lines sum to zero), and all reports derive from those lines, so the balance
 * sheet balances by construction. Amounts are integer cents throughout.
 *
 * Works in the browser (window.Ledger) and in Node (module.exports) so the
 * parity test can run headlessly.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Ledger = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  class LedgerError extends Error {}

  const CODES = {
    CASH: "1000",
    FIXED_ASSETS: "1500",
    LOANS_PAYABLE: "2000",
    OWNER_CONTRIBUTIONS: "3000",
    OWNER_DRAWS: "3100",
    INTEREST_EXPENSE: "5800",
  };

  const TXN_TYPE_LABELS = {
    income: "Income received",
    expense: "Expense paid",
    owner_contribution: "Owner contribution",
    owner_draw: "Owner draw",
    loan_received: "Loan received",
    loan_repayment: "Loan repayment",
    asset_purchase: "Asset purchase",
  };

  const SEED_ACCOUNTS = [
    ["1000", "Cash", "asset", 1],
    ["1500", "Equipment & Other Assets", "asset", 1],
    ["2000", "Loans Payable", "liability", 1],
    ["3000", "Owner Contributions", "equity", 1],
    ["3100", "Owner Draws", "equity", 1],
    ["4000", "Sales", "income", 0],
    ["4100", "Services", "income", 0],
    ["4900", "Other Income", "income", 0],
    ["5000", "Rent", "expense", 0],
    ["5100", "Utilities", "expense", 0],
    ["5200", "Supplies", "expense", 0],
    ["5300", "Payroll", "expense", 0],
    ["5400", "Insurance", "expense", 0],
    ["5500", "Advertising & Marketing", "expense", 0],
    ["5600", "Software & Subscriptions", "expense", 0],
    ["5800", "Interest Expense", "expense", 1],
    ["5900", "Other Expense", "expense", 0],
  ];

  const VALID_ACCOUNT_TYPES = ["asset", "liability", "equity", "income", "expense"];

  function newState() {
    return {
      accounts: SEED_ACCOUNTS.map(([code, name, type, is_system]) => ({
        code, name, type, is_system,
      })),
      transactions: [],
      nextId: 1,
    };
  }

  // ---------------------------------------------------------------- parsing

  function parseAmount(raw, allowZero) {
    const text = String(raw == null ? "" : raw).trim().replace(/[$,]/g, "");
    if (!text) throw new LedgerError("Amount is required.");
    if (!/^(\d+(\.\d*)?|\.\d+)$/.test(text)) {
      throw new LedgerError(`'${raw}' is not a valid amount.`);
    }
    const dot = text.indexOf(".");
    const intPart = dot === -1 ? text : text.slice(0, dot) || "0";
    const fracPart = dot === -1 ? "" : text.slice(dot + 1);
    if (fracPart.length > 2) {
      throw new LedgerError("Amount can have at most 2 decimal places.");
    }
    if (intPart.replace(/^0+(?=\d)/, "").length > 12) {
      throw new LedgerError("Amount is too large."); // cap: 999,999,999,999.99
    }
    const cents =
      parseInt(intPart, 10) * 100 + parseInt((fracPart + "00").slice(0, 2), 10);
    if (cents === 0 && !allowZero) {
      throw new LedgerError("Amount must be greater than zero.");
    }
    return cents;
  }

  function parseDate(raw) {
    const text = String(raw == null ? "" : raw).trim();
    if (!text) throw new LedgerError("Date is required.");
    const m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(text);
    if (!m) throw new LedgerError(`'${raw}' is not a valid date (use YYYY-MM-DD).`);
    const [year, month, day] = [+m[1], +m[2], +m[3]];
    const d = new Date(Date.UTC(year, month - 1, day));
    if (
      d.getUTCFullYear() !== year ||
      d.getUTCMonth() !== month - 1 ||
      d.getUTCDate() !== day
    ) {
      throw new LedgerError(`'${raw}' is not a valid date (use YYYY-MM-DD).`);
    }
    if (year < 1900 || year > 2999) {
      throw new LedgerError(
        `'${raw}' has an unlikely year — use a date between 1900 and 2999.`
      );
    }
    const pad = (n) => String(n).padStart(2, "0");
    return `${year}-${pad(month)}-${pad(day)}`;
  }

  function fmtMoney(cents) {
    const sign = cents < 0 ? "-" : "";
    const abs = Math.abs(cents);
    const dollars = Math.floor(abs / 100).toLocaleString("en-US");
    return `${sign}${dollars}.${String(abs % 100).padStart(2, "0")}`;
  }

  function fmtUsd(cents) {
    return (cents < 0 ? "-$" : "$") + fmtMoney(Math.abs(cents));
  }

  // ---------------------------------------------------------------- posting

  function account(state, code) {
    const acct = state.accounts.find((a) => a.code === code);
    if (!acct) throw new LedgerError(`Missing system account ${code}.`);
    return acct;
  }

  function getCategory(state, code, expectedType) {
    const acct = state.accounts.find(
      (a) => a.code === code && a.type === expectedType
    );
    if (!acct) throw new LedgerError(`Choose a valid ${expectedType} category.`);
    return acct;
  }

  function buildLines(state, txnType, form) {
    const cash = account(state, CODES.CASH).code;
    const amount = parseAmount(form.amount, false);
    let categoryName = null;
    let lines;

    if (txnType === "income") {
      const cat = getCategory(state, form.category_code, "income");
      categoryName = cat.name;
      lines = [[cash, amount], [cat.code, -amount]];
    } else if (txnType === "expense") {
      const cat = getCategory(state, form.category_code, "expense");
      categoryName = cat.name;
      lines = [[cat.code, amount], [cash, -amount]];
    } else if (txnType === "owner_contribution") {
      lines = [[cash, amount], [account(state, CODES.OWNER_CONTRIBUTIONS).code, -amount]];
    } else if (txnType === "owner_draw") {
      lines = [[account(state, CODES.OWNER_DRAWS).code, amount], [cash, -amount]];
    } else if (txnType === "loan_received") {
      lines = [[cash, amount], [account(state, CODES.LOANS_PAYABLE).code, -amount]];
    } else if (txnType === "loan_repayment") {
      const interestRaw = String(form.interest == null ? "" : form.interest).trim();
      let interest = 0;
      if (interestRaw) {
        try {
          interest = parseAmount(interestRaw, true);
        } catch (err) {
          throw new LedgerError(`Interest portion: ${err.message}`);
        }
      }
      if (interest > amount) {
        throw new LedgerError("Interest portion cannot exceed the total payment.");
      }
      const principal = amount - interest;
      lines = [[cash, -amount]];
      if (principal) lines.push([account(state, CODES.LOANS_PAYABLE).code, principal]);
      if (interest) lines.push([account(state, CODES.INTEREST_EXPENSE).code, interest]);
    } else if (txnType === "asset_purchase") {
      lines = [[account(state, CODES.FIXED_ASSETS).code, amount], [cash, -amount]];
    } else {
      throw new LedgerError(`Unknown transaction type '${txnType}'.`);
    }

    const total = lines.reduce((sum, [, cents]) => sum + cents, 0);
    if (total !== 0) throw new LedgerError("Internal error: transaction does not balance.");
    return {
      lines: lines.map(([code, cents]) => ({ account_code: code, amount_cents: cents })),
      categoryName,
    };
  }

  function resolveDescription(form, categoryName, txnType) {
    const description = String(form.description == null ? "" : form.description).trim();
    return description || categoryName || TXN_TYPE_LABELS[txnType] || txnType;
  }

  function postTransaction(state, txnType, form) {
    const date = parseDate(form.date);
    const { lines, categoryName } = buildLines(state, txnType, form);
    const txn = {
      id: state.nextId++,
      date,
      type: txnType,
      description: resolveDescription(form, categoryName, txnType),
      lines,
    };
    state.transactions.push(txn);
    return txn.id;
  }

  function updateTransaction(state, id, txnType, form) {
    const txn = state.transactions.find((t) => t.id === id);
    if (!txn) throw new LedgerError("Transaction not found.");
    const date = parseDate(form.date);
    const { lines, categoryName } = buildLines(state, txnType, form);
    txn.date = date;
    txn.type = txnType;
    txn.description = resolveDescription(form, categoryName, txnType);
    txn.lines = lines;
  }

  function deleteTransaction(state, id) {
    const index = state.transactions.findIndex((t) => t.id === id);
    if (index === -1) return false;
    state.transactions.splice(index, 1);
    return true;
  }

  function txnDetails(state, txn) {
    const cashLine = txn.lines.find((l) => l.account_code === CODES.CASH);
    const amount = cashLine ? Math.abs(cashLine.amount_cents) : 0;
    let categoryCode = null;
    let categoryName = null;
    let interest = 0;
    if (txn.type === "income" || txn.type === "expense") {
      const catLine = txn.lines.find((l) => {
        const acct = state.accounts.find((a) => a.code === l.account_code);
        return acct && (acct.type === "income" || acct.type === "expense");
      });
      if (catLine) {
        categoryCode = catLine.account_code;
        const acct = state.accounts.find((a) => a.code === categoryCode);
        categoryName = acct ? acct.name : null;
      }
    } else if (txn.type === "loan_repayment") {
      const intLine = txn.lines.find((l) => l.account_code === CODES.INTEREST_EXPENSE);
      if (intLine) interest = intLine.amount_cents;
    }
    return {
      id: txn.id,
      date: txn.date,
      type: txn.type,
      description: txn.description,
      amount_cents: amount,
      category_code: categoryCode,
      category_name: categoryName,
      interest_cents: interest,
    };
  }

  function listTransactions(state, filters) {
    const { start, end, type } = filters || {};
    return state.transactions
      .filter((t) => {
        if (start && t.date < start) return false;
        if (end && t.date > end) return false;
        if (type && t.type !== type) return false;
        return true;
      })
      .slice()
      .sort((a, b) => (a.date === b.date ? b.id - a.id : a.date < b.date ? 1 : -1))
      .map((t) => txnDetails(state, t));
  }

  // ---------------------------------------------------------------- reports

  function accountTotals(state, filterFn) {
    const totals = new Map();
    for (const txn of state.transactions) {
      if (!filterFn(txn)) continue;
      for (const line of txn.lines) {
        totals.set(line.account_code, (totals.get(line.account_code) || 0) + line.amount_cents);
      }
    }
    return totals;
  }

  function pnl(state, start, end) {
    const totals = accountTotals(state, (t) => t.date >= start && t.date <= end);
    const income = [];
    const expenses = [];
    const sorted = state.accounts.slice().sort((a, b) => a.code.localeCompare(b.code));
    for (const acct of sorted) {
      const total = totals.get(acct.code) || 0;
      if (total === 0) continue;
      if (acct.type === "income") income.push({ name: acct.name, amount: -total });
      else if (acct.type === "expense") expenses.push({ name: acct.name, amount: total });
    }
    const totalIncome = income.reduce((s, r) => s + r.amount, 0);
    const totalExpenses = expenses.reduce((s, r) => s + r.amount, 0);
    return {
      income,
      expenses,
      total_income: totalIncome,
      total_expenses: totalExpenses,
      net_profit: totalIncome - totalExpenses,
    };
  }

  function balanceSheet(state, asOf) {
    const totals = accountTotals(state, (t) => t.date <= asOf);
    const assets = [];
    const liabilities = [];
    const equity = [];
    let retained = 0;
    const sorted = state.accounts.slice().sort((a, b) => a.code.localeCompare(b.code));
    for (const acct of sorted) {
      const total = totals.get(acct.code) || 0;
      if (acct.type === "asset") {
        if (total !== 0 || acct.code === CODES.CASH) {
          assets.push({ name: acct.name, amount: total });
        }
      } else if (acct.type === "liability") {
        if (total !== 0) liabilities.push({ name: acct.name, amount: -total });
      } else if (acct.type === "equity") {
        if (total !== 0) equity.push({ name: acct.name, amount: -total });
      } else {
        retained -= total;
      }
    }
    if (!assets.some((a) => a.name === "Cash")) assets.push({ name: "Cash", amount: 0 });
    equity.push({ name: "Retained Earnings", amount: retained });
    const totalAssets = assets.reduce((s, r) => s + r.amount, 0);
    const totalLiabilities = liabilities.reduce((s, r) => s + r.amount, 0);
    const totalEquity = equity.reduce((s, r) => s + r.amount, 0);
    return {
      assets,
      liabilities,
      equity,
      total_assets: totalAssets,
      total_liabilities: totalLiabilities,
      total_equity: totalEquity,
      balanced: totalAssets === totalLiabilities + totalEquity,
    };
  }

  // ------------------------------------------------------------- categories

  function categories(state, type) {
    return state.accounts
      .filter((a) => a.type === type)
      .sort((a, b) => a.code.localeCompare(b.code));
  }

  function addCategory(state, name, type) {
    const trimmed = String(name == null ? "" : name).trim();
    if (!trimmed) throw new LedgerError("Category name is required.");
    if (type !== "income" && type !== "expense") {
      throw new LedgerError("Category type must be income or expense.");
    }
    const dup = state.accounts.some(
      (a) => a.type === type && a.name.toLowerCase() === trimmed.toLowerCase()
    );
    if (dup) throw new LedgerError(`A ${type} category named '${trimmed}' already exists.`);
    const [lo, hi] = type === "income" ? [4000, 4999] : [5000, 5999];
    let maxCode = lo - 1;
    for (const acct of state.accounts) {
      const n = parseInt(acct.code, 10);
      if (n >= lo && n <= hi && n > maxCode) maxCode = n;
    }
    const nextCode = maxCode + 1;
    if (nextCode > hi) throw new LedgerError("No category codes left in this range.");
    state.accounts.push({ code: String(nextCode), name: trimmed, type, is_system: 0 });
  }

  // --------------------------------------------------------- backup/restore

  const BACKUP_FORMAT = "simple-pl-bs-backup";

  function exportBackup(state, exportedOn) {
    return {
      format: BACKUP_FORMAT,
      version: 1,
      exported_on: exportedOn,
      accounts: state.accounts
        .slice()
        .sort((a, b) => a.code.localeCompare(b.code))
        .map((a) => ({ code: a.code, name: a.name, type: a.type, is_system: a.is_system })),
      transactions: state.transactions
        .slice()
        .sort((a, b) => a.id - b.id)
        .map((t) => ({
          date: t.date,
          type: t.type,
          description: t.description,
          lines: t.lines.map((l) => ({
            account_code: l.account_code,
            amount_cents: l.amount_cents,
          })),
        })),
    };
  }

  function importBackup(state, data) {
    if (!data || typeof data !== "object" || Array.isArray(data) || data.format !== BACKUP_FORMAT) {
      throw new LedgerError("This file is not a backup created by this app.");
    }
    const accounts = data.accounts;
    const txns = data.transactions;
    if (!Array.isArray(accounts) || !Array.isArray(txns)) {
      throw new LedgerError("Backup file is malformed.");
    }
    const codes = new Set();
    for (const a of accounts) {
      if (!a || typeof a !== "object" || !a.code || !a.name) {
        throw new LedgerError("Backup contains an invalid account.");
      }
      if (!VALID_ACCOUNT_TYPES.includes(a.type)) {
        throw new LedgerError(`Account '${a.name}' has an invalid type.`);
      }
      if (codes.has(a.code)) {
        throw new LedgerError(`Backup contains duplicate account code ${a.code}.`);
      }
      codes.add(a.code);
    }
    if (!codes.has(CODES.CASH)) throw new LedgerError("Backup is missing the Cash account.");

    const normalized = txns.map((t, i) => {
      const n = i + 1;
      if (!t || typeof t !== "object") throw new LedgerError(`Transaction #${n} is malformed.`);
      const date = parseDate(t.date);
      if (!TXN_TYPE_LABELS[t.type]) throw new LedgerError(`Transaction #${n} has an unknown type.`);
      if (!Array.isArray(t.lines) || t.lines.length === 0) {
        throw new LedgerError(`Transaction #${n} has no lines.`);
      }
      let total = 0;
      for (const l of t.lines) {
        if (
          !l || typeof l !== "object" ||
          !codes.has(l.account_code) ||
          typeof l.amount_cents !== "number" ||
          !Number.isInteger(l.amount_cents) ||
          l.amount_cents === 0
        ) {
          throw new LedgerError(`Transaction #${n} has an invalid line.`);
        }
        total += l.amount_cents;
      }
      if (total !== 0) throw new LedgerError(`Transaction #${n} does not balance.`);
      return {
        date,
        type: t.type,
        description: String(t.description || ""),
        lines: t.lines.map((l) => ({
          account_code: l.account_code,
          amount_cents: l.amount_cents,
        })),
      };
    });

    state.accounts = accounts.map((a) => ({
      code: String(a.code),
      name: String(a.name),
      type: a.type,
      is_system: a.is_system ? 1 : 0,
    }));
    state.transactions = normalized.map((t, i) => ({ id: i + 1, ...t }));
    state.nextId = normalized.length + 1;
    return normalized.length;
  }

  return {
    LedgerError,
    CODES,
    TXN_TYPE_LABELS,
    newState,
    parseAmount,
    parseDate,
    fmtMoney,
    fmtUsd,
    postTransaction,
    updateTransaction,
    deleteTransaction,
    txnDetails,
    listTransactions,
    pnl,
    balanceSheet,
    categories,
    addCategory,
    exportBackup,
    importBackup,
  };
});
