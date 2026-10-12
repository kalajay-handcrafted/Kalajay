# Render deployment

One Python web service serves both the storefront and ERP, using a single SQLite database on a 1 GB persistent disk. Render setting details are in ../render.yaml. The ERP domain root redirects to /erp/; website root serves the storefront.

No private local database, account hash, session, or setup token is committed. On first start the catalogue is seeded and an admin setup token is created on the persistent disk. Retrieve /var/data/kalajay/auth-setup-token through Render Shell, then open https://SERVICE.onrender.com/erp/setup#TOKEN and create the production admin account. Manager accounts are created through Manage logins.

Test the onrender.com URL, login, catalogue export and role permissions before moving custom domains from the existing static sites. Domains: www.kalajay.in, kalajay.in, erp.kalajay.in. Add the same three names to this service and update the required DNS records at GoDaddy. HTTPS cookies are Secure and same-origin checks use HTTPS in production.

The packaged ERP source is Final/erp. When editing the separate KalajayERP repository, synchronize its index.html, support.js and assets into this directory before deploying the shared service. Keep all data changes in the shared database. Do not overwrite the production database on deploy. Back up /var/data/kalajay/kalajay.sqlite3 using SQLite online backup before migrations; download backups privately.

The local account is separate from the production account. Catalogue and inventory are seeded from repository content on first start only; future deployments preserve records on disk.
