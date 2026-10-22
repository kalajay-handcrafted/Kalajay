import json,sqlite3,tempfile,unittest
from pathlib import Path
import shared_store as shared
import variant_inventory as variants
import catalogue_excel as excel
import team_store
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.path=self.root/'db'
  with self.connect() as db:db.executescript("CREATE TABLE products(name TEXT PRIMARY KEY,image TEXT,category TEXT,price REAL,sold_out INTEGER,position INTEGER);CREATE TABLE content(key TEXT PRIMARY KEY,value TEXT);INSERT INTO content VALUES('collections','[]');CREATE TABLE orders(id TEXT PRIMARY KEY,created_at TEXT,customer TEXT,items TEXT,total REAL,note TEXT,status TEXT DEFAULT 'new');")
  (self.root/'private').mkdir();(self.root/'index.html').write_text('fixture');shared.migrate(self.connect,self.root,self.root);team_store.initialize(self.connect)
 def connect(self):
  db=sqlite3.connect(self.path);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');return db
 def tearDown(self):self.temp.cleanup()
 def group(self):
  s=shared.state(self.connect);p=shared.record('KJ-TEST-001','Holder','Candle Holders');p.update(cp=100,sp=250,variants=[dict(label='Yellow',images=['/assets/y.jpg']),dict(label='Blue',images=['/assets/b.jpg'])]);s['products']=[p];return shared.update(self.connect,s)
 def request(self,items):return dict(customer=dict(name='Test',phone='9876543210',address='Fixture'),items=items)
 def test_stock_and_catalogue_count_once(self):
  s=self.group();root=next(p for p in s['products'] if p.get('isVariantGroup'));children=[p for p in s['products'] if p.get('parentCode')];yellow=next(p for p in children if p['variantLabel']=='Yellow');blue=next(p for p in children if p['variantLabel']=='Blue');yellow.update(open=5,sp=300);blue.update(open=0,sp=350);s=shared.update(self.connect,s)
  self.assertEqual(sum(shared.stock(p) for p in s['products']),5);self.assertEqual(shared.stock(root),0)
  cat=shared.catalog(self.connect);self.assertEqual(len(cat['products']),1);self.assertEqual([v['soldOut'] for v in cat['variants'][root['code']]],[False,True]);self.assertNotIn(root['code'],cat['soldOut'])
  rows=excel.export_data(self.connect)['rows'];self.assertEqual(len(rows),2);self.assertEqual(sum(r[3] for r in rows),5)
  order=shared.save_order(self.connect,self.request([dict(code=yellow['code'],quantity=2)]));shared.confirm(self.connect,order['orderId']);shared.confirm(self.connect,order['orderId'])
  now={p['code']:p for p in shared.state(self.connect)['products']};self.assertEqual(shared.stock(now[yellow['code']]),3);self.assertEqual(now[blue['code']]['sold'],0);self.assertEqual(now[root['code']]['sold'],0)
  for code in [blue['code'],root['code']]:
   with self.assertRaises(ValueError):shared.save_order(self.connect,self.request([dict(code=code,quantity=1)]))
 def test_legacy_cart_uses_child_order_codes(self):
  s=self.group();root=next(p for p in s['products'] if p.get('isVariantGroup'));children=[p for p in s['products'] if p.get('parentCode')]
  for child in children:child['open']=3
  shared.update(self.connect,s)
  order=shared.save_order(self.connect,self.request([dict(code=root['code'],quantity=3,varieties=[dict(code=children[0]['code'],quantity=1),dict(code=children[1]['code'],quantity=2)])]));shared.confirm(self.connect,order['orderId'])
  with self.connect() as db:self.assertEqual({r[0] for r in db.execute('SELECT product_code FROM order_items')},{p['code'] for p in children})
 def test_migration_backed_up_idempotent_preserves_unallocated_stock(self):
  p=shared.record('LEGACY','Legacy','Bags');p.update(open=7,cp=10,sp=50,variants=[dict(code='LEGACY-1',label='Red',images=['/assets/r.jpg'])])
  with self.connect() as db:db.execute('INSERT INTO products VALUES(?,?,?,?,?,?,?,?,?)',('LEGACY','Legacy','Bags','',50,0,1,1,1));db.execute('INSERT INTO inventory VALUES(?,?)',('LEGACY',json.dumps(p)))
  variants.migrate(self.connect,self.root);variants.migrate(self.connect,self.root);by={p['code']:p for p in shared.state(self.connect)['products']}
  self.assertEqual(len(by),3);self.assertEqual(shared.stock(by['LEGACY']),0);self.assertEqual(shared.stock(by['LEGACY-1']),0);self.assertEqual(shared.stock(by['LEGACY-UNASSIGNED']),7);self.assertTrue((self.root/'before-variety-skus.sqlite3').exists())
 def test_new_options_and_code_stability(self):
  s=self.group();root=next(p for p in s['products'] if p.get('isVariantGroup'));code=root['variants'][0]['code'];next(p for p in s['products'] if p['code']==code)['open']=4;root['variants'].reverse();root['variants'].append(dict(label='Pink',images=['/assets/p.jpg']));s=shared.update(self.connect,s)
  self.assertEqual(shared.stock(next(p for p in s['products'] if p['code']==code)),4);self.assertEqual(len(s['products']),4);root=next(p for p in s['products'] if p.get('isVariantGroup'));root['open']=4
  with self.assertRaises(ValueError):shared.update(self.connect,s)
  root['open']=0;root['variants']=[v for v in root['variants'] if v['code']!=code]
  with self.assertRaises(ValueError):shared.update(self.connect,s)
 def test_upgrade_existing_variety_skus_preserves_colour_stock(self):
  parent=shared.record('OLD','Old holder','Holders');parent['variants']=[dict(code='OLD-1',label='Blue',images=['/assets/b.jpg'])]
  child=shared.record('OLD-1','Old holder - Blue','Holders');child.update(variantOf='OLD',variantLabel='Blue',open=9,made=4,sold=2,cp=50,sp=200)
  with self.connect() as db:
   for p,published in [(parent,1),(child,0)]:
    db.execute('INSERT INTO products VALUES(?,?,?,?,?,?,?,?,?)',(p['code'],p['name'],p['cat'],'',p['sp'],0,1,published,1));db.execute('INSERT INTO inventory VALUES(?,?)',(p['code'],json.dumps(p)))
   db.execute("INSERT INTO shared_meta VALUES('variant_skus_v1',1)")
  variants.migrate(self.connect,self.root)
  now={p['code']:p for p in shared.state(self.connect)['products']};self.assertEqual(len(now),2);self.assertEqual(shared.stock(now['OLD-1']),11);self.assertEqual(shared.stock(now['OLD']),0);self.assertEqual(now['OLD-1']['parentCode'],'OLD');self.assertEqual(shared.catalog(self.connect)['variants']['OLD'][0]['stock'],11)
  self.assertEqual(excel.export_data(self.connect)['rows'][0][0],'OLD-1')
  state=shared.state(self.connect);shared.update(self.connect,state);self.assertEqual(shared.stock(next(p for p in shared.state(self.connect)['products'] if p['code']=='OLD-1')),11)
 def test_marketing_giveaway_stock_cost_and_availability(self):
  s=self.group();child=next(p for p in s['products'] if p.get('parentCode'));code=child['code'];child.update(open=3,cp=100,sp=250);s=shared.update(self.connect,s)
  child=next(p for p in s['products'] if p['code']==code);child['marketing']=2
  s['txns'].insert(0,dict(id='giveaway-1',date='2026-10-22',type='Marketing',code=code,qty=2,purpose='UGC',ref='Fixture creator',rate=25,unitCost=999))
  s=shared.update(self.connect,s);child=next(p for p in s['products'] if p['code']==code)
  self.assertEqual(shared.stock(child),1);self.assertEqual(child['sold'],0);self.assertEqual(child['dmg'],0);self.assertEqual(s['txns'][0]['unitCost'],100);self.assertEqual(s['txns'][0]['rate'],25)
  self.assertEqual(next(r for r in excel.export_data(self.connect)['rows'] if r[0]==code)[3],1)
  # Repeat saves and price edits preserve the original cost snapshot and stock.
  child['cp']=150;s=shared.update(self.connect,s);self.assertEqual(s['txns'][0]['unitCost'],100);self.assertEqual(shared.stock(next(p for p in s['products'] if p['code']==code)),1)
  next(p for p in s['products'] if p['code']==code)['marketing']=3
  s['txns'].insert(0,dict(id='giveaway-2',date='2026-10-22',type='Marketing',code=code,qty=1,purpose='Friends and family',ref='Fixture recipient',rate=0))
  s=shared.update(self.connect,s);self.assertEqual(s['txns'][0]['unitCost'],150)
  option=shared.catalog(self.connect)['variants']['KJ-TEST-001'][0];self.assertEqual(option['stock'],0);self.assertTrue(option['soldOut'])
  with self.assertRaises(ValueError):shared.save_order(self.connect,self.request([dict(code=code,quantity=1)]))
  # An older client omitting the optional counter cannot silently restore stock.
  for p in s['products']:p.pop('marketing',None)
  s=shared.update(self.connect,s);self.assertEqual(shared.stock(next(p for p in s['products'] if p['code']==code)),0)
 def test_marketing_validation_and_overdraw(self):
  s=self.group();child=next(p for p in s['products'] if p.get('parentCode'));child['open']=1;s=shared.update(self.connect,s);code=child['code']
  import copy
  original=copy.deepcopy(s)
  for purpose,qty,ref,rate in [('Invalid',1,'Creator',0),('UGC',2,'Creator',0),('UGC',1,'',0),('UGC',1,'Creator',-1)]:
   attempt=copy.deepcopy(original);next(p for p in attempt['products'] if p['code']==code)['marketing']=qty
   attempt['txns'].insert(0,dict(id='bad',date='2026-10-22',type='Marketing',code=code,qty=qty,purpose=purpose,ref=ref,rate=rate))
   with self.assertRaises(ValueError):shared.update(self.connect,attempt)
  attempt=copy.deepcopy(original);next(p for p in attempt['products'] if p['code']==code)['marketing']=1
  with self.assertRaises(ValueError):shared.update(self.connect,attempt)
  self.assertEqual(shared.stock(next(p for p in shared.state(self.connect)['products'] if p['code']==code)),1)
if __name__=='__main__':unittest.main()
