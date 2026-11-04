"""Admin record editing with concurrency checks and inventory reconciliation."""
import copy
import hashlib
import json
import math
import re
from contextlib import contextmanager
from datetime import date
import shared_store as shared
import expense_store as expenses
import team_store as team

KINDS=('products','transactions','orders','expenses','income','vendors','budgets','members','settings','users')

def version(record):
    return hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest()

def pack(key, record):
    return {'id':key,'version':version(record),'data':record}

def listing(connect,kind):
    if kind not in KINDS:raise ValueError('Unknown record type.')
    with connect() as db:
        if kind=='products':
            records=[pack(r['product_code'],json.loads(r['record'])) for r in db.execute('SELECT i.* FROM inventory i JOIN products p USING(product_code) WHERE p.active=1 ORDER BY p.name COLLATE NOCASE')]
        elif kind=='transactions':
            records=[pack(r['id'],json.loads(r['record'])) for r in db.execute('SELECT * FROM inventory_transactions ORDER BY rowid DESC')]
        elif kind=='orders':
            records=[]
            for r in db.execute('SELECT * FROM orders ORDER BY created_at DESC'):
                d=dict(r);d['customer']=json.loads(d['customer']);d['items']=json.loads(d['items']);records.append(pack(d['id'],d))
        elif kind in ('expenses','income','vendors','budgets'):
            book=json.loads(db.execute('SELECT payload FROM expense_book WHERE id=1').fetchone()[0])
            if kind=='budgets':return {'records':[pack(k,{'amount':v}) for k,v in book.get('budgets',{}).items()]}
            records=[pack(r['id'],r) for r in book.get('vendors',[]) ] if kind=='vendors' else [pack(r['id'],r) for r in book['entries'] if r['type']==('expense' if kind=='expenses' else 'income')]
        elif kind=='members':
            records=[pack(r['id'],{**json.loads(r['details']),'id':r['id'],'joined_on':r['joined_on'],'active':bool(r['active']),'existing_member':bool(r['existing_member'])}) for r in db.execute('SELECT * FROM team_members ORDER BY name')]
        elif kind=='settings':
            records=[pack(r['key'],{'count':r['value']}) for r in db.execute("SELECT * FROM shared_meta WHERE key IN ('city_count','team_baseline')")]
        else:
            records=[pack(r['username'],dict(r)) for r in db.execute('SELECT username,role FROM auth_users ORDER BY username')]
    return {'records':records}

class NestedDB:
    """Reuse the outer atomic transaction in existing validated save routines."""
    def __init__(self,db):self.db=db
    def execute(self,sql,*args):
        if sql.strip().upper().startswith('BEGIN'):return self.db.execute('SELECT 1')
        return self.db.execute(sql,*args)
    def __getattr__(self,name):return getattr(self.db,name)

def same_connection(db):
    @contextmanager
    def connect():yield NestedDB(db)
    return connect

def bump(db):db.execute("UPDATE shared_meta SET value=value+1 WHERE key='revision'")

def stock_changes(db, movements):
    products={}
    for txn,sign in movements:
        if txn['code'] not in products:
            row=db.execute('SELECT record FROM inventory WHERE product_code=?',(txn['code'],)).fetchone()
            if not row:raise ValueError('Product no longer exists.')
            products[txn['code']]=json.loads(row[0])
        p=products[txn['code']]
        key={'Production':'made','Purchase':'purch','Sale':'sold','Damage':'dmg','Marketing':'marketing','Adjustment':'adjustment'}[txn['type']]
        p[key]=p.get(key,0)+sign*txn['qty']
    for p in products.values():
        if any(p.get(k,0)<0 for k in ('made','purch','sold','dmg','marketing')) or shared.stock(p)<0:raise ValueError('This correction would make stock or movement totals negative. Correct the dependent movements first.')
        db.execute('UPDATE inventory SET record=? WHERE product_code=?',(json.dumps(p),p['code']))
        db.execute('UPDATE products SET sold_out=? WHERE product_code=?',(int(shared.stock(p)<=0),p['code']))

def stock_delta(db,txn,sign):stock_changes(db,[(txn,sign)])

def validate_txn(db,t):
    if not isinstance(t,dict) or t.get('type') not in ('Production','Purchase','Sale','Damage','Marketing','Adjustment'):raise ValueError('Choose a valid stock movement type.')
    if type(t.get('qty')) not in (int,float) or not math.isfinite(t['qty']) or (t['qty']==0 if t['type']=='Adjustment' else t['qty']<=0):raise ValueError('Enter a valid quantity.')
    date.fromisoformat(t.get('date',''))
    row=db.execute('SELECT i.record FROM inventory i JOIN products p USING(product_code) WHERE product_code=? AND active=1',(t.get('code'),)).fetchone()
    if not row or json.loads(row[0]).get('isVariantGroup'):raise ValueError('Choose an active stock-bearing product / variety.')
    for key in ('rate','unitCost'):
        if t.get(key) is not None and (type(t[key]) not in (int,float) or not math.isfinite(t[key]) or not 0<=t[key]<=1e9):raise ValueError('Invalid '+key)
    if not isinstance(t.get('ref',''),str) or len(t.get('ref',''))>300:raise ValueError('Invalid reference.')
    if t['type']=='Marketing' and (t.get('purpose') not in ('UGC','Friends and family','Samples','Other marketing') or not t.get('ref','').strip()):raise ValueError('Choose a giveaway category and recipient.')

