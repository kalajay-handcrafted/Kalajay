"""Expense book in the ERP's existing SQLite database; bill files stay private."""
import base64
import binascii
import copy
import hashlib
import json
import math
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

class Conflict(Exception):
    pass

def initialize(connect, root):
    # Back up before the additive structural migration. Never use a second live DB.
    backup = Path(root) / 'before-expenses.sqlite3'
    with connect() as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='expense_book'").fetchone()
        if not exists and not backup.exists():
            with sqlite3.connect(backup) as destination:
                db.backup(destination)
            backup.chmod(0o600)
        db.executescript("""
        CREATE TABLE IF NOT EXISTS expense_book (
            id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL,
            payload TEXT NOT NULL, updated_by TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """)
        empty = {'version': 1, 'entries': [], 'budgets': {}, 'sourceOptions': {}}
        db.execute("INSERT OR IGNORE INTO expense_book VALUES (1,0,?,'','')", (json.dumps(empty),))
    directory = Path(root) / 'expense-bills'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)

def state(connect):
    with connect() as db:
        row = db.execute('SELECT revision,payload FROM expense_book WHERE id=1').fetchone()
        return {'revision': row['revision'], 'book': json.loads(row['payload'])}

def _text(value, limit=2000):
    return isinstance(value, str) and len(value) <= limit

def _integer(value, low=0, high=99999999900):
    return type(value) is int and low <= value <= high

def validate(book):
    if not isinstance(book, dict) or book.get('version') != 1:
        raise ValueError('Select a Kalajay expense backup.')
    entries, budgets = book.get('entries'), book.get('budgets', {})
    options = book.get('sourceOptions', {})
    if not isinstance(options, dict) or any(not _text(k, 100) or not isinstance(v, list) or len(v) > 10000 or any(not _text(item, 2000) for item in v) for k, v in options.items()):
        raise ValueError('Invalid source dropdown options.')
    if not isinstance(entries, list) or len(entries) > 100000 or not isinstance(budgets, dict):
        raise ValueError('Invalid expense records.')
    ids = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Invalid entry.')
        key = entry.get('id')
        if not _text(key, 150) or not key or key in ids:
            raise ValueError('Every entry needs a unique ID.')
        ids.add(key)
        try:
            date.fromisoformat(entry['date'])
        except (KeyError, TypeError, ValueError):
            raise ValueError('Every entry needs a valid date.')
        if entry.get('type') not in ('expense', 'income'):
            raise ValueError('Invalid entry type.')
        if entry.get('status') not in ('paid', 'pending', 'recorded'):
            raise ValueError('Invalid payment status.')
        if not _integer(entry.get('amount')):
            raise ValueError('Amount must be a nonnegative value in paise.')
        for field in ('description', 'category', 'party', 'method', 'notes',
                      'group', 'subcategory', 'paidBy', 'treatment', 'frequency',
                      'reviewNote', 'reviewReason', 'reviewSignature'):
            if field in entry and not _text(entry[field], 10000 if field == 'reviewSignature' else 2000):
                raise ValueError('Invalid ' + field + '.')
        if not entry.get('description', '').strip():
            raise ValueError('Description is required.')
        for field in ('badInvestment', 'dateAssumed'):
            if field in entry and type(entry[field]) is not bool:
                raise ValueError('Invalid flag.')
        quantity = entry.get('quantity', 1)
        if type(quantity) not in (int, float) or not math.isfinite(quantity) or not 0 < quantity <= 999999999:
            raise ValueError('Quantity must be positive.')
        if entry.get('unitPrice') is not None and not _integer(entry['unitPrice']):
            raise ValueError('Invalid unit price.')
        bills = entry.get('bills', [])
        if not isinstance(bills, list) or len(bills) > 3 or any(not isinstance(b, dict) for b in bills):
            raise ValueError('Attach up to three bills per entry.')
    if any(not _text(k, 100) or not _integer(v, 1) for k, v in budgets.items()):
        raise ValueError('Invalid budgets.')
    if len(json.dumps(book)) > 25000000:
        raise ValueError('Expense book is too large.')

