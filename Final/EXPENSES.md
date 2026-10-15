# ERP Expenses

The shared Python service serves the new authenticated section at /erp/expenses.
Finance → Expenses in the bundled ERP opens it. The storefront is unchanged.

Records use the existing SQLite connection and persistent KALAJAY_DATA_DIR.
The additive expense_book migration first takes before-expenses.sqlite3.
Expense UI source is synchronized to content.expense_page at startup; the
existing shared migration synchronizes the edited ERP HTML to erp_homepage.
Image/PDF bytes stay in private expense-bills files on the persistent disk.

Admins can add/edit/delete entries, import XLSX or local-app JSON backups,
maintain budgets, resolve issues, attach bills, and export data. Managers can
view/export records. All page, JSON, backup, and bill reads require ERP login.
Writes require admin and the existing same-origin checks. Revision checks
reject concurrent overwrites. The screen refreshes every 10 seconds and on
focus, without replacing an open entry form.

The register view omits Date source, Group, and Type. Attribute filters use
imported file values plus Others; All clears a filter. Quantity, Price each,
and Total are exact numeric filters. Status choices on entry are Paid,
Not Recorded, Pending. Payment choices are UPI, Cash, Bank Transfer, GPay,
Others. Source-derived category, subcategory, treatment and frequency entry
choices start blank, with Others as the additional choice.

Overview defaults to all expenses through today (India date), with month and
custom periods. Monthly history ignores that period filter. Net cash flow
appears in the monthly table, not the summary cards. Notes are optional.

## Deploy

Deploy the same codex/render-backend branch used by kalajay-shared; do not
switch to the older main-branch backend. Existing environment values and
persistent disk must be retained. Startup handles the backed-up additive
migration and refreshes page content. No product, inventory, order, account
or team data is rewritten by expense operations.

For this initial integration, a short-lived KALAJAY_EXPENSE_LIBRARY_TRANSFER
environment value can transfer the existing expense package using the current
Library helper. Only the source package's imported register is merged, not
arbitrary browser data. Source IDs deduplicate entries, and a successful
Library file ID marker prevents a repeated download after URL expiry.
Remove or blank that temporary environment value after successful import.
Never commit its signed URL, transfer JSON, financial data or database.

Alternatively sign in as admin, open Expenses → Import & backup and select
the original Expense Tracker XLSX. Empty dates become 2026-09-30; explicit
dates and original amounts including zero are preserved. Original comments
remain blank. Repeated imports skip existing IDs and preserve later edits.
Use a local app JSON backup to include bill photos and later local entries.

A full expense JSON backup includes bill files; CSV exports filtered text.
A full server backup also needs the SQLite file and private expense-bills.
Deleting an entry does not delete old immutable bill files, preserving backup
references. No cleanup of production bills is automatic.

## Validation

Run from Final:
python3 -m unittest -v test_expenses
python3 -m py_compile backend.py expense_store.py expense_import.py expense_bootstrap.py

The PR workflow tests a temporary database, never production records.
It covers migrations/backup, existing table preservation, amount validation,
duplicate IDs, bill validation, protected routes, manager write rejection,
CSRF, revision conflicts and XLSX date/amount/import semantics.