def rename_product(db,old,new):
    if not isinstance(new,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',new):raise ValueError('Use letters, numbers, hyphens or underscores in the product code.')
    mappings={old:new}
    for r in db.execute('SELECT product_code,record FROM inventory'):
        if json.loads(r['record']).get('parentCode')==old:
            mappings[r['product_code']]=new+r['product_code'][len(old):]
    existing={r[0].casefold() for r in db.execute('SELECT product_code FROM products') if r[0] not in mappings}
    if len({v.casefold() for v in mappings.values()})!=len(mappings) or any(v.casefold() in existing for v in mappings.values()):raise ValueError('Product code already belongs to a different product. Choose a unique code.')
    for a,b in mappings.items():
        shared.rename_product_code(db,a,b,None)
    for r in db.execute('SELECT product_code,record FROM inventory').fetchall():
        p=json.loads(r['record']);changed=False
        if p.get('parentCode') in mappings:p['parentCode']=mappings[p['parentCode']];changed=True
        for v in p.get('variants',[]):
            if v.get('code') in mappings:v['code']=mappings[v['code']];changed=True
        if changed:db.execute('UPDATE inventory SET record=? WHERE product_code=?',(json.dumps(p),r['product_code']))
    for r in db.execute('SELECT id,items FROM orders').fetchall():
        items=json.loads(r['items']);changed=False
        for p in items:
            if p.get('code') in mappings:p['code']=mappings[p['code']];changed=True
            for v in p.get('varieties',[]):
                if v.get('code') in mappings:v['code']=mappings[v['code']];changed=True
        if changed:db.execute('UPDATE orders SET items=? WHERE id=?',(json.dumps(items),r['id']))
    return mappings

def apply(connect,root,request,username):
    if not isinstance(request,dict) or request.get('action') not in ('edit','delete'):raise ValueError('Choose edit or delete.')
    kind=request.get('kind');key=request.get('id');delete=request['action']=='delete'
    if kind not in KINDS or not isinstance(key,str):raise ValueError('Choose a record.')
    data=copy.deepcopy(request.get('data'))
    if not delete and not isinstance(data,dict):raise ValueError('Record fields required.')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE');nested=same_connection(db)
        if 'revision' in request and request['revision']!=db.execute("SELECT value FROM shared_meta WHERE key='revision'").fetchone()[0]:raise shared.Conflict('Inventory changed on another device. Reload before editing.')
        old=next((r for r in listing(nested,kind)['records'] if r['id']==key),None)
        if not old:raise ValueError('Record no longer exists. Reload the list.')
        if request.get('version')!=old['version']:raise shared.Conflict('This record changed on another device. Reload before editing.')
        prior=old['data']
        if kind=='products':
            if prior.get('parentCode') and (delete or data.get('code')!=key):raise ValueError('Remove or rename a variety through its parent product, so colour links remain consistent.')
            if delete:
                codes=[key]+[r[0] for r in db.execute("SELECT product_code FROM inventory WHERE json_extract(record,'$.parentCode')=?",(key,))]
                db.executemany('UPDATE products SET active=0 WHERE product_code=?',[(c,) for c in codes]);bump(db)
            else:
                new=data.get('code',key)
                mappings=rename_product(db,key,new) if new!=key else {}
                if mappings:
                    for v in data.get('variants',[]):v['code']=mappings.get(v.get('code'),v.get('code'))
                current=shared.state(nested);updated=[]
                for p in current['products']:
                    updated.append({**p,**data,'code':new} if p['code']==new else p)
                shared.update(nested,{'products':updated,'txns':current['txns'],'revision':current['revision']})
        elif kind=='transactions':
            # Linked confirmed-order sales must be changed through the order record.
            if db.execute("SELECT 1 FROM orders WHERE id=? AND status='confirmed'",(prior.get('ref'),)).fetchone():raise ValueError('This movement belongs to a confirmed order. Edit or delete that order to keep stock and sales aligned.')
            if not delete:
                if data.get('id')!=key:raise ValueError('Transaction ID cannot change.')
                validate_txn(db,data)
            stock_changes(db,[(prior,-1)]+([] if delete else [(data,1)]))
            if delete:db.execute('DELETE FROM inventory_transactions WHERE id=?',(key,))
            else:
                db.execute('UPDATE inventory_transactions SET product_code=?,record=? WHERE id=?',(data['code'],json.dumps(data),key))
            bump(db)
        elif kind=='orders':
            if not delete:
                if data.get('id')!=key:raise ValueError('Order ID cannot change.')
                if data.get('status') not in ('new','confirmed','cancelled'):raise ValueError('Choose new, confirmed or cancelled status.')
                if not isinstance(data.get('customer'),dict) or any(not isinstance(data['customer'].get(k),str) or not data['customer'][k].strip() or len(data['customer'][k])>1000 for k in ('name','phone','address')):raise ValueError('Customer name, phone and address are required.')
                if not isinstance(data.get('note',''),str) or len(data.get('note',''))>2000:raise ValueError('Invalid order note.')
                if not isinstance(data.get('items'),list) or not 1<=len(data['items'])<=200:raise ValueError('Add at least one order item.')
                codes=set();total=0
                for item in data['items']:
                    if not isinstance(item,dict):raise ValueError('Invalid order item.')
                    code=item.get('code');qty=item.get('quantity');price=item.get('unitPrice')
                    if code in codes or type(qty) is not int or not 1<=qty<=100000 or type(price) not in (int,float) or not math.isfinite(price) or not 0<=price<=1e9:raise ValueError('Order item codes must be unique, with valid quantities and prices.')
                    if not db.execute('SELECT 1 FROM products WHERE product_code=?',(code,)).fetchone():raise ValueError('Unknown product in order.')
                    if not isinstance(item.get('name'),str) or not item['name'].strip():raise ValueError('Each order item needs a name.')
                    codes.add(code);total+=qty*price
                try:__import__('datetime').datetime.fromisoformat(data.get('created_at','').replace('Z','+00:00'))
                except (ValueError,TypeError):raise ValueError('Use a valid order date and time.')
            # Reverse the exact sale movements generated by the previous confirmation.
            if prior['status']=='confirmed':
                for r in db.execute('SELECT id,record FROM inventory_transactions WHERE json_extract(record,\'$.ref\')=?',(key,)).fetchall():
                    transaction=json.loads(r['record'])
                    if r['id'].startswith(key+'-') and transaction['type']=='Sale':
                        stock_delta(db,transaction,-1);db.execute('DELETE FROM inventory_transactions WHERE id=?',(r['id'],))
            db.execute('DELETE FROM order_items WHERE order_id=?',(key,))
            if delete:db.execute('DELETE FROM orders WHERE id=?',(key,))
            else:
                db.execute('UPDATE orders SET created_at=?,customer=?,items=?,total=?,note=?,status=? WHERE id=?',(data['created_at'],json.dumps(data['customer']),json.dumps(data['items']),total,data.get('note',''),'new' if data['status']=='confirmed' else data['status'],key))
                db.executemany('INSERT INTO order_items VALUES (?,?,?,?,?)',[(key,p['code'],p['quantity'],p['unitPrice'],p['name']) for p in data['items']])
                if data['status']=='confirmed':shared.confirm(nested,key)
            bump(db)
        elif kind in ('expenses','income','vendors','budgets'):
            current=expenses.state(nested);field='vendors' if kind=='vendors' else 'entries'
            if not delete and kind!='budgets' and data.get('id')!=key:raise ValueError('Record ID cannot change.')
            if kind in ('expenses','income') and not delete and data.get('type')!=prior['type']:raise ValueError('Keep the income / expense type unchanged.')
            if kind=='budgets':
                if delete:current['book']['budgets'].pop(key,None)
                else:current['book']['budgets'][key]=data.get('amount')
            else:current['book'][field]=[data if r['id']==key else r for r in current['book'].get(field,[]) if not(delete and r['id']==key)]
            expenses.update(nested,root,current,username)
        elif kind=='members':
            if delete:db.execute('DELETE FROM team_members WHERE id=?',(key,))
            else:
                data['id']=key;team.add(nested,data,root)
        elif kind=='settings':
            if delete:raise ValueError('Settings cannot be deleted; edit the count instead.')
            count=data.get('count')
            if type(count) is not int or not 0<=count<=100000:raise ValueError('Enter a whole count between 0 and 100000.')
            if key=='team_baseline' and count<db.execute('SELECT count(*) FROM team_members WHERE existing_member=1').fetchone()[0]:raise ValueError('Baseline cannot be below the registered existing-member count.')
            db.execute('UPDATE shared_meta SET value=? WHERE key=?',(count,key))
        else:
            role=data.get('role') if not delete else None
            if not delete and (data.get('username')!=key or role not in ('admin','manager')):raise ValueError('Keep the username unchanged and choose admin or manager.')
            if prior['role']=='admin' and (delete or role!='admin') and db.execute("SELECT count(*) FROM auth_users WHERE role='admin'").fetchone()[0]<=1:raise ValueError('Keep at least one administrator account.')
            if delete:
                db.execute('DELETE FROM auth_sessions WHERE username=?',(key,));db.execute('DELETE FROM auth_users WHERE username=?',(key,))
            else:db.execute('UPDATE auth_users SET role=? WHERE username=?',(role,key))
    return {'ok':True}
