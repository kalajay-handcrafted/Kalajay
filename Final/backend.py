"""Kalajay local backend. Run: python3 backend.py --port 8000"""
import argparse
import json
import mimetypes
import sqlite3
import uuid
import shared_store as shared
import team_store as team
import catalogue_excel as excel
import subprocess, tempfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'private' / 'kalajay.sqlite3'
ERP_ROOT = ROOT.parent.parent / 'KalajayERP'

def connect():
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db

def initialize():
    DB.parent.mkdir(exist_ok=True, mode=0o700)
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

def catalogue():
    return shared.catalog(connect)

def save_order(data):
    return shared.save_order(connect, data)

class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, kind='application/json; charset=utf-8'):
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
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        if path == '/erp/team':
            return self.send(200, (ROOT/'team.html').read_text(), 'text/html; charset=utf-8')
        if path == '/api/erp/cities':
            return self.send(200, team.cities(connect))
        if path == '/api/erp/team':
            return self.send(200, team.state(connect))
        if path in ('/erp', '/erp/', '/erp/index.html'):
            with connect() as db:
                return self.send(200, db.execute("SELECT value FROM content WHERE key='erp_homepage'").fetchone()[0], 'text/html; charset=utf-8')
        if path == '/api/catalogue.xlsx':
            try:
                with tempfile.TemporaryDirectory() as temp:
                    base = Path(temp)
                    (base/'data.json').write_text(json.dumps(excel.export_data(connect)))
                    subprocess.run(['/Users/som/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node', str(ROOT/'catalogue_excel.mjs'), str(base/'data.json'), str(base/'catalogue.xlsx')], check=True, timeout=60, capture_output=True)
                    return self.send(200, (base/'catalogue.xlsx').read_bytes(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            except (OSError, subprocess.SubprocessError):
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
        if self.path not in ('/api/erp/cities', '/api/erp/team', '/api/orders', '/api/erp', '/api/erp/confirm', '/api/catalogue/import-preview', '/api/catalogue/import'):
            return self.send(404, {'error': 'Not found'})
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + self.headers.get('Host', ''):
            return self.send(403, {'error': 'Cross-origin requests are not allowed.'})
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

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    initialize()
    print(f'Kalajay running at http://127.0.0.1:{args.port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
