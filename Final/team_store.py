"""Private team directory; only its aggregate count is included in public catalogue data."""
import uuid, json
from datetime import date
FIELDS=('name','capacity','member_code','membership_type','phone','email','address','date_of_birth','emergency_name','emergency_phone','notes')
def initialize(connect):
    with connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS team_members (id TEXT PRIMARY KEY, name TEXT NOT NULL, capacity TEXT NOT NULL, joined_on TEXT NOT NULL, details TEXT NOT NULL, existing_member INTEGER NOT NULL, active INTEGER NOT NULL)')
        db.execute("INSERT OR IGNORE INTO shared_meta(key,value) VALUES ('team_baseline',21)")
        db.execute("INSERT OR IGNORE INTO shared_meta(key,value) VALUES ('city_count',2)")
def cities(connect,data=None):
    with connect() as db:
        if data is not None:
            if not isinstance(data,dict) or type(data.get('count')) is not int or not 0<=data['count']<=100000: raise ValueError('City count must be a whole number between 0 and 100000.')
            db.execute("UPDATE shared_meta SET value=? WHERE key='city_count'",(data['count'],))
        return {'count':db.execute("SELECT value FROM shared_meta WHERE key='city_count'").fetchone()[0]}
def count(db):
    return db.execute("SELECT value FROM shared_meta WHERE key='team_baseline'").fetchone()[0] + db.execute('SELECT COALESCE(SUM(active-existing_member),0) FROM team_members').fetchone()[0]
def state(connect):
    with connect() as db:
        members=[dict(json.loads(r['details']),id=r['id'],name=r['name'],capacity=r['capacity'],joined_on=r['joined_on'],existing_member=bool(r['existing_member']),active=bool(r['active'])) for r in db.execute('SELECT * FROM team_members ORDER BY name COLLATE NOCASE')]
        baseline=db.execute("SELECT value FROM shared_meta WHERE key='team_baseline'").fetchone()[0]
        return dict(count=count(db), baseline=baseline,unregistered=baseline-sum(m['existing_member'] for m in members),members=members)
def add(connect,data):
    if not isinstance(data,dict): raise ValueError('Member details required.')
    clean={}
    for key in FIELDS:
        value=data.get(key,'')
        if not isinstance(value,str) or len(value.strip())>(2000 if key in ('notes','address') else 150): raise ValueError('Invalid '+key+'.')
        clean[key]=value.strip()
    if not clean['name'] or not clean['capacity'] or not clean['member_code']: raise ValueError('Name, member code and role are required.')
    for key in ('active','existing_member'):
        if type(data.get(key)) is not bool: raise ValueError('Membership status is required.')
    try:
        member_id=str(uuid.UUID(data.get('id','')))
        joined=data.get('joined_on','')
        if not isinstance(joined,str): raise ValueError()
        if joined and date.fromisoformat(joined)>date.today(): raise ValueError()
        if clean['date_of_birth'] and date.fromisoformat(clean['date_of_birth'])>date.today(): raise ValueError()
    except (ValueError,TypeError,AttributeError): raise ValueError('Use valid dates, no later than today.')
    if clean['email'] and ('@' not in clean['email'] or ' ' in clean['email']): raise ValueError('Enter a valid email address.')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for row in db.execute('SELECT id,details FROM team_members WHERE id<>?',(member_id,)):
            if json.loads(row['details'])['member_code'].casefold()==clean['member_code'].casefold(): raise ValueError('Member code already exists. Edit the existing member instead.')
        baseline=db.execute("SELECT value FROM shared_meta WHERE key='team_baseline'").fetchone()[0]
        registered=db.execute('SELECT COUNT(*) FROM team_members WHERE existing_member=1 AND id<>?',(member_id,)).fetchone()[0]
        if data['existing_member'] and registered>=baseline: raise ValueError('All 21 existing members have already been registered.')
        db.execute('INSERT INTO team_members VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,capacity=excluded.capacity,joined_on=excluded.joined_on,details=excluded.details,existing_member=excluded.existing_member,active=excluded.active',(member_id,clean['name'],clean['capacity'],joined,json.dumps(clean),int(data['existing_member']),int(data['active'])))
    return state(connect)
