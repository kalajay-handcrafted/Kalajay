"""Shared product, ERP and website data; product_code is the stable key."""
import json, re, sqlite3, uuid, math
import team_store as team
from datetime import datetime, timezone

NUMBERS=('open','purch','made','sold','dmg','reorder','cp','sp','mrp','gst')
ALIASES={
 'Pearl Beaded Ring/Earring Box':'Pearl Beaded Ring & Earring Box',
 'Pearl Beaded Round Watch/Accessory Box':'Pearl Beaded Round Watch Box',
 'Beaded Desk Organiser Baskets':'Beaded Desk Organiser Basket Set',
 'Pearl Beaded Mini Pouch with Flower Charm':'Pearl Beaded Mini Pouch, Flower Charm',
 'Pearl Beaded Tealight Holder Set':'Pearl Beaded Tealight Holder Set of 2',
 'Lilac Beaded Tealight Holder Set':'Lilac Beaded Tealight Holder Set of 2',
 'Crochet Flower Bookmark/Bag Charm':'Crochet Flower Bookmark / Bag Charm',
 'Crochet Chicken Bookmarks':'Crochet Chicken Bookmark',
 'Crochet Flower Bookmarks':'Crochet Flower Bookmark Set of 3',
 'Crystal Beaded Heart Charm Collection':'Crystal Beaded Heart Charm',
}
def norm(s):return ' '.join(s.strip().lower().split())
def record(code,name,cat,unit='pcs'):
 return dict(code=code,name=name,cat=cat,unit=unit,hsn='NA',upd='NA',sno=0,**{k:0 for k in NUMBERS})
def stock(p):return p['open']+p['purch']+p['made']-p['sold']-p['dmg']+p.get('adjustment',0)
def migrate(connect,root,erp_root):
 with connect() as db:
  done=db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='shared_meta'").fetchone()
 if not done:
  # Online SQLite backup preserves the existing catalogue, website content, and customer orders.
  with connect() as src, sqlite3.connect(__import__('pathlib').Path(src.execute('PRAGMA database_list').fetchone()[2]).parent/'before-shared-migration.sqlite3') as dest: src.backup(dest)
  with connect() as db:
   db.execute('BEGIN IMMEDIATE')
   legacy=[dict(r) for r in db.execute('SELECT * FROM products')]
   db.execute('ALTER TABLE products RENAME TO website_products_legacy')
   for sql in [
    'CREATE TABLE shared_meta (key TEXT PRIMARY KEY,value INTEGER NOT NULL)',
    '''CREATE TABLE products (product_code TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, image TEXT NOT NULL DEFAULT '', price REAL NOT NULL CHECK(price>=0), sold_out INTEGER NOT NULL DEFAULT 0, position INTEGER NOT NULL, published INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1)''',
    'CREATE TABLE inventory (product_code TEXT PRIMARY KEY REFERENCES products(product_code), record TEXT NOT NULL)',
    'CREATE TABLE inventory_transactions (id TEXT PRIMARY KEY, product_code TEXT NOT NULL REFERENCES products(product_code), record TEXT NOT NULL)',
    '''CREATE TABLE order_items (order_id TEXT NOT NULL REFERENCES orders(id), product_code TEXT NOT NULL REFERENCES products(product_code), quantity INTEGER NOT NULL CHECK(quantity>0), unit_price REAL NOT NULL, name_snapshot TEXT NOT NULL, PRIMARY KEY(order_id,product_code))''',
    'CREATE TABLE product_aliases (name TEXT PRIMARY KEY,product_code TEXT NOT NULL REFERENCES products(product_code))']:
    db.execute(sql)
   db.execute("INSERT INTO shared_meta VALUES ('revision',1)")
   db.execute("INSERT INTO shared_meta VALUES ('browser_imported',0)")
   seed=json.loads((root/'erp-seed.json').read_text())
   names={}
   for i,(code,name,cat,unit) in enumerate(seed):
    p=record(code,name,cat,unit);p['sno']=i+1
    db.execute('INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?)',(code,name,cat,'',0,0,1000+i,0,1))
    db.execute('INSERT INTO inventory VALUES (?,?)',(code,json.dumps(p)))
    names[norm(name)]=code
   used=set()
   for i,p in enumerate(legacy):
    code=names.get(norm(ALIASES.get(p['name'],p['name'])))
    if code in used:code=None
    if not code:
     code='KJ-WEB-'+str(i+1).zfill(3)
     db.execute('INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?)',(code,p['name'],p['category'],p['image'],p['price'],p['sold_out'],p['position'],1,1))
     inv=record(code,p['name'],p['category']);inv['sp']=p['price'];inv['sno']=len(seed)+i+1
     db.execute('INSERT INTO inventory VALUES (?,?)',(code,json.dumps(inv)))
    else:
     db.execute('UPDATE products SET name=?,category=?,image=?,price=?,sold_out=?,position=?,published=1 WHERE product_code=?',(p['name'],p['category'],p['image'],p['price'],p['sold_out'],p['position'],code))
     inv=json.loads(db.execute('SELECT record FROM inventory WHERE product_code=?',(code,)).fetchone()[0]);inv.update(name=p['name'],cat=p['category'],sp=p['price'])
     db.execute('UPDATE inventory SET record=? WHERE product_code=?',(json.dumps(inv),code))
    used.add(code)
    db.execute('INSERT INTO product_aliases VALUES (?,?)',(p['name'],code))
   for order in db.execute('SELECT * FROM orders').fetchall():
    for item in json.loads(order['items']):
     row=db.execute('SELECT product_code FROM product_aliases WHERE name=?',(item['name'],)).fetchone()
     if not row:raise ValueError('Existing order references an unknown product; migration rolled back.')
     db.execute('INSERT INTO order_items VALUES (?,?,?,?,?)',(order['id'],row[0],item['quantity'],item['unitPrice'],item['name']))
 with connect() as db:
  db.execute('INSERT OR REPLACE INTO content VALUES (?,?)',('erp_homepage',(erp_root/'index.html').read_text()))

