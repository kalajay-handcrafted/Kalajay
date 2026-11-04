"""Atomic, append-only ERP audit history in the shared database."""
import contextvars
import csv
import io
import json
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

actor = contextvars.ContextVar('erp_actor', default='System')
request_id = contextvars.ContextVar('erp_request', default='startup')
source = contextvars.ContextVar('erp_source', default='system')
TABLES = ('products','inventory','inventory_transactions','orders','order_items',
          'product_aliases','expense_book','team_members','team_member_images','shared_meta','auth_users')

def configure(db):
    db.create_function('erp_actor', 0, actor.get)
    db.create_function('erp_request', 0, request_id.get)
    db.create_function('erp_source', 0, source.get)

def initialize(connect, root):
    with connect() as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='erp_audit'").fetchone()
        if not exists:
            backup = Path(root) / 'before-admin-records.sqlite3'
            if not backup.exists():
                with sqlite3.connect(backup) as dest:
                    db.backup(dest)
                backup.chmod(0o600)
        db.executescript('''
        CREATE TABLE IF NOT EXISTS erp_audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
          actor TEXT NOT NULL, request_id TEXT NOT NULL, source TEXT NOT NULL,
          entity TEXT NOT NULL, action TEXT NOT NULL,
          before_json TEXT, after_json TEXT
        );
        CREATE INDEX IF NOT EXISTS erp_audit_at ON erp_audit(at,id);
        CREATE TRIGGER IF NOT EXISTS erp_audit_no_update BEFORE UPDATE ON erp_audit
          BEGIN SELECT RAISE(ABORT,'Action history cannot be edited.'); END;
        CREATE TRIGGER IF NOT EXISTS erp_audit_no_delete BEFORE DELETE ON erp_audit
          BEGIN SELECT RAISE(ABORT,'Action history cannot be deleted.'); END;
        ''')
        for table in TABLES:
            columns = [r['name'] for r in db.execute('PRAGMA table_info("'+table+'")')]
            if not columns:
                continue
            # Never retain passwords, password hashes, salts, session tokens or bill binaries.
            columns = [c for c in columns if c not in ('salt','password_hash')]
            def snapshot(prefix):
                return 'json_object('+','.join("'"+c+"',"+prefix+'."'+c+'"' for c in columns)+')'
            for operation in ('INSERT','UPDATE','DELETE'):
                before = 'NULL' if operation=='INSERT' else snapshot('OLD')
                after = 'NULL' if operation=='DELETE' else snapshot('NEW')
                condition = ' WHEN '+before+' <> '+after if operation=='UPDATE' else ''
                if table=='shared_meta':
                    condition = (' WHEN NEW.key IN (\'city_count\',\'team_baseline\')' if operation=='INSERT' else
                                 ' WHEN OLD.key IN (\'city_count\',\'team_baseline\')' + (' AND '+before+' <> '+after if operation=='UPDATE' else ''))
                action="CASE WHEN OLD.active=1 AND NEW.active=0 THEN 'delete' ELSE 'update' END" if table=='products' and operation=='UPDATE' else "'"+operation.lower()+"'"
                db.execute(f'''CREATE TRIGGER IF NOT EXISTS audit_{table}_{operation.lower()}
                    AFTER {operation} ON "{table}"{condition} BEGIN
                    INSERT INTO erp_audit(at,actor,request_id,source,entity,action,before_json,after_json)
                    VALUES(strftime('%Y-%m-%dT%H:%M:%fZ','now'),erp_actor(),erp_request(),erp_source(),
                    '{table}',{action},{before},{after}); END''')

def history(connect, query):
    zone = ZoneInfo('Asia/Kolkata')
    today = datetime.now(zone).date()
    try:
        days = int(query.get('days',['30'])[0])
        start = date.fromisoformat(query['from'][0]) if query.get('from',[''])[0] else today-timedelta(days=max(days-1,0))
        end = date.fromisoformat(query['to'][0]) if query.get('to',[''])[0] else today
        if start>end or days<0:
            raise ValueError()
        low = datetime.combine(start,time.min,zone).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
        high = datetime.combine(end+timedelta(days=1),time.min,zone).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
        offset = max(0,int(query.get('offset',['0'])[0]))
    except (ValueError,OverflowError):
        raise ValueError('Choose a valid date range.')
    all_time = query.get('all',[''])[0]=='1'
    where, args = ('1=1',[]) if all_time else ('at>=? AND at<?',[low,high])
    with connect() as db:
        total=db.execute('SELECT count(*) FROM erp_audit WHERE '+where,args).fetchone()[0]
        rows=[dict(r) for r in db.execute('SELECT * FROM erp_audit WHERE '+where+' ORDER BY id DESC LIMIT 500 OFFSET ?',[*args,offset])]
    return {'rows':rows,'total':total,'offset':offset,'nextOffset':offset+len(rows), 'timezone':'Asia/Kolkata'}

def csv_export(connect, query):
    out=io.StringIO();writer=csv.writer(out)
    writer.writerow(['Time (UTC)','Admin','Action','Record type','Request','Source','Before','After'])
    q=dict(query);q['offset']=['0']
    while True:
        page=history(connect,q)
        for r in page['rows']:
            # Prevent spreadsheet formula execution, including values edited by customers.
            values=[r[k] or '' for k in ('at','actor','action','entity','request_id','source','before_json','after_json')]
            writer.writerow(["'"+v if v.startswith(('=','+','-','@','\t','\r')) else v for v in values])
        if page['nextOffset']>=page['total']:break
        q['offset']=[str(page['nextOffset'])]
    return '\ufeff'+out.getvalue()


def event(connect, entity, action, before=None, after=None):
    with connect() as db:
        db.execute("INSERT INTO erp_audit(at,actor,request_id,source,entity,action,before_json,after_json) VALUES(strftime('%Y-%m-%dT%H:%M:%fZ','now'),?,?,?,?,?,?,?)",
                   (actor.get(),request_id.get(),source.get(),entity,action,json.dumps(before) if before is not None else None,json.dumps(after) if after is not None else None))