def _bill_bytes(data):
    if not isinstance(data, str) or len(data) > 1400000:
        raise ValueError('Bill is too large (maximum 1 MB).')
    match = re.fullmatch(r'data:(image/jpeg|image/png|image/webp|application/pdf);base64,([A-Za-z0-9+/=\r\n]+)', data)
    if not match:
        raise ValueError('Use JPEG, PNG, WebP or PDF bills.')
    try:
        raw = base64.b64decode(match[2], validate=True)
    except binascii.Error:
        raise ValueError('Invalid bill attachment.')
    mime = match[1]
    signatures = {
        'image/jpeg': raw.startswith(b'\xff\xd8\xff'),
        'image/png': raw.startswith(b'\x89PNG\r\n\x1a\n'),
        'image/webp': raw.startswith(b'RIFF') and raw[8:12] == b'WEBP',
        'application/pdf': raw.startswith(b'%PDF-'),
    }
    if not raw or len(raw) > 1000000 or not signatures[mime]:
        raise ValueError('Bill content does not match its file type.')
    return mime, raw

def update(connect, root, request, username):
    if not isinstance(request, dict) or not _integer(request.get('revision'), 0, 2**53-1):
        raise ValueError('A current revision is required.')
    book = copy.deepcopy(request.get('book'))
    validate(book)
    prepared = []
    directory = Path(root) / 'expense-bills'
    extensions = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'application/pdf': '.pdf'}
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT revision,payload FROM expense_book WHERE id=1').fetchone()
        if row['revision'] != request['revision']:
            raise Conflict('Expenses changed on another device. Reload before saving.')
        existing = json.loads(row['payload'])
        allowed = {b['id']: b for e in existing['entries'] for b in e.get('bills', [])}
        for entry in book['entries']:
            normalized = []
            for bill in entry.get('bills', []):
                if not _text(bill.get('name'), 200):
                    raise ValueError('Bill filename is required.')
                if 'data' in bill:
                    mime, raw = _bill_bytes(bill['data'])
                    key = hashlib.sha256(raw).hexdigest() + extensions[mime]
                    prepared.append((directory / key, raw))
                    normalized.append({'id': key, 'name': bill['name'], 'mime': mime,
                                       'url': '/api/erp/expenses/bills/' + key})
                else:
                    previous = allowed.get(bill.get('id', ''))
                    if not previous:
                        raise ValueError('Unknown bill attachment. Restore a full backup.')
                    normalized.append({**previous, 'name': bill['name']})
            entry['bills'] = normalized
        # Store immutable bill files before references. A failed save never deletes old files.
        for path, raw in prepared:
            try:
                with path.open('xb') as output:
                    output.write(raw)
                path.chmod(0o600)
            except FileExistsError:
                pass
        db.execute('UPDATE expense_book SET revision=revision+1,payload=?,updated_by=?,updated_at=? WHERE id=1',
                   (json.dumps(book, ensure_ascii=False), username, datetime.now(timezone.utc).isoformat()))
    return state(connect)

def bill(connect, root, key):
    if not re.fullmatch(r'[0-9a-f]{64}\.(jpg|png|webp|pdf)', key):
        raise ValueError('Bill not found.')
    existing = state(connect)['book']
    record = next((b for e in existing['entries'] for b in e.get('bills', []) if b['id'] == key), None)
    path = Path(root) / 'expense-bills' / key
    if not record or not path.is_file():
        raise ValueError('Bill not found.')
    return path.read_bytes(), record['mime']

def backup(connect, root):
    result = state(connect)['book']
    for entry in result['entries']:
        for attachment in entry.get('bills', []):
            raw, mime = bill(connect, root, attachment['id'])
            attachment['data'] = 'data:' + mime + ';base64,' + base64.b64encode(raw).decode()
    return result