def catalog(connect):
 with connect() as db:
  rows=db.execute('SELECT * FROM products WHERE active=1 AND published=1 ORDER BY position').fetchall()
  cats=json.loads(db.execute("SELECT value FROM content WHERE key='collections'").fetchone()[0])
  for r in rows:
   if r['category'] not in [c[0] for c in cats]:cats.append([r['category'],'Handcrafted pieces','assets/kalajay-brand.png'])
  return {'cityCount':db.execute("SELECT value FROM shared_meta WHERE key='city_count'").fetchone()[0], 'memberCount':team.count(db), 'collections':cats,'products':[[r['name'],r['image'],r['category'],r['product_code']] for r in rows], 'prices':{r['product_code']:r['price'] for r in rows},'soldOut':[r['product_code'] for r in rows if r['sold_out']], 'defaultPrice':500}

def state(connect):
 with connect() as db:
  products=[json.loads(r[0]) for r in db.execute('SELECT i.record FROM inventory i JOIN products p USING(product_code) WHERE p.active=1 ORDER BY p.position')]
  for i,p in enumerate(products):p['sno']=i+1
  orders=[]
  for r in db.execute('SELECT * FROM orders ORDER BY created_at DESC'):
   orders.append(dict(id=r['id'],date=r['created_at'][:10],customer=json.loads(r['customer']),items=[dict(x) for x in db.execute('SELECT * FROM order_items WHERE order_id=?',(r['id'],))],total=r['total'],status=r['status'],note=r['note']))
  return dict(products=products,txns=[json.loads(r[0]) for r in db.execute('SELECT record FROM inventory_transactions ORDER BY rowid DESC')],orders=orders,revision=db.execute("SELECT value FROM shared_meta WHERE key='revision'").fetchone()[0],browserImported=bool(db.execute("SELECT value FROM shared_meta WHERE key='browser_imported'").fetchone()[0]))

