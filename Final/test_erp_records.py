import copy
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
import erp_audit as audit
import erp_records as records
import shared_store as shared
import expense_store as expenses
import team_store as team
import team_images
import auth_store as auth

class RecordTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.path=self.root/'db'
        (self.root/'index.html').write_text('fixture')
        with self.connect() as db:
            db.executescript("CREATE TABLE products(name TEXT PRIMARY KEY,image TEXT,category TEXT,price REAL,sold_out INTEGER,position INTEGER);CREATE TABLE content(key TEXT PRIMARY KEY,value TEXT);INSERT INTO content VALUES('collections','[]');CREATE TABLE orders(id TEXT PRIMARY KEY,created_at TEXT,customer TEXT,items TEXT,total REAL,note TEXT,status TEXT DEFAULT 'new');")
        shared.migrate(self.connect,self.root,self.root);team.initialize(self.connect);team_images.initialize(self.connect,self.root);expenses.initialize(self.connect,self.root);auth.initialize(self.connect,self.root);audit.initialize(self.connect,self.root)
        self.tokens=[audit.actor.set('admin-test'),audit.request_id.set('test-request'),audit.source.set('/api/erp/record-action')]
        p=shared.record('A','Alpha','Bags');p.update(open=10,sp=100,cp=40,image='/assets/a.jpg')
        p2=shared.record('B','Beta','Organisers');p2.update(open=2,sp=200)
        s=shared.state(self.connect);s['products']=[p,p2];shared.update(self.connect,s)
        with self.connect() as db:db.execute('UPDATE products SET published=1')
    def connect(self):
        db=sqlite3.connect(self.path);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');audit.configure(db);return db
    def tearDown(self):
        audit.actor.reset(self.tokens[0]);audit.request_id.reset(self.tokens[1]);audit.source.reset(self.tokens[2]);self.temp.cleanup()
    def find(self,kind,key):return next(r for r in records.listing(self.connect,kind)['records'] if r['id']==key)
    def action(self,kind,key,data=None,delete=False,version=None):
        item=self.find(kind,key)
        return records.apply(self.connect,self.root,{'kind':kind,'id':key,'version':version or item['version'],'action':'delete' if delete else 'edit','data':data or item['data']},'admin-test')
    def product(self,key):return self.find('products',key)['data']
    def audit_count(self):
        with self.connect() as db:return db.execute('SELECT count(*) FROM erp_audit').fetchone()[0]
    def test_product_edit_rename_alias_and_website(self):
        d=self.product('A');d.update(name='Alpha renamed',code='NEW-A',sp=150)
        self.action('products','A',d)
        self.assertEqual(self.product('NEW-A')['name'],'Alpha renamed')
        self.assertEqual(shared.catalog(self.connect)['products'][0][0],'Alpha renamed')
        with self.connect() as db:self.assertEqual(db.execute("SELECT product_code FROM product_aliases WHERE name='Alpha'").fetchone()[0],'NEW-A')
    def test_duplicate_codes_and_conflict_roll_back(self):
        d=self.product('A');d['code']='b';before=self.audit_count()
        with self.assertRaisesRegex(ValueError,'already belongs'):self.action('products','A',d)
        self.assertEqual(self.audit_count(),before);self.assertEqual(self.product('A')['code'],'A')
        s=shared.state(self.connect);s['products'].append({**s['products'][0],'code':s['products'][0]['code'].lower()})
        with self.assertRaisesRegex(ValueError,'unique'):shared.update(self.connect,s)
        old=self.find('products','A');d=old['data'];d['name']='changed';self.action('products','A',d)
        with self.assertRaises(shared.Conflict):self.action('products','A',d,version=old['version'])
    def test_product_delete_archives_and_retains_history(self):
        self.action('products','A',delete=True)
        self.assertFalse(any(r['id']=='A' for r in records.listing(self.connect,'products')['records']))
        self.assertFalse(any(p[3]=='A' for p in shared.catalog(self.connect)['products']))
        with self.connect() as db:
            self.assertIsNotNone(db.execute("SELECT 1 FROM inventory WHERE product_code='A'").fetchone())
            self.assertGreater(db.execute("SELECT count(*) FROM erp_audit WHERE entity='products' AND action='delete'").fetchone()[0],0)
    def txn(self,qty=4):
        s=shared.state(self.connect);next(p for p in s['products'] if p['code']=='A')['made']=qty
        t={'id':'t1','code':'A','type':'Production','qty':qty,'date':'2026-11-05','ref':'studio','rate':None};s['txns']=[t];shared.update(self.connect,s);return t
    def test_transaction_edit_delete_and_negative_stock(self):
        t=self.txn();t['qty']=7;self.action('transactions','t1',t);self.assertEqual(self.product('A')['made'],7)
        self.action('transactions','t1',delete=True);self.assertEqual(self.product('A')['made'],0)
        t=self.txn(4);s=shared.state(self.connect);next(p for p in s['products'] if p['code']=='A').update(open=0,sold=4);shared.update(self.connect,s)
        t['qty']=5;self.action('transactions','t1',t);self.assertEqual(shared.stock(self.product('A')),1)
        before=self.audit_count()
        with self.assertRaisesRegex(ValueError,'negative'):self.action('transactions','t1',delete=True)
        self.assertEqual(self.audit_count(),before);self.assertEqual(self.product('A')['made'],5)
    def test_group_rename_and_deletion(self):
        s=shared.state(self.connect);p=next(p for p in s['products'] if p['code']=='A');p.update(open=0,variants=[{'label':'Red','images':['/assets/r.jpg']}]);shared.update(self.connect,s)
        d=self.product('A');d['code']='C';self.action('products','A',d)
        self.assertEqual(self.product('C-1')['parentCode'],'C');self.assertEqual(self.product('C')['variants'][0]['code'],'C-1')
        self.action('products','C',delete=True);self.assertFalse(any(r['id'].startswith('C') for r in records.listing(self.connect,'products')['records']))
    def test_order_edit_confirm_delete_reconciles_stock(self):
        result=shared.save_order(self.connect,{'customer':{'name':'Customer','phone':'9876543210','address':'Mumbai'},'items':[{'code':'A','quantity':2}]});key=result['orderId'];shared.confirm(self.connect,key)
        self.assertEqual(self.product('A')['sold'],2)
        d=self.find('orders',key)['data'];d['items'][0]['quantity']=3;d['customer']['name']='Updated customer';self.action('orders',key,d)
        self.assertEqual(self.product('A')['sold'],3);self.assertEqual(self.find('orders',key)['data']['total'],300)
        txn=self.find('transactions',key+'-A')
        with self.assertRaisesRegex(ValueError,'confirmed order'):self.action('transactions',txn['id'],delete=True)
        self.action('orders',key,delete=True);self.assertEqual(self.product('A')['sold'],0)
        self.assertEqual(records.listing(self.connect,'orders')['records'],[])
    def test_finance_income_vendor_edit_delete(self):
        book={'version':1,'entries':[{'id':'e','date':'2026-11-05','type':'expense','status':'paid','amount':100,'description':'Beads','bills':[]},{'id':'i','date':'2026-11-05','type':'income','status':'recorded','amount':200,'description':'Sales','bills':[]}],'budgets':{},'vendors':[{'id':'v','name':'Vendor'}]}
        expenses.update(self.connect,self.root,{'revision':0,'book':book},'admin-test')
        for kind,key in [('expenses','e'),('income','i'),('vendors','v')]:
            d=self.find(kind,key)['data'];d['name' if kind=='vendors' else 'description']='Edited';self.action(kind,key,d);self.action(kind,key,delete=True);self.assertEqual(records.listing(self.connect,kind)['records'],[])
    def test_renamed_confirmed_order_still_reconciles(self):
        result=shared.save_order(self.connect,{'customer':{'name':'Customer','phone':'9876543210','address':'Mumbai'},'items':[{'code':'A','quantity':2}]});key=result['orderId'];shared.confirm(self.connect,key)
        d=self.product('A');d['code']='C';self.action('products','A',d)
        self.action('orders',key,delete=True);self.assertEqual(self.product('C')['sold'],0)
    def test_budget_edit_delete(self):
        current=expenses.state(self.connect);current['book']['budgets']={'2026-11':10000};expenses.update(self.connect,self.root,current,'admin-test')
        self.action('budgets','2026-11',{'amount':15000});self.assertEqual(self.find('budgets','2026-11')['data']['amount'],15000)
        self.action('budgets','2026-11',delete=True);self.assertEqual(records.listing(self.connect,'budgets')['records'],[])
    def test_audit_is_immutable_redacted_and_date_filtered(self):
        with self.connect() as db:db.execute("INSERT INTO auth_users VALUES ('a','SECRET-SALT','SECRET-HASH','admin')")
        history=audit.history(self.connect,{'all':['1']});self.assertGreater(history['total'],0)
        raw=json.dumps(history);self.assertNotIn('SECRET',raw);self.assertIn('admin-test',raw)
        with self.connect() as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM erp_audit')
        self.assertEqual(audit.history(self.connect,{'from':['2000-01-01'],'to':['2000-01-02']})['total'],0)
        with self.assertRaises(ValueError):audit.history(self.connect,{'from':['2026-12-01'],'to':['2026-01-01']})
        self.assertIn('Before,After',audit.csv_export(self.connect,{'all':['1']}))
    def test_no_change_save_does_not_fake_deletions(self):
        s=shared.state(self.connect);shared.update(self.connect,s);before=self.audit_count();shared.update(self.connect,shared.state(self.connect));self.assertEqual(self.audit_count(),before)
    def test_last_admin_and_settings(self):
        with self.connect() as db:db.execute("INSERT INTO auth_users VALUES ('admin','x','y','admin')")
        with self.assertRaisesRegex(ValueError,'at least one'):self.action('users','admin',delete=True)
        self.action('settings','city_count',{'count':8});self.assertEqual(team.cities(self.connect)['count'],8)
    def test_http_admin_confirmation_and_history_access(self):
        import backend
        with self.connect() as db:
            for name,role in [('admin','admin'),('manager','manager')]:
                db.execute('INSERT INTO auth_users VALUES (?,?,?,?)',(name,'x','y',role))
                token=name+'-token';digest=__import__('hashlib').sha256(token.encode()).hexdigest();db.execute('INSERT INTO auth_sessions VALUES (?,?,?)',(digest,name,__import__('time').time()+3600))
        with patch.object(backend,'connect',self.connect),patch.object(backend,'ROOT',Path(__file__).parent),patch.object(backend,'DATA_DIR',self.root):
            server=ThreadingHTTPServer(('127.0.0.1',0),backend.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
            def call(path,who='admin',body=None,confirmed=False):
                headers={'Cookie':'kj_session='+who+'-token','Origin':base,'Content-Type':'application/json'}
                if confirmed:headers['X-ERP-Confirmed']='yes'
                req=Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
                try:
                    with urlopen(req) as r:return r.status,r.read()
                except HTTPError as e:return e.code,e.read()
            try:
                # The session cookie name follows auth_store.current.
                self.assertEqual(call('/api/erp/history',who='manager')[0],403)
                self.assertEqual(call('/api/erp/cities',body={'count':4})[0],428)
                self.assertEqual(call('/api/erp/cities',body={'count':4},confirmed=True)[0],200)
                self.assertEqual(call('/api/erp/cities',who='manager',body={'count':4},confirmed=True)[0],403)
                self.assertEqual(call('/erp/records')[0],200)
                self.assertEqual(call('/api/erp/history.csv?all=1')[0],200)
                with self.connect() as db:self.assertEqual(db.execute("SELECT actor FROM erp_audit WHERE source='/api/erp/cities' ORDER BY id DESC LIMIT 1").fetchone()[0],'admin')
            finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
