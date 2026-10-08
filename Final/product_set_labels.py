"""Rename set products in the shared database without changing their codes or history."""
import json
import sqlite3

RENAMES = {
    "Beaded Coaster Set, Grey & Blue": "Beaded Coaster Set, Grey & Blue (Set of 2)",
    "Beaded Coaster Set, Blue & White": "Beaded Coaster Set, Blue & White (Set of 2)",
    "Pearl Beaded Round Coaster Set": "Pearl Beaded Round Coaster (Set of 2)",
    "Pearl Beaded Tealight Holder Set": "Pearl Beaded Tealight Holder (Set of 2)",
    "Lilac Beaded Tealight Holder Set": "Lilac Beaded Tealight Holder (Set of 2)",
    "Pearl Beaded Tealight Holder Set of 2": "Pearl Beaded Tealight Holder (Set of 2)",
    "Lilac Beaded Tealight Holder Set of 2": "Lilac Beaded Tealight Holder (Set of 2)"
}

def migrate(connect, root):
    with connect() as db:
        pending = db.execute(
            'SELECT product_code, name FROM products WHERE name IN (' +
            ','.join('?' for _ in RENAMES) + ')', tuple(RENAMES)
        ).fetchall()
    if not pending:
        return
    backup = root / 'private' / 'before-product-set-labels.sqlite3'
    if not backup.exists():
        with connect() as source, sqlite3.connect(backup) as target:
            source.backup(target)
        backup.chmod(0o600)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        changed = False
        for code, old_name in pending:
            new_name = RENAMES[old_name]
            # Recheck under the write lock in case a concurrent editor renamed it.
            cursor = db.execute(
                'UPDATE products SET name=? WHERE product_code=? AND name=?',
                (new_name, code, old_name)
            )
            if not cursor.rowcount:
                continue
            changed = True
            db.execute('INSERT OR IGNORE INTO product_aliases VALUES (?,?)', (old_name, code))
            row = db.execute('SELECT record FROM inventory WHERE product_code=?', (code,)).fetchone()
            if row:
                record = json.loads(row[0])
                record['name'] = new_name
                db.execute('UPDATE inventory SET record=? WHERE product_code=?', (json.dumps(record), code))
        if changed:
            db.execute("UPDATE shared_meta SET value=value+1 WHERE key='revision'")
