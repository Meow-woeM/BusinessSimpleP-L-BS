/* Parity test: the browser ledger engine must produce exactly the same
 * numbers as the Python engine (see tests/test_accounting.py, whose expected
 * values these mirror). Run with:  node webapp/ledger.test.mjs */
import { createRequire } from "node:module";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const L = require("./ledger.js");

let failures = 0;
function test(name, fn) {
  try {
    fn();
    console.log(`ok   ${name}`);
  } catch (err) {
    failures += 1;
    console.error(`FAIL ${name}\n     ${err.message}`);
  }
}

function seedBooks(state) {
  // Same scenario as seed_books() in tests/test_accounting.py.
  L.postTransaction(state, "owner_contribution", { date: "2026-01-01", amount: "5000" });
  L.postTransaction(state, "loan_received", { date: "2026-01-05", amount: "2000" });
  L.postTransaction(state, "asset_purchase", { date: "2026-01-10", amount: "1500" });
  L.postTransaction(state, "income", { date: "2026-02-01", amount: "3000", category_code: "4000" });
  L.postTransaction(state, "expense", { date: "2026-02-10", amount: "800", category_code: "5000" });
  L.postTransaction(state, "loan_repayment", { date: "2026-02-15", amount: "550", interest: "50" });
  L.postTransaction(state, "owner_draw", { date: "2026-03-01", amount: "400" });
}

test("parse_amount valid values match Python", () => {
  assert.equal(L.parseAmount("10"), 1000);
  assert.equal(L.parseAmount("10.5"), 1050);
  assert.equal(L.parseAmount("10.55"), 1055);
  assert.equal(L.parseAmount("$1,234.56"), 123456);
  assert.equal(L.parseAmount(" 0.01 "), 1);
  assert.equal(L.parseAmount("0", true), 0);
});

test("parse_amount invalid values rejected like Python", () => {
  for (const bad of ["", "  ", "abc", "10.555", "0", "-5", "nan", "inf", "1e30",
                     "100000000000000000000", "1000000000000.00"]) {
    assert.throws(() => L.parseAmount(bad), L.LedgerError, `should reject ${bad}`);
  }
});

test("parse_date normalizes and bounds years like Python", () => {
  assert.equal(L.parseDate("2026-02-28"), "2026-02-28");
  assert.equal(L.parseDate("2026-6-1"), "2026-06-01");
  for (const bad of ["2026-13-40", "2026-02-30", "June 1", "0205-06-15", "3026-06-15"]) {
    assert.throws(() => L.parseDate(bad), L.LedgerError, `should reject ${bad}`);
  }
});

test("fmt_money matches Python", () => {
  assert.equal(L.fmtMoney(123456789), "1,234,567.89");
  assert.equal(L.fmtMoney(-50), "-0.50");
  assert.equal(L.fmtMoney(0), "0.00");
});

test("every transaction type posts balanced lines", () => {
  const state = L.newState();
  seedBooks(state);
  for (const txn of state.transactions) {
    const total = txn.lines.reduce((s, l) => s + l.amount_cents, 0);
    assert.equal(total, 0, `${txn.type} does not balance`);
  }
});

test("P&L matches Python expected values", () => {
  const state = L.newState();
  seedBooks(state);
  const report = L.pnl(state, "2026-01-01", "2026-12-31");
  assert.equal(report.total_income, 300000);
  assert.equal(report.total_expenses, 85000); // 800 rent + 50 loan interest
  assert.equal(report.net_profit, 215000);
  assert.deepEqual(
    report.expenses.map((r) => r.name).sort(),
    ["Interest Expense", "Rent"]
  );
  const jan = L.pnl(state, "2026-01-01", "2026-01-31");
  assert.equal(jan.total_income, 0);
  assert.equal(jan.total_expenses, 0);
});

test("balance sheet matches Python expected values", () => {
  const state = L.newState();
  seedBooks(state);
  const report = L.balanceSheet(state, "2026-12-31");
  const assets = Object.fromEntries(report.assets.map((r) => [r.name, r.amount]));
  assert.equal(assets["Cash"], 675000);
  assert.equal(assets["Equipment & Other Assets"], 150000);
  assert.equal(report.total_assets, 825000);
  assert.equal(report.total_liabilities, 150000);
  const equity = Object.fromEntries(report.equity.map((r) => [r.name, r.amount]));
  assert.equal(equity["Owner Contributions"], 500000);
  assert.equal(equity["Owner Draws"], -40000);
  assert.equal(equity["Retained Earnings"], 215000);
  assert.equal(report.total_equity, 675000);
  assert.ok(report.balanced);

  const early = L.balanceSheet(state, "2026-01-31");
  const earlyAssets = Object.fromEntries(early.assets.map((r) => [r.name, r.amount]));
  assert.equal(earlyAssets["Cash"], 550000);
  assert.equal(early.total_liabilities, 200000);
  assert.ok(early.balanced);
});

