# Shared website and ERP data

User requirement: whenever a product name or any other stored website/ERP data changes, update the shared database and all relevant source files in the same task. Verify both applications use the updated values before reporting completion.

The shared database is `/Users/som/Documents/GitHub/Kalajay/Final/private/kalajay.sqlite3`. The website and ERP must continue using this single database.

- Preserve product_code when renaming products. Update products.name and the linked inventory JSON record; keep a name alias for backward compatibility. Update relevant catalogue/seed files so old names are not restored later.
- Preserve historical order name snapshots and transaction records; they describe the purchase at that time.
- Sync website HTML to content.homepage and ERP HTML to content.erp_homepage after editing. Restart the server after backend changes.
- Store team, city and authentication changes through their shared database tables/APIs. Keep credentials hashed and respect admin/manager permissions.
- Image files remain assets on disk; update database references if an asset path changes. Do not store image binaries in the content table.
- Back up the database before structural migrations and test changes without adding fake records to the live database.

## Current brand and catalogue instructions

- Use only current shared database records when preparing catalogues or documents. The catalogue uploaded at initial website creation is retired; do not use it to refill or overwrite the database.
- Brand description: We create pretty handcrafted beaded pieces for you that would make your daily life one bit more beautiful.
- Contact emails: support@kalajay.in and kalajay.handcrafted@gmail.com. Ask the user which one to include when producing each document.
- Inventory CP is bead quantity in kg × bead cost per kg + ₹50 × labor hours + other material cost. Preserve a legacy CP until costing inputs are provided.
