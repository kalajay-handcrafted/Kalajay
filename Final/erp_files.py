"""Admin cleanup of owned uploads, with shared-reference checks under the write lock."""
import hashlib
import json
import re
from pathlib import Path

DIRECTORIES = {'products': 'product-images', 'bills': 'expense-bills', 'team': 'team-images'}
NAME = re.compile(r'[0-9a-f]{64}\.(?:webp|jpg|png|pdf)')


def listing(connect, root):
    references = {}
    def add(key, label):
        references.setdefault(key, set()).add(label)
    with connect() as db:
        for row in db.execute('SELECT p.product_code,p.image,i.record FROM products p JOIN inventory i USING(product_code) WHERE p.active=1'):
            data = json.loads(row['record'])
            paths = [row['image'], data.get('image', '')] + data.get('images', [])
            paths += [image for v in data.get('variants', []) for image in v.get('images', [])]
            for path in paths:
                if isinstance(path, str) and path.startswith('/media/products/'):
                    add('products/' + path.rsplit('/', 1)[-1], row['product_code'])
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='team_member_images'").fetchone():
            for row in db.execute('SELECT member_id,image_id FROM team_member_images'):
                add('team/' + row['image_id'], 'Team member ' + row['member_id'])
        book = db.execute('SELECT payload FROM expense_book WHERE id=1').fetchone()
        if book:
            for entry in json.loads(book[0]).get('entries', []):
                for bill in entry.get('bills', []):
                    add('bills/' + bill['id'], entry.get('code') or entry['id'])
    files = []
    for kind, folder in DIRECTORIES.items():
        for path in sorted((Path(root) / folder).glob('*')):
            if not NAME.fullmatch(path.name) or not path.is_file() or path.is_symlink():
                continue
            key = kind + '/' + path.name
            data = {'name': path.name, 'fileType': kind, 'bytes': path.stat().st_size,
                    'usedBy': sorted(references.get(key, [])),
                    'url': '/media/products/' + path.name if kind == 'products' else '/api/erp/expenses/bills/' + path.name if kind == 'bills' else None}
            version = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
            files.append({'id': key, 'version': version, 'data': data})
    return {'records': files}


def delete(root, key):
    kind, name = key.split('/', 1)
    if kind not in DIRECTORIES or not NAME.fullmatch(name):
        raise ValueError('Invalid uploaded file.')
    path = Path(root) / DIRECTORIES[kind] / name
    if path.is_symlink():
        raise ValueError('Invalid uploaded file.')
    path.unlink(missing_ok=True)