test("edit and delete keep the ledger balanced", () => {
  const state = L.newState();
  const id = L.postTransaction(state, "income", {
    date: "2026-06-15", amount: "100", category_code: "4000",
  });
  L.updateTransaction(state, id, "expense", {
    date: "2026-06-20", amount: "80", category_code: "5000", description: "now an expense",
  });
  const details = L.txnDetails(state, state.transactions[0]);
  assert.equal(details.type, "expense");
  assert.equal(details.amount_cents, 8000);
  assert.ok(L.balanceSheet(state, "2026-12-31").balanced);
  assert.ok(L.deleteTransaction(state, id));
  assert.equal(state.transactions.length, 0);
});

test("zero interest treated as no interest; bad interest names the field", () => {
  const state = L.newState();
  const id = L.postTransaction(state, "loan_repayment", {
    date: "2026-06-15", amount: "100", interest: "0",
  });
  const txn = state.transactions.find((t) => t.id === id);
  assert.deepEqual(
    txn.lines.map((l) => [l.account_code, l.amount_cents]).sort(),
    [["1000", -10000], ["2000", 10000]]
  );
  assert.throws(
    () => L.postTransaction(state, "loan_repayment", { date: "2026-06-15", amount: "100", interest: "abc" }),
    /Interest portion/
  );
});

test("backup roundtrip preserves reports (and matches the desktop format)", () => {
  const state = L.newState();
  seedBooks(state);
  L.addCategory(state, "Consulting", "income");
  const before = L.balanceSheet(state, "2026-12-31");
  const backup = L.exportBackup(state, "2026-07-18");
  assert.equal(backup.format, "simple-pl-bs-backup");
  assert.equal(backup.version, 1);

  const restored = L.newState();
  const count = L.importBackup(restored, JSON.parse(JSON.stringify(backup)));
  assert.equal(count, 7);
  assert.deepEqual(L.balanceSheet(restored, "2026-12-31"), before);
  assert.deepEqual(L.pnl(restored, "2026-01-01", "2026-12-31"), L.pnl(state, "2026-01-01", "2026-12-31"));
});

test("import rejects invalid backups like Python", () => {
  const state = L.newState();
  const backup = L.exportBackup(state, "2026-07-18");
  const unbalanced = JSON.parse(JSON.stringify(backup));
  unbalanced.transactions.push({
    date: "2026-01-01", type: "income", description: "bad",
    lines: [{ account_code: "1000", amount_cents: 100 }],
  });
  assert.throws(() => L.importBackup(L.newState(), unbalanced), /does not balance/);
  assert.throws(() => L.importBackup(L.newState(), { format: "something-else" }), L.LedgerError);
  const badLine = JSON.parse(JSON.stringify(backup));
  badLine.transactions.push({
    date: "2026-01-01", type: "income", description: "bad",
    lines: [
      { account_code: "9999", amount_cents: 100 },
      { account_code: "1000", amount_cents: -100 },
    ],
  });
  assert.throws(() => L.importBackup(L.newState(), badLine), L.LedgerError);
  // Non-integer and boolean amounts must be rejected.
  const floatLine = JSON.parse(JSON.stringify(backup));
  floatLine.transactions.push({
    date: "2026-01-01", type: "income", description: "bad",
    lines: [
      { account_code: "1000", amount_cents: 0.5 },
      { account_code: "4000", amount_cents: -0.5 },
    ],
  });
  assert.throws(() => L.importBackup(L.newState(), floatLine), L.LedgerError);
});

test("category management matches Python", () => {
  const state = L.newState();
  L.addCategory(state, "Consulting", "income");
  const added = state.accounts.find((a) => a.name === "Consulting");
  assert.equal(added.type, "income");
  assert.ok(+added.code >= 4000 && +added.code <= 4999);
  assert.throws(() => L.addCategory(state, "consulting", "income"), /already exists/);
  assert.throws(() => L.addCategory(state, "", "income"), L.LedgerError);
  assert.throws(() => L.addCategory(state, "Stuff", "asset"), L.LedgerError);
});

if (failures) {
  console.error(`\n${failures} test(s) failed`);
  process.exit(1);
}
console.log("\nall parity tests passed");
