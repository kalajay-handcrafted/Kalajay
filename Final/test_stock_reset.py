import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
import stock_reset
from shared_store import record, stock

class StockResetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root/'kalajay.sqlite3'
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE content (key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE shared_meta (key TEXT PRIMARY KEY,value INTEGER NOT NULL);
            INSERT INTO shared_meta VALUES ('revision',7);
            CREATE TABLE products (product_code TEXT PRIMARY KEY,active INTEGER,sold_out INTEGER);
            CREATE TABLE inventory (product_code TEXT PRIMARY KEY,record TEXT NOT NULL);
            CREATE TABLE inventory_transactions (id TEXT PRIMARY KEY,product_code TEXT,record TEXT);
            """)
        for code, values, active in [
            ('POS',dict(open=10,purch=5,made=4,sold=3,dmg=1,adjustment=-2),1),
            ('ZERO',dict(open=0),1),
            ('NEG',dict(open=2,sold=4),1),
            ('FRACTION',dict(open=.3,purch=.2,sold=.1,adjustment=.05),1),
            ('ARCHIVED',dict(open=8),0)]:
            p=record(code,code,'Test');p.update(values)
            with self.connect() as db:
                db.execute('INSERT INTO products VALUES (?,?,0)',(code,active))
                db.execute('INSERT INTO inventory VALUES (?,?)',(code,json.dumps(p)))
        with self.connect() as db:
            db.execute('INSERT INTO inventory_transactions VALUES (?,?,?)',('history','POS',json.dumps({'original':'unchanged'})))
    def connect(self):
        db=sqlite3.connect(self.path);db.row_factory=sqlite3.Row;return db
    def tearDown(self):
        self.temp.cleanup()
    def records(self):
        with self.connect() as db:
            return {r[0]:json.loads(r[1]) for r in db.execute('SELECT * FROM inventory')}
    def test_zero_preserves_history_and_backs_up(self):
        before=self.records()
        stock_reset.apply_once(self.connect,self.root)
        after=self.records()
        for code in ('POS','ZERO','NEG','FRACTION'):
            self.assertEqual(stock(after[code]),0)
            for key in ('open','purch','made','sold','dmg','cp','sp','name'):
                self.assertEqual(after[code][key],before[code][key])
        self.assertEqual(after['ARCHIVED'],before['ARCHIVED'])
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT record FROM inventory_transactions WHERE id='history'").fetchone()[0],json.dumps({'original':'unchanged'}))
            adjustments=[json.loads(r[0]) for r in db.execute("SELECT record FROM inventory_transactions WHERE id!='history'")]
            self.assertEqual(len(adjustments),3)
            self.assertEqual({t['code']:t['qty'] for t in adjustments},{c:-stock(before[c]) for c in ('POS','NEG','FRACTION')})
            self.assertEqual(db.execute("SELECT value FROM shared_meta WHERE key='revision'").fetchone()[0],8)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM products WHERE active=1 AND sold_out=0').fetchone()[0],0)
        with sqlite3.connect(self.root/'before-stock-zero-2026-10-21.sqlite3') as db:
            p=json.loads(db.execute("SELECT record FROM inventory WHERE product_code='POS'").fetchone()[0])
        self.assertEqual(p,before['POS'])
    def test_restart_keeps_future_stock(self):
        stock_reset.apply_once(self.connect,self.root)
        records=self.records()
        records['POS']['made']+=5
        with self.connect() as db:
            db.execute("UPDATE inventory SET record=? WHERE product_code='POS'",(json.dumps(records['POS']),))
        stock_reset.apply_once(self.connect,self.root)
        self.assertEqual(stock(self.records()['POS']),5)
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM inventory_transactions').fetchone()[0],4)
    def test_failure_rolls_back_entire_reset(self):
        before=self.records()
        with self.connect() as db:
            broken={**before['NEG'],'open':float('nan')}
            db.execute("UPDATE inventory SET record=? WHERE product_code='NEG'",(json.dumps(broken),))
        with self.assertRaises(ValueError):
            stock_reset.apply_once(self.connect,self.root)
        self.assertEqual(self.records()['POS'],before['POS'])
        with self.connect() as db:
            self.assertFalse(db.execute('SELECT 1 FROM content WHERE key=?',(stock_reset.MARKER,)).fetchone())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM inventory_transactions').fetchone()[0],1)

if __name__=='__main__':
    unittest.main()
