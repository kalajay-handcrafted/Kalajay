"""Private image attachments for existing ERP team records."""
import base64
import binascii
import hashlib
import re
import sqlite3
import uuid
from pathlib import Path

def initialize(connect, data_dir):
    directory = Path(data_dir)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = directory / 'before-team-images.sqlite3'
    with connect() as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='team_member_images'").fetchone()
        if not exists and not backup.exists():
            with sqlite3.connect(backup) as destination:
                db.backup(destination)
            backup.chmod(0o600)
        db.executescript("""
        CREATE TABLE IF NOT EXISTS team_member_images (
            member_id TEXT NOT NULL REFERENCES team_members(id) ON DELETE CASCADE,
            image_id TEXT NOT NULL, name TEXT NOT NULL, mime TEXT NOT NULL,
            position INTEGER NOT NULL,
            PRIMARY KEY(member_id, image_id)
        );
        """)
    (directory / 'team-images').mkdir(exist_ok=True, mode=0o700)
    with connect() as db:
        count = db.execute('SELECT COUNT(*) FROM team_member_images').fetchone()[0]
    print('Team image storage ready: '+str(count)+' image attachments.', flush=True)

def attachments(db):
    result = {}
    for row in db.execute('SELECT * FROM team_member_images ORDER BY member_id,position'):
        result.setdefault(row['member_id'], []).append({
            'id': row['image_id'], 'name': row['name'], 'mime': row['mime'],
            'url': '/api/erp/team/images/'+row['member_id']+'/'+row['image_id'],
        })
    return result

def _decode(value):
    if not isinstance(value, str) or len(value) > 1400000:
        raise ValueError('Each saved image must be under 1 MB.')
    match = re.fullmatch(r'data:(image/jpeg|image/png|image/webp);base64,([A-Za-z0-9+/=]+)', value)
    if not match:
        raise ValueError('Attach a JPEG, PNG or WebP image.')
    try:
        raw = base64.b64decode(match[2], validate=True)
    except binascii.Error:
        raise ValueError('Invalid image attachment.')
    mime = match[1]
    valid = {
        'image/jpeg': raw.startswith(b'\xff\xd8\xff'),
        'image/png': raw.startswith(b'\x89PNG\r\n\x1a\n'),
        'image/webp': raw.startswith(b'RIFF') and raw[8:12] == b'WEBP',
    }
    if not raw or len(raw) > 1000000 or not valid[mime]:
        raise ValueError('Image contents do not match the file type.')
    return mime, raw

def save(db, data_dir, member_id, images, expected_ids):
    """Called inside the same transaction as the member update."""
    if not isinstance(images, list) or len(images) > 3:
        raise ValueError('Attach up to three images per member.')
    existing = {row['image_id']: dict(row) for row in db.execute(
        'SELECT * FROM team_member_images WHERE member_id=?', (member_id,))}
    if not isinstance(expected_ids, list) or any(not isinstance(key, str) for key in expected_ids):
        raise ValueError('Current image references are required.')
    if sorted(expected_ids) != sorted(existing):
        raise ValueError('This member’s images changed in another session. Reload and edit again.')
    normalized, files, seen = [], [], set()
    extensions = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp'}
    for item in images:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not 1 <= len(item['name']) <= 200:
            raise ValueError('An image filename is required.')
        if 'data' in item:
            mime, raw = _decode(item['data'])
            key = hashlib.sha256(raw).hexdigest() + extensions[mime]
            files.append((Path(data_dir)/'team-images'/key, raw))
            record = {'image_id':key, 'name':item['name'], 'mime':mime}
        else:
            record = existing.get(item.get('id'))
            if record is None:
                raise ValueError('Unknown image attachment for this member.')
            record = {**record, 'name':item['name']}
            key = record['image_id']
        if key in seen:
            raise ValueError('The same image was attached more than once.')
        seen.add(key)
        normalized.append(record)
    # Immutable disk files: failed saves cannot delete prior member images.
    for path, raw in files:
        try:
            with path.open('xb') as output:
                output.write(raw)
            path.chmod(0o600)
        except FileExistsError:
            pass
    db.execute('DELETE FROM team_member_images WHERE member_id=?', (member_id,))
    for position, record in enumerate(normalized):
        db.execute('INSERT INTO team_member_images VALUES (?,?,?,?,?)',
                   (member_id, record['image_id'], record['name'], record['mime'], position))

def read(connect, data_dir, member_id, key):
    try:
        if str(uuid.UUID(member_id)) != member_id:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Image not found.')
    if not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{64}\.(jpg|png|webp)', key):
        raise ValueError('Image not found.')
    with connect() as db:
        row = db.execute('SELECT mime FROM team_member_images WHERE member_id=? AND image_id=?',
                         (member_id, key)).fetchone()
    path = Path(data_dir)/'team-images'/key
    if not row or not path.is_file():
        raise ValueError('Image not found.')
    return path.read_bytes(), row['mime']
