/**
 * Simple P&L → Google Sheet backup receiver.
 *
 * One-time setup (about 5 minutes, no Google Cloud account needed):
 *   1. In Google Drive, create a new Google Sheet (name it e.g. "Business Ledger").
 *   2. In the sheet: Extensions → Apps Script. Delete any starter code and
 *      paste this entire file. Click the save (disk) icon.
 *   3. Click Deploy → New deployment → gear icon → Web app.
 *        - Description: anything
 *        - Execute as: Me
 *        - Who has access: Anyone
 *      Click Deploy, then Authorize when Google asks (it may warn the app is
 *      unverified — click Advanced → Go to project). Copy the Web app URL.
 *   4. In Simple P&L: Settings → Google Sheet backup → paste the URL → Save.
 *      Click "Sync now" and check the sheet — your transactions appear.
 *
 * Optional: set TOKEN below to any password and enter the same value in the
 * app's Settings to reject pushes from anyone who guesses the URL.
 *
 * The app rewrites two tabs on every change:
 *   - "Transactions": every transaction, readable.
 *   - "Backup": a full JSON backup. To recover after a computer failure,
 *     copy all the cells in column A (row 2 down) into one text file, save it
 *     as backup.json, and use Settings → Restore from backup in the app.
 */

var TOKEN = ''; // optional shared password; '' disables the check

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    if (TOKEN && data.token !== TOKEN) {
      return reply({ ok: false, error: 'wrong sync token' });
    }

    var ss = SpreadsheetApp.getActiveSpreadsheet();

    var tx = ss.getSheetByName('Transactions') || ss.insertSheet('Transactions');
    tx.clearContents();
    var rows = [['Date', 'Type', 'Description', 'Category', 'Amount']].concat(
      data.rows || []
    );
    tx.getRange(1, 1, rows.length, 5).setValues(rows);
    tx.getRange('A1:E1').setFontWeight('bold');

    var bk = ss.getSheetByName('Backup') || ss.insertSheet('Backup');
    bk.clearContents();
    bk.getRange(1, 1).setValue(
      'Full backup (updated ' + data.generated_at + '). To restore: copy ' +
      'column A below into one file named backup.json, then use ' +
      'Settings → Restore from backup in Simple P&L.'
    );
    var chunks = (data.backup_chunks || []).map(function (c) { return [c]; });
    if (chunks.length) {
      bk.getRange(2, 1, chunks.length, 1).setValues(chunks);
    }

    return reply({ ok: true, rows: rows.length - 1 });
  } catch (err) {
    return reply({ ok: false, error: String(err) });
  }
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(
    ContentService.MimeType.JSON
  );
}
