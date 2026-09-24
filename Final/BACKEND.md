# Shared Kalajay database

Website: http://127.0.0.1:8000/

ERP: http://127.0.0.1:8000/erp/

Both are served by `backend.py` in the website's Final folder. Run `python3 backend.py --port 8000` from that folder. Do not run the old static server for either app.

The single database is `/Users/som/Desktop/Kalajay Claude/Kalajay website/Final/private/kalajay.sqlite3`.

## Tables and keys

| Table | Key / relationship | Purpose |
| --- | --- | --- |
| products | product_code PRIMARY KEY | Canonical names, categories, selling prices, images, availability and website publication |
| inventory | product_code PRIMARY KEY, FOREIGN KEY → products | ERP costs, opening stock, production, purchases, sales, damage and other inventory fields |
| inventory_transactions | id PRIMARY KEY; product_code FOREIGN KEY → products | Production, purchase, sale and damage history |
| orders | id PRIMARY KEY | Customer details, order time, totals, notes and status |
| order_items | (order_id, product_code) composite PRIMARY KEY; FOREIGN KEYs → orders/products | Product-code links with quantity and historical name/price snapshots |
| content | key PRIMARY KEY | Website page, ERP page and collection descriptions |
| product_aliases | name PRIMARY KEY; product_code FOREIGN KEY → products | Original website names mapped to stable product codes |
| shared_meta | key PRIMARY KEY | Revision control for concurrent editing |
| website_products_legacy | original name key | Preserved pre-migration catalogue |

Product codes remain stable when names change. Existing ERP codes are retained. Products without a reliable match receive a `KJ-WEB-###` code; no uncertain products were automatically merged. The database contains 68 products, of which the original 61 are published on the website. Images and videos remain in their asset folders and are referenced by stored content.

## Workflow

- ERP edits write to the shared database. Both apps refresh shared data every 10 seconds and when their browser tab regains focus.
- New website orders remain pending. They do not reserve or deduct stock.
- Use **Confirm order & record sale** in the ERP's Website orders section. Confirmation checks available stock, records a sale transaction, and deducts stock exactly once.
- If stock is insufficient, record production or a purchase first. Confirmation is rejected without partially updating inventory.
- Changes to inventory quantities update sold-out status. Initial zero inventory was preserved without marking all made-to-order website products sold out.
- Removing an ERP product archives it from active views; historical orders and transactions retain their references.
- Initial storefront selling prices take precedence over the ERP's zero-valued seed prices. ERP edits thereafter control the shared selling price.
- Unsubmitted shopping carts remain browser-session state; submitted orders are stored centrally.

## Previous browser data

The original ERP saved its products and transactions under the browser key `kalajay-erp-v2`. Those browser-only records are not in the supplied folder. **Import previous browser data** merges them if available on the new page's origin. If the previous ERP used a different address/browser, import a JSON backup containing `products` and `txns` from that original session. Imports merge by product code, so imported values replace matching inventory fields; existing orders are retained. No previous browser storage is deleted.

The ERP export button exports inventory and transactions, not customer orders. Back up the SQLite database for a complete data backup.

## Backups and deployment

The pre-migration database is `private/before-shared-migration.sqlite3`; original page/backend files are in `private/before-shared/`. The private directory is excluded from Git and HTTP file serving. No test records were added to the real database.

The server remains localhost-only. ERP routes are intended for this local trusted setup; authenticated ERP access and production hosting are required before public deployment.

Page content is stored in the database and refreshed from each app's editable index.html when the backend starts. Catalogue seed files are used only during initial setup; edit shared product records through the ERP afterward.

Validation completed: historical-order migration, unique product codes, foreign keys, shared pricing, concurrent-save protection, pending orders, idempotent confirmation, stock validation, archival, persistence, and HTTP file-access restrictions.
