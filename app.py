"""Simple income & expenses tracker with P&L and balance sheet reports.

Run with:  python app.py   (then open http://127.0.0.1:5000)
"""

import csv
import io
import json
import os
import sys
from datetime import date, timedelta

from flask import (
    Flask,
    Response,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

import accounting
import db
import sync
from accounting import LedgerError, TXN_TYPE_LABELS

# When frozen by PyInstaller, templates/static are unpacked next to _MEIPASS.
BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def month_start(d):
    return d.replace(day=1)


def quarter_start(d):
    return d.replace(month=(d.month - 1) // 3 * 3 + 1, day=1)


def period_presets(today=None):
    """Named date ranges for the P&L period selector."""
    today = today or date.today()
    this_month = month_start(today)
    last_month_end = this_month - timedelta(days=1)
    year_start = today.replace(month=1, day=1)
    return {
        "this_month": (this_month, today),
        "last_month": (month_start(last_month_end), last_month_end),
        "this_quarter": (quarter_start(today), today),
        "this_year": (year_start, today),
        "last_year": (
            year_start.replace(year=today.year - 1),
            date(today.year - 1, 12, 31),
        ),
        "all_time": (date(1900, 1, 1), today),
    }


def resolve_period(args):
    """Turn ?preset= or ?start=&?end= query params into a (start, end) range."""
    presets = period_presets()
    preset = args.get("preset")
    if preset in presets:
        start, end = presets[preset]
        return start.isoformat(), end.isoformat(), preset
    start = args.get("start")
    end = args.get("end")
    if start and end:
        start = accounting.parse_date(start)
        end = accounting.parse_date(end)
        if start > end:
            start, end = end, start
        return start, end, "custom"
    start, end = presets["this_month"]
    return start.isoformat(), end.isoformat(), "this_month"


def create_app(db_path=None):
    app = Flask(
        __name__,
        template_folder=os.path.join(BASE_DIR, "templates"),
        static_folder=os.path.join(BASE_DIR, "static"),
    )
    app.secret_key = os.environ.get("SECRET_KEY", "dev-only-not-secret")
    app.config["DB_PATH"] = db_path or os.environ.get("LEDGER_DB", "ledger.db")
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

    db.init_db(app.config["DB_PATH"])

    def changed(conn):
        """Mark the ledger dirty and queue a Google Sheet push."""
        sync.mark_dirty(conn)
        if not app.config.get("TESTING"):
            sync.schedule_push(app.config["DB_PATH"])

    # Catch up on changes made while offline (or before sync was set up).
    startup_conn = db.connect(app.config["DB_PATH"])
    try:
        if sync.get_config(startup_conn)["dirty"]:
            sync.schedule_push(app.config["DB_PATH"])
    finally:
        startup_conn.close()
    app.teardown_appcontext(db.close_db)
    app.jinja_env.filters["money"] = accounting.fmt_money
    app.jinja_env.filters["usd"] = lambda cents: ("-$" if cents < 0 else "$") + accounting.fmt_money(abs(cents))
    app.jinja_env.globals["txn_type_labels"] = TXN_TYPE_LABELS

    @app.errorhandler(LedgerError)
    def handle_ledger_error(err):
        flash(str(err), "error")
        return redirect(request.referrer or url_for("transactions"))

    @app.route("/")
    def index():
        return redirect(url_for("transactions"))

    # ------------------------------------------------------------------
    # Transactions

    @app.route("/transactions")
    def transactions():
        conn = db.get_db()
        txn_type = request.args.get("type") or None
        if txn_type and txn_type not in TXN_TYPE_LABELS:
            txn_type = None
        start = request.args.get("start") or None
        end = request.args.get("end") or None
        if start:
            start = accounting.parse_date(start)
        if end:
            end = accounting.parse_date(end)
        rows = accounting.list_transactions(conn, start=start, end=end, txn_type=txn_type)
        return render_template(
            "transactions.html",
            transactions=rows,
            income_categories=accounting.categories(conn, "income"),
            expense_categories=accounting.categories(conn, "expense"),
            today=date.today().isoformat(),
            filter_type=txn_type or "",
            filter_start=start or "",
            filter_end=end or "",
        )

    @app.route("/transactions", methods=["POST"])
    def create_transaction():
        conn = db.get_db()
        txn_type = request.form.get("type", "")
        accounting.post_transaction(conn, txn_type, request.form)
        changed(conn)
        flash("Transaction added.", "success")
        return redirect(url_for("transactions"))

    @app.route("/transactions/<int:txn_id>/edit", methods=["GET", "POST"])
    def edit_transaction(txn_id):
        conn = db.get_db()
        details = accounting.txn_details(conn, txn_id)
        if details is None:
            flash("Transaction not found.", "error")
            return redirect(url_for("transactions"))
        if request.method == "POST":
            txn_type = request.form.get("type", "")
            accounting.update_transaction(conn, txn_id, txn_type, request.form)
            changed(conn)
            flash("Transaction updated.", "success")
            return redirect(url_for("transactions"))
        return render_template(
            "edit_transaction.html",
            txn=details,
            income_categories=accounting.categories(conn, "income"),
            expense_categories=accounting.categories(conn, "expense"),
        )

    @app.route("/transactions/<int:txn_id>/delete", methods=["POST"])
    def delete_transaction(txn_id):
        conn = db.get_db()
        if accounting.delete_transaction(conn, txn_id):
            changed(conn)
            flash("Transaction deleted.", "success")
        else:
            flash("Transaction not found.", "error")
        return redirect(url_for("transactions"))

    # ------------------------------------------------------------------
    # Reports

    @app.route("/pnl")
    def pnl():
        conn = db.get_db()
        start, end, preset = resolve_period(request.args)
        report = accounting.pnl(conn, start, end)
        return render_template(
            "pnl.html", report=report, start=start, end=end, preset=preset
        )

    @app.route("/balance-sheet")
    def balance_sheet():
        conn = db.get_db()
        as_of = request.args.get("as_of")
        as_of = accounting.parse_date(as_of) if as_of else date.today().isoformat()
        report = accounting.balance_sheet(conn, as_of)
        return render_template("balance_sheet.html", report=report, as_of=as_of)

    # ------------------------------------------------------------------
    # Settings: categories + backup

    @app.route("/settings")
    def settings():
        conn = db.get_db()
        try:
            with open(os.path.join(BASE_DIR, "apps_script.gs")) as f:
                apps_script = f.read()
        except OSError:
            apps_script = ""
        return render_template(
            "settings.html",
            income_categories=accounting.categories(conn, "income"),
            expense_categories=accounting.categories(conn, "expense"),
            sync=sync.get_config(conn),
            apps_script=apps_script,
        )

    @app.route("/categories", methods=["POST"])
    def add_category():
        conn = db.get_db()
        accounting.add_category(
            conn, request.form.get("name"), request.form.get("type", "")
        )
        changed(conn)
        flash("Category added.", "success")
        return redirect(url_for("settings"))

    # ------------------------------------------------------------------
    # Google Sheet backup

    @app.route("/settings/sync", methods=["POST"])
    def save_sync_settings():
        conn = db.get_db()
        sync.save_config(conn, request.form.get("url"), request.form.get("token"))
        if sync.get_config(conn)["url"]:
            sync.mark_dirty(conn)
            flash("Google Sheet backup saved — click “Sync now” to test it.", "success")
        else:
            flash("Google Sheet backup turned off.", "success")
        return redirect(url_for("settings"))

    @app.route("/sync-now", methods=["POST"])
    def sync_now():
        conn = db.get_db()
        ok, message = sync.push(conn)
        flash(message, "success" if ok else "error")
        return redirect(url_for("settings"))

    # ------------------------------------------------------------------
    # Export / import

    @app.route("/export/backup.json")
    def export_backup():
        conn = db.get_db()
        payload = json.dumps(accounting.export_backup(conn), indent=2)
        return Response(
            payload,
            mimetype="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=backup-{date.today().isoformat()}.json"
            },
        )

    @app.route("/import", methods=["POST"])
    def import_backup():
        if request.form.get("confirm") != "yes":
            raise LedgerError(
                "Check the confirmation box to replace all existing data."
            )
        upload = request.files.get("backup")
        if upload is None or not upload.filename:
            raise LedgerError("Choose a backup file to import.")
        try:
            data = json.load(upload.stream)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise LedgerError("That file is not valid JSON.")
        conn = db.get_db()
        count = accounting.import_backup(conn, data)
        changed(conn)
        flash(f"Backup restored: {count} transactions imported.", "success")
        return redirect(url_for("settings"))

    def csv_response(rows, filename):
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerows(rows)
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    @app.route("/export/transactions.csv")
    def export_transactions_csv():
        conn = db.get_db()
        rows = [["Date", "Type", "Description", "Category", "Amount"]]
        for t in accounting.list_transactions(conn):
            rows.append(
                [
                    t["txn_date"],
                    TXN_TYPE_LABELS.get(t["txn_type"], t["txn_type"]),
                    t["description"],
                    t["category_name"] or "",
                    accounting.fmt_money(t["amount_cents"]).replace(",", ""),
                ]
            )
        return csv_response(rows, "transactions.csv")

    @app.route("/export/pnl.csv")
    def export_pnl_csv():
        conn = db.get_db()
        start, end, _ = resolve_period(request.args)
        report = accounting.pnl(conn, start, end)
        money = lambda c: accounting.fmt_money(c).replace(",", "")
        rows = [["Profit & Loss", f"{start} to {end}"], [], ["Income"]]
        rows += [[i["name"], money(i["amount"])] for i in report["income"]]
        rows.append(["Total Income", money(report["total_income"])])
        rows += [[], ["Expenses"]]
        rows += [[e["name"], money(e["amount"])] for e in report["expenses"]]
        rows.append(["Total Expenses", money(report["total_expenses"])])
        rows += [[], ["Net Profit", money(report["net_profit"])]]
        return csv_response(rows, f"pnl-{start}-to-{end}.csv")

    @app.route("/export/balance-sheet.csv")
    def export_balance_sheet_csv():
        conn = db.get_db()
        as_of = request.args.get("as_of")
        as_of = accounting.parse_date(as_of) if as_of else date.today().isoformat()
        report = accounting.balance_sheet(conn, as_of)
        money = lambda c: accounting.fmt_money(c).replace(",", "")
        rows = [["Balance Sheet", f"As of {as_of}"], [], ["Assets"]]
        rows += [[a["name"], money(a["amount"])] for a in report["assets"]]
        rows.append(["Total Assets", money(report["total_assets"])])
        rows += [[], ["Liabilities"]]
        rows += [[l["name"], money(l["amount"])] for l in report["liabilities"]]
        rows.append(["Total Liabilities", money(report["total_liabilities"])])
        rows += [[], ["Equity"]]
        rows += [[e["name"], money(e["amount"])] for e in report["equity"]]
        rows.append(["Total Equity", money(report["total_equity"])])
        rows += [
            [],
            [
                "Total Liabilities + Equity",
                money(report["total_liabilities"] + report["total_equity"]),
            ],
        ]
        return csv_response(rows, f"balance-sheet-{as_of}.csv")

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
