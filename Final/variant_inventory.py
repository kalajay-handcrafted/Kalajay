"""Display groups have no stock; each colour/variety is a stock-bearing SKU."""
import copy
import json
import sqlite3
from pathlib import Path

COUNTERS = ('open', 'purch', 'made', 'sold', 'dmg', 'adjustment')


def is_group(product):
    return bool(product.get('variants')) and not product.get('parentCode')


def prepare(products, previous):
    """Expand option descriptors without copying a parent's stock to every colour."""
    import shared_store as shared
    result = copy.deepcopy(products)
    old = {p['code']: p for p in previous}
    by_code = {p['code']: p for p in result}
    for parent in list(result):
        if parent.get('parentCode'):
            if parent.get('variants'):
                raise ValueError('A variety cannot contain further varieties.')
            continue
        prior = old.get(parent['code'], {})
        options = parent.get('variants', prior.get('variants', []))
        parent['variants'] = options
        if not options:
            if prior.get('isVariantGroup'):
                raise ValueError('Keep at least one variety in a display group.')
            parent['isVariantGroup'] = False
            continue
        parent['variants'], parent['variantSequence'] = shared.numbered_variants(parent, prior)
        parent['isVariantGroup'] = True
        retained = set()
        for option in parent['variants']:
            code = option['code']
            retained.add(code)
            child = by_code.get(code)
            existing = old.get(code)
            if child and child.get('parentCode') != parent['code']:
                raise ValueError('Variety code conflicts with another product: ' + code)
            if not child:
                child = copy.deepcopy(existing or parent)
                child.update(code=code, parentCode=parent['code'], variants=[], isVariantGroup=False)
                if not existing:
                    child.update({key: 0 for key in COUNTERS})
                result.append(child)
                by_code[code] = child
            # Names/photos are edited in the group; prices/costs/quantities are independent.
            renamed = not existing or existing.get('variantLabel') != option['label'].strip() or prior.get('name') != parent['name']
            if renamed:
                child['name'] = parent['name'] + ' - ' + option['label'].strip()
            child.update(variantLabel=option['label'].strip(),
                         images=list(option['images']), image=option['images'][0])
        # Preserve an old pooled balance explicitly instead of guessing its colour.
        if any(parent.get(key, 0) for key in COUNTERS):
            if prior.get('isVariantGroup'):
                raise ValueError('Record stock against an individual colour / variety.')
            code = parent['code'] + '-UNASSIGNED'
            if code in by_code:
                raise ValueError('Unassigned stock code already exists: ' + code)
            child = copy.deepcopy(parent)
            child.update(code=code, parentCode=parent['code'], variantLabel='Unassigned',
                         name=parent['name'] + ' - Unassigned', variants=[], isVariantGroup=False,
                         unassignedVariety=True)
            result.append(child)
            by_code[code] = child
        parent.update({key: 0 for key in COUNTERS})
        for code, child in list(by_code.items()):
            if child.get('parentCode') == parent['code'] and code not in retained and not child.get('unassignedVariety'):
                if shared.stock(child):
                    raise ValueError('Clear stock before removing variety ' + code)
                result.remove(child)
                del by_code[code]
    # A child may not be orphaned by removing its display group.
    for child in result:
        if child.get('parentCode') and child['parentCode'] not in by_code:
            raise ValueError('Keep the display group when editing its varieties.')
        if child.get('parentCode') and not child.get('unassignedVariety'):
            parent = by_code[child['parentCode']]
            if child['code'] not in {v['code'] for v in parent.get('variants', [])}:
                raise ValueError('Variety must belong to its display group.')
    return result


def options_for(parent, products, stock):
    by_code = {p['code']: p for p in products}
    result = []
    for option in parent.get('variants', []):
        child = by_code.get(option['code'])
        if child:
            result.append({**option, 'stock': stock(child), 'soldOut': stock(child) <= 0,
                           'price': child['sp']})
    return result


def migrate(connect, data_dir):
    """Idempotent, backed-up conversion of current stored options to SKU records."""
    with connect() as db:
        if db.execute("SELECT 1 FROM shared_meta WHERE key='variety_skus_v1'").fetchone():
            return
    backup = Path(data_dir) / 'before-variety-skus.sqlite3'
    with connect() as source, sqlite3.connect(backup) as target:
        source.backup(target)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM shared_meta WHERE key='variety_skus_v1'").fetchone():
            return
        rows = db.execute('SELECT p.*,i.record FROM products p JOIN inventory i USING(product_code) WHERE p.active=1').fetchall()
        prior = [json.loads(r['record']) for r in rows]
        expanded = prepare(prior, prior)
        source = {r['product_code']: r for r in rows}
        for index, p in enumerate(expanded):
            if p['code'] not in source:
                parent = source[p['parentCode']]
                db.execute('INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?)',
                           (p['code'], p['name'], p['cat'], p['image'], p['sp'],
                            int(sum(p.get(k, 0) * (-1 if k in ('sold', 'dmg') else 1) for k in COUNTERS) <= 0),
                            3000 + index, 1, 1))
            db.execute('INSERT OR REPLACE INTO inventory VALUES (?,?)', (p['code'], json.dumps(p)))
        db.execute("INSERT INTO shared_meta VALUES ('variety_skus_v1',1)")
        db.execute("UPDATE shared_meta SET value=value+1 WHERE key='revision'")
