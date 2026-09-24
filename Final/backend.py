"""Kalajay local backend. Run: python3 backend.py --port 8000"""
import argparse
import os
import json
import mimetypes
import sqlite3
import uuid
import shared_store as shared
import team_store as team
import auth_store as auth
import catalogue_excel as excel
import subprocess, tempfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get('KALAJAY_DATA_DIR', str(ROOT / 'private')))
DB = DATA_DIR / 'kalajay.sqlite3'
ERP_ROOT = Path(os.environ.get('KALAJAY_ERP_ROOT', str(ROOT / 'erp' if (ROOT / 'erp').exists() else ROOT.parent.parent / 'KalajayERP')))
PRODUCTION = os.environ.get('KALAJAY_PRODUCTION') == '1'
ALLOWED_HOSTS = set(filter(None, os.environ.get('KALAJAY_HOSTS','www.kalajay.in,kalajay.in,erp.kalajay.in').split(',')))
if os.environ.get('RENDER_EXTERNAL_HOSTNAME'): ALLOWED_HOSTS.add(os.environ['RENDER_EXTERNAL_HOSTNAME'])

def connect():
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db

def initialize():
    DB.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS content (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS products (name TEXT PRIMARY KEY, image TEXT NOT NULL, category TEXT NOT NULL, price INTEGER NOT NULL, sold_out INTEGER NOT NULL, position INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, customer TEXT NOT NULL, items TEXT NOT NULL, total INTEGER NOT NULL, note TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new');
        ''')
        if not db.execute('SELECT 1 FROM products LIMIT 1').fetchone():
            data = json.loads((ROOT / 'catalogue.json').read_text())
            for i, (name, image, category) in enumerate(data['products']):
                db.execute('INSERT INTO products VALUES (?,?,?,?,?,?)', (name, image, category, data['prices'].get(name, data['defaultPrice']), int(name in data['soldOut']), i))
            db.execute('INSERT OR REPLACE INTO content VALUES (?,?)', ('collections', json.dumps(data['collections'])))
        # Preserve all page content and design in the database; refresh from the editable file at startup.
        db.execute('INSERT OR REPLACE INTO content VALUES (?,?)', ('homepage', (ROOT / 'index.html').read_text()))
    DB.chmod(0o600)
    shared.migrate(connect, ROOT, ERP_ROOT)
    team.initialize(connect)
    auth.initialize(connect, DATA_DIR)

def catalogue():
    return shared.catalog(connect)

def save_order(data):
    return shared.save_order(connect, data)

class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def valid_host(self):
        host=self.headers.get('Host','').split(':')[0].lower()
        return not PRODUCTION or host in ALLOWED_HOSTS

    def expected_origin(self):
        return ('https://' if PRODUCTION else 'http://') + self.headers.get('Host','')

    def session_cookie(self, token, age):
        return 'kj_session='+token+'; HttpOnly; SameSite=Strict; Path=/; Max-Age='+str(age)+('; Secure' if PRODUCTION else '')

    def send(self, status, body, kind='application/json; charset=utf-8', headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        if kind == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
            self.send_header('Content-Disposition', 'attachment; filename=Kalajay-Catalogue-Update.xlsx')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy','same-origin')
        self.send_header('X-Frame-Options','SAMEORIGIN')
        for key,value in (headers or {}).items(): self.send_header(key,value)
        self.end_headers()
        self.wfile.write(body)

    def erp_page(self, html):
        user=auth.current(connect,self.headers.get('Cookie'))
        extra='<script>window.ERP_USER='+json.dumps(user)+'</script><script src="/erp/auth.js" defer></script>'
        return self.send(200,html.replace('</head>',extra+'</head>') if '</head>' in html else html.replace('<main>',extra+'<main>'), 'text/html; charset=utf-8')

    def do_GET(self):
        if not self.valid_host(): return self.send(400, {'error':'Invalid host.'})
        path = unquote(urlsplit(self.path).path)
        if path == '/healthz':return self.send(200, {'status':'ok'})
        if path == '/' and self.headers.get('Host','').split(':')[0].lower() == 'erp.kalajay.in':
            return self.send(302, '', 'text/plain', {'Location':'/erp/'})
        if path in ('/erp/login','/erp/setup'):
            return self.send(200,(ROOT/'auth.html').read_text(),'text/html; charset=utf-8')
        protected=path=='/erp' or path.startswith('/erp/') or path.startswith('/api/erp') or path in ('/api/catalogue.xlsx','/api/auth/users')
        user=auth.current(connect,self.headers.get('Cookie')) if protected else None
        if protected and not user:
            if path.startswith('/api/'): return self.send(401,{'error':'Please sign in to ERP.'})
            return self.send(303,'','text/plain',{'Location':'/erp/login'})
        if path in ('/erp/accounts','/api/auth/users'):
            if user['role']!='admin':return self.send(403,{'error':'Admin access required.'})
            if path=='/erp/accounts':return self.erp_page((ROOT/'auth.html').read_text())
            with connect() as db:return self.send(200,[dict(row) for row in db.execute('SELECT username,role FROM auth_users ORDER BY username')])
        if path=='/erp/auth.js':return self.send(200,(ROOT/'erp-auth.js').read_text(),'application/javascript')
        if path == '/erp/team':
            return self.erp_page((ROOT/'team.html').read_text())
        if path == '/api/erp/cities':
            return self.send(200, team.cities(connect))
        if path == '/api/erp/team':
            return self.send(200, team.state(connect))
        if path in ('/erp', '/erp/', '/erp/index.html'):
            with connect() as db:
                return self.erp_page(db.execute("SELECT value FROM content WHERE key='erp_homepage'").fetchone()[0])
        if path == '/api/catalogue.xlsx':
            try:
                return self.send(200, excel.export_workbook(connect), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            except Exception:
                return self.send(503, {'error': 'Excel export failed. Please try again.'})
        if path == '/api/erp':
            return self.send(200, shared.state(connect))
        if path.startswith('/erp/'):
            rel = path[5:]
            file = (ERP_ROOT / rel).resolve()
            allowed = rel == 'support.js' or rel.startswith(('assets/', 'uploads/'))
            if not allowed or not file.is_relative_to(ERP_ROOT) or not file.is_file():
                return self.send(404, {'error': 'Not found'})
            return self.send(200, file.read_bytes(), mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
        if path in ('/', '/index.html', '/shop', '/shop/', '/story', '/story/'):
            with connect() as db:
                return self.send(200, db.execute("SELECT value FROM content WHERE key='homepage'").fetchone()[0], 'text/html; charset=utf-8')
        if path == '/api/catalogue':
            return self.send(200, catalogue())
        if path == '/api/catalogue.js':
            return self.send(200, 'window.KALAJAY_DATA = ' + json.dumps(catalogue()) + ';', 'application/javascript; charset=utf-8')
        file = (ROOT / path.lstrip('/')).resolve()
        allowed = path == '/support.js' or path.startswith(('/assets/', '/v2/', '/uploads/')) or path == '/kalajay_wordmark_transparent-mtyrts9s-tzhj.png'
        if not allowed or not file.is_relative_to(ROOT) or not file.is_file():
            return self.send(404, {'error': 'Not found'})
        return self.send(200, file.read_bytes(), mimetypes.guess_type(file.name)[0] or 'application/octet-stream')

    def do_POST(self):
        if not self.valid_host():return self.send(400, {"error":"Invalid host."})
        if self.path.startswith('/api/auth/'):
            return self.auth_post()
        if self.path not in ('/api/erp/cities', '/api/erp/team', '/api/orders', '/api/erp', '/api/erp/confirm', '/api/catalogue/import-preview', '/api/catalogue/import'):
            return self.send(404, {'error': 'Not found'})
        origin = self.headers.get('Origin')
        if origin and origin != self.expected_origin():
            return self.send(403, {'error': 'Cross-origin requests are not allowed.'})
        if self.path != '/api/orders':
            user=auth.current(connect,self.headers.get('Cookie'))
            if not user:return self.send(401,{'error':'Please sign in to ERP.'})
            if user['role']!='admin':return self.send(403,{'error':'Managers have view-only access.'})
            if origin != self.expected_origin():return self.send(403,{'error':'Same-origin request required.'})
        if self.path in ('/api/catalogue/import-preview', '/api/catalogue/import'):
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 5000000:
                    return self.send(413, {'error': 'Workbook must be under 5 MB.'})
                return self.send(200, excel.import_sheet(connect, self.rfile.read(size), self.path == '/api/catalogue/import'))
            except shared.Conflict as error:
                return self.send(409, {'error': str(error)})
            except (ValueError, UnicodeError) as error:
                return self.send(400, {'error': str(error)})
            except sqlite3.Error:
                return self.send(503, {'error': 'Import failed. No changes were saved.'})
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.send(415, {'error': 'JSON required.'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= (5000000 if self.path == '/api/erp' else 32768):
                return self.send(413, {'error': 'Invalid request size.'})
            data = json.loads(self.rfile.read(size))
            if self.path == '/api/erp/cities':
                return self.send(200, team.cities(connect, data))
            if self.path == '/api/erp/team':
                return self.send(200, team.add(connect, data))
            if self.path == '/api/erp':
                return self.send(200, shared.update(connect, data))
            if self.path == '/api/erp/confirm':
                if not isinstance(data, dict) or not isinstance(data.get('orderId'), str):
                    raise ValueError('Order ID required.')
                return self.send(200, shared.confirm(connect, data['orderId']))
            return self.send(201, save_order(data))
        except shared.Conflict as error:
            return self.send(409, {'error': str(error)})
        except (ValueError, UnicodeError) as error:
            return self.send(400, {'error': str(error)})
        except sqlite3.Error:
            return self.send(503, {'error': 'Could not save your order. Please try again.'})

    def auth_post(self):
        if self.headers.get('Origin') != self.expected_origin():
            return self.send(403,{'error':'Same-origin request required.'})
        try:
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.send(415,{'error':'JSON required.'})
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=4096:raise ValueError('Invalid request size.')
            data=json.loads(self.rfile.read(size))
            path=self.path
            if path=='/api/auth/login':
                token=auth.login(connect,data,self.client_address[0])
                return self.send(200,{'ok':True},headers={'Set-Cookie':self.session_cookie(token,43200)})
            if path=='/api/auth/setup':return self.send(201,auth.create(connect,data,DATA_DIR))
            user=auth.current(connect,self.headers.get('Cookie'))
            if not user:return self.send(401,{'error':'Please sign in.'})
            if path=='/api/auth/logout':
                auth.logout(connect,self.headers.get('Cookie'))
                return self.send(200,{'ok':True},headers={'Set-Cookie':self.session_cookie('',0)})
            if path=='/api/auth/users':
                if user['role']!='admin':return self.send(403,{'error':'Admin access required.'})
                return self.send(201,auth.create(connect,data))
            return self.send(404,{'error':'Not found'})
        except (ValueError,UnicodeError) as error:return self.send(400,{'error':str(error)})
        except sqlite3.Error:return self.send(503,{'error':'Unable to save login details.'})

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT','8000')))
    args = parser.parse_args()
    initialize()
    print(f'Kalajay running at http://127.0.0.1:{args.port}', flush=True)
    ThreadingHTTPServer(('0.0.0.0' if PRODUCTION else '127.0.0.1', args.port), Handler).serve_forever()
