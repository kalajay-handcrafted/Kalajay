"""One-time, backed-up stock adjustment explicitly requested by the owner."""
import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from shared_store import stock

MARKER = 'stock-zero-2026-10-21-v1'

def apply_once(connect, data_dir):
    with connect() as db:
        if db.execute('SELECT 1 FROM content WHERE key=?', (MARKER,)).fetchone():
            return
    backup = Path(data_dir) / 'before-stock-zero-2026-10-21.sqlite3'
    if not backup.exists():
        with connect() as source, sqlite3.connect(backup) as destination:
            source.backup(destination)
        backup.chmod(0o600)
    today = datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM content WHERE key=?', (MARKER,)).fetchone():
            return
        rows = db.execute('SELECT i.product_code,i.record FROM inventory i JOIN products p USING(product_code) WHERE p.active=1').fetchall()
        adjusted = 0
        for row in rows:
            product = json.loads(row['record'])
            current = stock(product)
            if not math.isfinite(current):
                raise ValueError('Invalid stock; zero-stock adjustment rolled back.')
            if current != 0:
                # Cancel the original stock components exactly, preserving their history.
                product['adjustment'] = -(product['open'] + product['purch'] + product['made'] - product['sold'] - product['dmg'])
                product['upd'] = today
                if stock(product) != 0:
                    raise ValueError('Stock did not reach zero; adjustment rolled back.')
                transaction = dict(id='reset-20261021-'+row['product_code'], date=today, type='Adjustment',
                                   code=row['product_code'], qty=-current, rate=product.get('cp', 0),
                                   ref='Owner request: set all master inventory stock to zero')
                db.execute('INSERT INTO inventory_transactions VALUES (?,?,?)',
                           (transaction['id'], row['product_code'], json.dumps(transaction)))
                db.execute('UPDATE inventory SET record=? WHERE product_code=?',
                           (json.dumps(product), row['product_code']))
                adjusted += 1
            db.execute('UPDATE products SET sold_out=1 WHERE product_code=?', (row['product_code'],))
        # Fail atomically if any active item has a nonzero stock after the adjustment.
        remaining = sum(stock(json.loads(row[0])) != 0 for row in db.execute(
            'SELECT i.record FROM inventory i JOIN products p USING(product_code) WHERE p.active=1'))
        if remaining:
            raise ValueError('Nonzero stock remains; adjustment rolled back.')
        db.execute("UPDATE shared_meta SET value=value+1 WHERE key='revision'")
        db.execute('INSERT INTO content VALUES (?,?)',
                   (MARKER, json.dumps({'items':len(rows), 'adjusted':adjusted, 'remainingNonzero':remaining})))
    print('Stock reset complete: items='+str(len(rows))+'; adjusted='+str(adjusted)+'; remaining_nonzero='+str(remaining), flush=True)
