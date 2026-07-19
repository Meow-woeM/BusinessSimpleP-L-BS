/* UI wiring for the browser version of Simple P&L. All bookkeeping logic
 * lives in ledger.js; this file renders it and persists to localStorage. */
(function () {
  "use strict";

  const L = window.Ledger;
  const STORAGE_KEY = "simple-pl-bs-data";

  // ------------------------------------------------------------ persistence

  function loadState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const data = JSON.parse(raw);
        const state = L.newState();
        L.importBackup(state, data);
        return state;
      }
    } catch (err) {
      console.error("Stored data unreadable, starting fresh:", err);
    }
    return L.newState();
  }

  function saveState() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(L.exportBackup(state, todayStr())));
  }

  const state = loadState();

  // ---------------------------------------------------------------- helpers

  function todayStr() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }

  function el(id) {
    return document.getElementById(id);
  }

  function h(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (key === "class") node.className = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value);
    }
    for (const child of children) {
      node.append(child);
    }
    return node;
  }

  function flash(message, kind) {
    const box = el("flash");
    box.replaceChildren(h("div", { class: `flash flash-${kind}` }, message));
    clearTimeout(flash._timer);
    flash._timer = setTimeout(() => box.replaceChildren(), 6000);
  }

  function download(filename, text, mime) {
    const blob = new Blob([text], { type: mime });
    const a = h("a", { href: URL.createObjectURL(blob), download: filename });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }

  function csvString(rows) {
    const quote = (v) => {
      const s = String(v == null ? "" : v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    // UTF-8 BOM so Excel decodes non-ASCII correctly.
    return "\ufeff" + rows.map((r) => r.map(quote).join(",")).join("\r\n") + "\r\n";
  }

  function plainMoney(cents) {
    return L.fmtMoney(cents).replace(/,/g, "");
  }

  // ------------------------------------------------------------- navigation

  const VIEWS = ["transactions", "pnl", "balance-sheet", "settings"];

  function showView(name) {
    if (!VIEWS.includes(name)) name = "transactions";
    for (const view of VIEWS) {
      el(`view-${view}`).hidden = view !== name;
    }
    for (const link of document.querySelectorAll("#nav a")) {
      link.classList.toggle("active", link.dataset.view === name);
    }
    if (name === "transactions") renderTransactions();
    if (name === "pnl") renderPnl();
    if (name === "balance-sheet") renderBalanceSheet();
    if (name === "settings") renderSettings();
  }

  window.addEventListener("hashchange", () => showView(location.hash.slice(1)));

  // ------------------------------------------------------- transaction form

  function fillTypeSelects() {
    const typeSelect = el("txn-type");
    typeSelect.replaceChildren(
      ...Object.entries(L.TXN_TYPE_LABELS).map(([value, label]) =>
        h("option", { value }, label)
      )
    );
    const filterType = el("filter-type");
    filterType.replaceChildren(
      h("option", { value: "" }, "All types"),
      ...Object.entries(L.TXN_TYPE_LABELS).map(([value, label]) =>
        h("option", { value }, label)
      )
    );
  }

  function fillCategorySelects() {
    el("income-category-select").replaceChildren(
      ...L.categories(state, "income").map((c) => h("option", { value: c.code }, c.name))
    );
    el("expense-category-select").replaceChildren(
      ...L.categories(state, "expense").map((c) => h("option", { value: c.code }, c.name))
    );
  }

  function updateTxnFields() {
    const type = el("txn-type").value;
    el("field-income-category").style.display = type === "income" ? "" : "none";
    el("field-expense-category").style.display = type === "expense" ? "" : "none";
    el("field-interest").style.display = type === "loan_repayment" ? "" : "none";
  }

  function resetTxnForm() {
    const form = el("txn-form");
    form.reset();
    form.elements.editing_id.value = "";
    form.elements.date.value = todayStr();
    el("txn-form-title").textContent = "Add a transaction";
    el("txn-submit").textContent = "Add transaction";
    el("txn-cancel-edit").hidden = true;
    updateTxnFields();
  }

  function startEdit(id) {
    const txn = state.transactions.find((t) => t.id === id);
    if (!txn) return;
    const details = L.txnDetails(state, txn);
    const form = el("txn-form");
    form.elements.editing_id.value = String(id);
    form.elements.type.value = details.type;
    form.elements.date.value = details.date;
    form.elements.amount.value = plainMoney(details.amount_cents);
    form.elements.description.value = details.description;
    form.elements.interest.value = details.interest_cents
      ? plainMoney(details.interest_cents)
      : "";
    if (details.category_code) {
      if (details.type === "income") form.elements.income_category.value = details.category_code;
      else form.elements.expense_category.value = details.category_code;
    }
    el("txn-form-title").textContent = `Edit transaction`;
    el("txn-submit").textContent = "Save changes";
    el("txn-cancel-edit").hidden = false;
    updateTxnFields();
    el("view-transactions").scrollIntoView({ behavior: "smooth" });
  }

  el("txn-type").addEventListener("change", updateTxnFields);
  el("txn-cancel-edit").addEventListener("click", resetTxnForm);

  el("txn-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.target;
    const type = form.elements.type.value;
    const fields = {
      date: form.elements.date.value,
      amount: form.elements.amount.value,
      description: form.elements.description.value,
      interest: form.elements.interest.value,
      category_code:
        type === "income"
          ? form.elements.income_category.value
          : form.elements.expense_category.value,
    };
    try {
      const editingId = parseInt(form.elements.editing_id.value, 10);
      if (editingId) {
        L.updateTransaction(state, editingId, type, fields);
        flash("Transaction updated.", "success");
      } else {
        L.postTransaction(state, type, fields);
        flash("Transaction added.", "success");
      }
      saveState();
      resetTxnForm();
      renderTransactions();
    } catch (err) {
      if (err instanceof L.LedgerError) flash(err.message, "error");
      else throw err;
    }
  });

  // --------------------------------------------------------------- filters

  let filters = {};

  el("filter-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.target;
    try {
      filters = {
        type: form.elements.type.value || null,
        start: form.elements.start.value ? L.parseDate(form.elements.start.value) : null,
        end: form.elements.end.value ? L.parseDate(form.elements.end.value) : null,
      };
      renderTransactions();
    } catch (err) {
      if (err instanceof L.LedgerError) flash(err.message, "error");
      else throw err;
    }
  });

  el("filter-clear").addEventListener("click", () => {
    el("filter-form").reset();
    filters = {};
    renderTransactions();
  });

  // ------------------------------------------------------------- rendering

  function renderTransactions() {
    fillCategorySelects();
    const rows = L.listTransactions(state, filters);
    const container = el("txn-table");
    if (rows.length === 0) {
      container.replaceChildren(
        h("p", { class: "empty" }, "No transactions yet. Add your first one above.")
      );
      return;
    }
    const negTypes = ["expense", "owner_draw", "loan_repayment", "asset_purchase"];
    container.replaceChildren(
      h(
        "table",
        {},
        h(
          "thead",
          {},
          h(
            "tr",
            {},
            h("th", {}, "Date"),
            h("th", {}, "Type"),
            h("th", {}, "Description"),
            h("th", {}, "Category"),
            h("th", { class: "num" }, "Amount"),
            h("th", {}, "")
          )
        ),
        h(
          "tbody",
          {},
          ...rows.map((t) =>
            h(
              "tr",
              {},
              h("td", {}, t.date),
              h("td", {}, L.TXN_TYPE_LABELS[t.type] || t.type),
              h("td", {}, t.description),
              h("td", {}, t.category_name || "—"),
              h(
                "td",
                {
                  class:
                    "num " +
                    (t.type === "income" ? "pos" : negTypes.includes(t.type) ? "neg" : ""),
                },
                L.fmtUsd(t.amount_cents)
              ),
              h(
                "td",
                { class: "actions" },
                h("button", { class: "link-button", onclick: () => startEdit(t.id) }, "Edit"),
                " ",
                h(
                  "button",
                  {
                    class: "link-button danger",
                    onclick: () => {
                      if (!confirm("Delete this transaction?")) return;
                      L.deleteTransaction(state, t.id);
                      saveState();
                      flash("Transaction deleted.", "success");
                      renderTransactions();
                    },
                  },
                  "Delete"
                )
              )
            )
          )
        )
      )
    );
  }

  function reportTable(sections) {
    const tbody = h("tbody", {});
    for (const section of sections) {
      tbody.append(h("tr", { class: "section-row" }, h("td", { colspan: "2" }, section.title)));
      if (section.rows.length === 0 && section.emptyLabel) {
        tbody.append(
          h(
            "tr",
            {},
            h("td", { class: "indent empty" }, section.emptyLabel),
            h("td", { class: "num" }, "$0.00")
          )
        );
      }
      for (const row of section.rows) {
        tbody.append(
          h(
            "tr",
            {},
            h("td", { class: "indent" }, row.name),
            h("td", { class: "num" }, L.fmtUsd(row.amount))
          )
        );
      }
      tbody.append(
        h(
          "tr",
          { class: "total-row" },
          h("td", {}, section.totalLabel),
          h("td", { class: "num" }, L.fmtUsd(section.total))
        )
      );
    }
    return tbody;
  }

  // -------------------------------------------------------------- P&L view

  function monthStart(d) {
    return new Date(d.getFullYear(), d.getMonth(), 1);
  }

  function fmtDate(d) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }

  function periodPresets() {
    const today = new Date();
    const thisMonth = monthStart(today);
    const lastMonthEnd = new Date(thisMonth.getTime() - 24 * 3600 * 1000);
    const yearStart = new Date(today.getFullYear(), 0, 1);
    const quarterStart = new Date(today.getFullYear(), Math.floor(today.getMonth() / 3) * 3, 1);
    return {
      this_month: ["This month", thisMonth, today],
      last_month: ["Last month", monthStart(lastMonthEnd), lastMonthEnd],
      this_quarter: ["This quarter", quarterStart, today],
      this_year: ["This year", yearStart, today],
      last_year: [
        "Last year",
        new Date(today.getFullYear() - 1, 0, 1),
        new Date(today.getFullYear() - 1, 11, 31),
      ],
      all_time: ["All time", new Date(1900, 0, 1), today],
    };
  }

  function renderPnl() {
    const form = el("pnl-form");
    if (!form.elements.start.value || !form.elements.end.value) {
      const [, start, end] = periodPresets().this_month;
      form.elements.start.value = fmtDate(start);
      form.elements.end.value = fmtDate(end);
    }
    const start = form.elements.start.value;
    const end = form.elements.end.value;

    const presets = periodPresets();
    el("pnl-presets").replaceChildren(
      ...Object.entries(presets).map(([key, [label, s, e]]) =>
        h(
          "a",
          {
            href: "#pnl",
            class: fmtDate(s) === start && fmtDate(e) === end ? "active" : "",
            onclick: (event) => {
              event.preventDefault();
              form.elements.start.value = fmtDate(s);
              form.elements.end.value = fmtDate(e);
              renderPnl();
            },
          },
          label
        )
      )
    );

    const report = L.pnl(state, start, end);
    const net = report.net_profit;
    el("pnl-report").replaceChildren(
      h("h2", {}, `${start} to ${end}`),
      h(
        "table",
        {},
        reportTable([
          {
            title: "Income",
            rows: report.income,
            emptyLabel: "No income in this period",
            totalLabel: "Total Income",
            total: report.total_income,
          },
          {
            title: "Expenses",
            rows: report.expenses,
            emptyLabel: "No expenses in this period",
            totalLabel: "Total Expenses",
            total: report.total_expenses,
          },
        ])
      )
    );
    el("pnl-report").querySelector("tbody").append(
      h(
        "tr",
        { class: `grand-total ${net >= 0 ? "pos" : "neg"}` },
        h("td", {}, net >= 0 ? "Net Profit" : "Net Loss"),
        h("td", { class: "num" }, L.fmtUsd(net))
      )
    );
  }

  el("pnl-form").addEventListener("submit", (event) => {
    event.preventDefault();
    try {
      const form = event.target;
      let start = L.parseDate(form.elements.start.value);
      let end = L.parseDate(form.elements.end.value);
      if (start > end) [start, end] = [end, start];
      form.elements.start.value = start;
      form.elements.end.value = end;
      renderPnl();
    } catch (err) {
      if (err instanceof L.LedgerError) flash(err.message, "error");
      else throw err;
    }
  });

  // ----------------------------------------------------- balance sheet view

  function renderBalanceSheet() {
    const form = el("bs-form");
    if (!form.elements.as_of.value) form.elements.as_of.value = todayStr();
    const asOf = form.elements.as_of.value;
    const report = L.balanceSheet(state, asOf);
    const container = el("bs-report");
    container.replaceChildren(
      h("h2", {}, `As of ${asOf}`),
      h(
        "table",
        {},
        reportTable([
          { title: "Assets", rows: report.assets, totalLabel: "Total Assets", total: report.total_assets },
          {
            title: "Liabilities",
            rows: report.liabilities,
            emptyLabel: "No liabilities",
            totalLabel: "Total Liabilities",
            total: report.total_liabilities,
          },
          { title: "Equity", rows: report.equity, totalLabel: "Total Equity", total: report.total_equity },
        ])
      ),
      h(
        "p",
        { class: `balance-check ${report.balanced ? "ok" : "bad"}` },
        report.balanced
          ? "✓ Balanced: assets equal liabilities plus equity."
          : "⚠ Out of balance — this should never happen; restore a backup or report a bug."
      )
    );
    container.querySelector("tbody").append(
      h(
        "tr",
        { class: "grand-total" },
        h("td", {}, "Total Liabilities + Equity"),
        h("td", { class: "num" }, L.fmtUsd(report.total_liabilities + report.total_equity))
      )
    );
    // Keep the balance-check note after the table.
    container.append(container.querySelector(".balance-check"));
  }

  el("bs-form").addEventListener("submit", (event) => {
    event.preventDefault();
    try {
      event.target.elements.as_of.value = L.parseDate(event.target.elements.as_of.value);
      renderBalanceSheet();
    } catch (err) {
      if (err instanceof L.LedgerError) flash(err.message, "error");
      else throw err;
    }
  });

  // --------------------------------------------------------------- settings

  function renderSettings() {
    el("income-cat-list").replaceChildren(
      ...L.categories(state, "income").map((c) => h("li", {}, c.name))
    );
    el("expense-cat-list").replaceChildren(
      ...L.categories(state, "expense").map((c) => h("li", {}, c.name))
    );
  }

  el("category-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.target;
    try {
      L.addCategory(state, form.elements.name.value, form.elements.type.value);
      saveState();
      form.reset();
      flash("Category added.", "success");
      renderSettings();
      fillCategorySelects();
    } catch (err) {
      if (err instanceof L.LedgerError) flash(err.message, "error");
      else throw err;
    }
  });

  // -------------------------------------------------------- export / import

  function exportTransactionsCsv() {
    const rows = [["Date", "Type", "Description", "Category", "Amount"]];
    for (const t of L.listTransactions(state, {})) {
      rows.push([
        t.date,
        L.TXN_TYPE_LABELS[t.type] || t.type,
        t.description,
        t.category_name || "",
        plainMoney(t.amount_cents),
      ]);
    }
    download("transactions.csv", csvString(rows), "text/csv");
  }

  el("export-txn-csv").addEventListener("click", exportTransactionsCsv);
  el("export-txn-csv-2").addEventListener("click", exportTransactionsCsv);

  el("export-pnl-csv").addEventListener("click", () => {
    const form = el("pnl-form");
    const start = form.elements.start.value;
    const end = form.elements.end.value;
    const report = L.pnl(state, start, end);
    const rows = [["Profit & Loss", `${start} to ${end}`], [], ["Income"]];
    for (const r of report.income) rows.push([r.name, plainMoney(r.amount)]);
    rows.push(["Total Income", plainMoney(report.total_income)], [], ["Expenses"]);
    for (const r of report.expenses) rows.push([r.name, plainMoney(r.amount)]);
    rows.push(
      ["Total Expenses", plainMoney(report.total_expenses)],
      [],
      ["Net Profit", plainMoney(report.net_profit)]
    );
    download(`pnl-${start}-to-${end}.csv`, csvString(rows), "text/csv");
  });

  el("export-bs-csv").addEventListener("click", () => {
    const asOf = el("bs-form").elements.as_of.value || todayStr();
    const report = L.balanceSheet(state, asOf);
    const rows = [["Balance Sheet", `As of ${asOf}`], [], ["Assets"]];
    for (const r of report.assets) rows.push([r.name, plainMoney(r.amount)]);
    rows.push(["Total Assets", plainMoney(report.total_assets)], [], ["Liabilities"]);
    for (const r of report.liabilities) rows.push([r.name, plainMoney(r.amount)]);
    rows.push(["Total Liabilities", plainMoney(report.total_liabilities)], [], ["Equity"]);
    for (const r of report.equity) rows.push([r.name, plainMoney(r.amount)]);
    rows.push(
      ["Total Equity", plainMoney(report.total_equity)],
      [],
      ["Total Liabilities + Equity", plainMoney(report.total_liabilities + report.total_equity)]
    );
    download(`balance-sheet-${asOf}.csv`, csvString(rows), "text/csv");
  });

  el("export-backup").addEventListener("click", () => {
    download(
      `backup-${todayStr()}.json`,
      JSON.stringify(L.exportBackup(state, todayStr()), null, 2),
      "application/json"
    );
  });

  el("import-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (!el("import-confirm").checked) {
      flash("Check the confirmation box to replace all existing data.", "error");
      return;
    }
    const file = el("import-file").files[0];
    if (!file) {
      flash("Choose a backup file to import.", "error");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const data = JSON.parse(reader.result);
        const count = L.importBackup(state, data);
        saveState();
        el("import-form").reset();
        flash(`Backup restored: ${count} transactions imported.`, "success");
        renderSettings();
        fillCategorySelects();
        renderTransactions();
      } catch (err) {
        if (err instanceof SyntaxError) flash("That file is not valid JSON.", "error");
        else if (err instanceof L.LedgerError) flash(err.message, "error");
        else throw err;
      }
    };
    reader.readAsText(file);
  });

  // ------------------------------------------------------------------ boot

  fillTypeSelects();
  fillCategorySelects();
  resetTxnForm();
  showView(location.hash.slice(1) || "transactions");

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("./sw.js").catch(() => {});
  }
})();