class Conflict(ValueError):pass

def update(connect,data):
 if not isinstance(data,dict) or not isinstance(data.get('products'),list) or not isinstance(data.get('txns'),list):raise ValueError('Invalid ERP data.')
 if len(data['products'])>10000 or len(data['txns'])>100000:raise ValueError('Too many records.')
 seen=set()
 for p in data['products']:
  if not isinstance(p,dict) or not isinstance(p.get('code'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',p['code']) or p['code'] in seen:raise ValueError('Product codes must be unique and contain only letters, numbers, hyphens or underscores.')
  seen.add(p['code'])
  for k in ('name','cat','unit','hsn','upd'):
   if not isinstance(p.get(k),str) or len(p[k])>300:raise ValueError('Invalid product '+k)
  if not p['name'].strip():raise ValueError('Product name required.')
  for k in NUMBERS:
   if type(p.get(k)) not in (int,float) or not math.isfinite(p[k]) or not 0<=p[k]<=1e9:raise ValueError('Invalid non-negative '+k)
  if type(p.get('adjustment',0)) not in (int,float) or not math.isfinite(p.get('adjustment',0)):raise ValueError('Invalid inventory adjustment.')
  if stock(p)<0:raise ValueError('Stock cannot be negative for '+p['code'])
 txn_seen=set()
 for t in data['txns']:
  if not isinstance(t,dict) or not isinstance(t.get('id'),str) or t['id'] in txn_seen or len(t['id'])>100:raise ValueError('Invalid transaction ID.')
  txn_seen.add(t['id'])
  if not isinstance(t.get('code'),str) or t.get('type') not in ('Production','Purchase','Sale','Damage','Adjustment') or type(t.get('qty')) not in (int,float) or not math.isfinite(t['qty']) or (t['qty']==0 if t.get('type')=='Adjustment' else t['qty']<=0):raise ValueError('Invalid stock transaction.')
 with connect() as db:
  db.execute('BEGIN IMMEDIATE')
  revision=db.execute("SELECT value FROM shared_meta WHERE key='revision'").fetchone()[0]
  if data.get('revision')!=revision:raise Conflict('Data changed in another session. Refresh ERP before saving again.')
  # Soft-delete keeps historical order and transaction links intact.
  if not data.get('importLegacy'):db.execute('UPDATE products SET active=0')
  for i,p in enumerate(data['products']):
   code=p['code'];old=db.execute('SELECT * FROM products WHERE product_code=?',(code,)).fetchone()
   if old:
    db.execute('UPDATE products SET name=?,category=?,price=?,active=1 WHERE product_code=?',(p['name'],p['cat'],p['sp'],code))
   else:
    db.execute('INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?)',(code,p['name'],p['cat'],'',p['sp'],0,2000+i,1,1))
   old_inv=db.execute('SELECT record FROM inventory WHERE product_code=?',(code,)).fetchone()
   # Availability follows inventory once inventory quantities are actually changed.
   if old_inv and any(p[k]!=json.loads(old_inv[0]).get(k,0) for k in ('open','purch','made','sold','dmg')):
    db.execute('UPDATE products SET sold_out=? WHERE product_code=?',(int(stock(p)<=0),code))
   db.execute('INSERT OR REPLACE INTO inventory VALUES (?,?)',(code,json.dumps(p)))
  for t in data['txns']:
   if not db.execute('SELECT 1 FROM products WHERE product_code=?',(t['code'],)).fetchone():raise ValueError('Transaction has an unknown product code.')
   prior=db.execute('SELECT record FROM inventory_transactions WHERE id=?',(t['id'],)).fetchone()
   if prior and json.loads(prior[0])!=t:raise ValueError('Existing stock transactions cannot be rewritten.')
   db.execute('INSERT OR IGNORE INTO inventory_transactions VALUES (?,?,?)',(t['id'],t['code'],json.dumps(t)))
  if data.get('importLegacy'):db.execute("UPDATE shared_meta SET value=1 WHERE key='browser_imported'")
  db.execute("UPDATE shared_meta SET value=value+1 WHERE key='revision'")
 return state(connect)

def save_order(connect,data):
 if not isinstance(data,dict):raise ValueError('Invalid order.')
 customer=data.get('customer',{});clean={}
 for key,limit in [('name',150),('phone',40),('address',1000)]:
  v=customer.get(key) if isinstance(customer,dict) else None
  if not isinstance(v,str) or not v.strip() or len(v)>limit:raise ValueError('Please enter a valid '+key)
  clean[key]=v.strip()
 if not 7<=sum(c.isdigit() for c in clean['phone'])<=15:raise ValueError('Please enter a valid phone number.')
 items=data.get('items');note=data.get('note','')
 if not isinstance(items,list) or not 1<=len(items)<=100:raise ValueError('Add products to your order.')
 if not isinstance(note,str) or len(note)>2000:raise ValueError('Invalid notes.')
 with connect() as db:
  db.execute('BEGIN IMMEDIATE')
  saved=[];seen=set();total=0
  for item in items:
   if not isinstance(item,dict) or not isinstance(item.get('code'),str):raise ValueError('Product code is required. Refresh the page.')
   code=item['code'];qty=item.get('quantity')
   if code in seen or type(qty)is not int or not 1<=qty<=100:raise ValueError('Invalid quantity or duplicate product.')
   seen.add(code)
   p=db.execute('SELECT * FROM products WHERE product_code=? AND active=1 AND published=1',(code,)).fetchone()
   if not p or p['sold_out']:raise ValueError('Product unavailable: '+code)
   saved.append(dict(code=code,name=p['name'],quantity=qty,unitPrice=p['price']));total+=qty*p['price']
  oid='KJ-'+uuid.uuid4().hex[:16].upper()
  db.execute('INSERT INTO orders (id,created_at,customer,items,total,note) VALUES (?,?,?,?,?,?)',(oid,datetime.now(timezone.utc).isoformat(),json.dumps(clean),json.dumps(saved),total,note))
  db.executemany('INSERT INTO order_items VALUES (?,?,?,?,?)',[(oid,i['code'],i['quantity'],i['unitPrice'],i['name']) for i in saved])
 return dict(orderId=oid,total=total,status='new',currency='INR')

def confirm(connect,oid):
 with connect() as db:
  db.execute('BEGIN IMMEDIATE')
  order=db.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
  if not order:raise ValueError('Order not found.')
  if order['status']=='confirmed':return {'status':'confirmed'}
  for item in db.execute('SELECT * FROM order_items WHERE order_id=?',(oid,)).fetchall():
   p=json.loads(db.execute('SELECT record FROM inventory WHERE product_code=?',(item['product_code'],)).fetchone()[0])
   if stock(p)<item['quantity']:raise ValueError('Insufficient stock for '+item['product_code']+'. Record production or stock-in first.')
   p['sold']+=item['quantity'];p['upd']=datetime.now().date().isoformat()
   db.execute('UPDATE inventory SET record=? WHERE product_code=?',(json.dumps(p),p['code']))
   db.execute('UPDATE products SET sold_out=? WHERE product_code=?',(int(stock(p)<=0),p['code']))
   t=dict(id=oid+'-'+p['code'],date=p['upd'],type='Sale',code=p['code'],qty=item['quantity'],ref=oid,rate=item['unit_price'])
   db.execute('INSERT INTO inventory_transactions VALUES (?,?,?)',(t['id'],p['code'],json.dumps(t)))
  db.execute("UPDATE orders SET status='confirmed' WHERE id=?",(oid,))
  db.execute("UPDATE shared_meta SET value=value+1 WHERE key='revision'")
 return {'status':'confirmed'}
