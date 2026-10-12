"""Apply website category and typography changes to the shared store."""
import json
import sqlite3

def clean(text):
    return text.replace('\u2014', '-')

def category(text):
    return 'Little Treasures' if text == 'Special Pieces' else clean(text)

def migrate(connect, root):
    with connect() as db:
        rows = db.execute('SELECT product_code,name,category FROM products').fetchall()
        row = db.execute("SELECT value FROM content WHERE key='collections'").fetchone()
        collections = json.loads(row[0]) if row else []
        updated = [[category(c[0]), clean(c[1]), *c[2:]] for c in collections]
        pending = [(code, name, cat) for code, name, cat in rows
                   if clean(name) != name or category(cat) != cat]
    if not pending and collections == updated:
        return
    backup = root / 'private' / 'before-website-refresh.sqlite3'
    if not backup.exists():
        with connect() as source, sqlite3.connect(backup) as target:
            source.backup(target)
        backup.chmod(0o600)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        changed = False
        for code, _, _ in pending:
            row = db.execute('SELECT name,category FROM products WHERE product_code=?', (code,)).fetchone()
            if not row:
                continue
            name, cat = row
            new_name, new_cat = clean(name), category(cat)
            if (name,cat) == (new_name,new_cat):
                continue
            db.execute('UPDATE products SET name=?,category=? WHERE product_code=?', (new_name,new_cat,code))
            if name != new_name:
                db.execute('INSERT OR IGNORE INTO product_aliases VALUES (?,?)', (name,code))
            inv = db.execute('SELECT record FROM inventory WHERE product_code=?', (code,)).fetchone()
            if inv:
                record = json.loads(inv[0])
                record.update(name=new_name,cat=new_cat)
                db.execute('UPDATE inventory SET record=? WHERE product_code=?', (json.dumps(record),code))
            changed = True
        # Refresh collections under the same write lock to preserve concurrent edits.
        row = db.execute("SELECT value FROM content WHERE key='collections'").fetchone()
        if row:
            current = json.loads(row[0])
            updated = [[category(c[0]), clean(c[1]), *c[2:]] for c in current]
            if current != updated:
                db.execute("UPDATE content SET value=? WHERE key='collections'", (json.dumps(updated),))
                changed = True
        if changed:
            db.execute("UPDATE shared_meta SET value=value+1 WHERE key='revision'")
