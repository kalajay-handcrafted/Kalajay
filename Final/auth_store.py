import hashlib,hmac,secrets,time,sqlite3
from http.cookies import SimpleCookie

def initialize(connect,root):
 with connect() as db:
  db.executescript('CREATE TABLE IF NOT EXISTS auth_users(username TEXT PRIMARY KEY, salt TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN (\'admin\',\'manager\'))); CREATE TABLE IF NOT EXISTS auth_sessions(token_hash TEXT PRIMARY KEY,username TEXT REFERENCES auth_users(username),expires REAL NOT NULL); CREATE TABLE IF NOT EXISTS auth_attempts(client TEXT PRIMARY KEY, failures INTEGER NOT NULL, until REAL NOT NULL);')
  if not db.execute('SELECT 1 FROM auth_users').fetchone():
   p=root/'auth-setup-token'
   if not p.exists():p.write_text(secrets.token_urlsafe(32));p.chmod(0o600)
def password_hash(password,salt):return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
def credentials(data):
 if not isinstance(data,dict):raise ValueError('Invalid credentials.')
 user=data.get('username','');pw=data.get('password','')
 if not isinstance(user,str) or not 1<=len(user.strip())<=80 or not all(c.isalnum() or c in '._-@' for c in user.strip()):raise ValueError('Use a username with letters, numbers, dots, underscores or hyphens.')
 if not isinstance(pw,str) or not 12<=len(pw)<=256:raise ValueError('Use a password of 12–256 characters.')
 return user.strip().lower(),pw

def create(connect,data,root=None):
 user,pw=credentials(data);role=data.get('role','admin' if root else 'manager')
 if role not in ('admin','manager'):raise ValueError('Invalid role.')
 salt=secrets.token_hex(16);digest=password_hash(pw,salt)
 with connect() as db:
  db.execute('BEGIN IMMEDIATE')
  if root:
   p=root/'auth-setup-token'
   if db.execute('SELECT 1 FROM auth_users').fetchone() or not p.exists() or not hmac.compare_digest(str(data.get('token','')),p.read_text()):raise ValueError('Setup link is invalid or already used.')
   role='admin'
  try:db.execute('INSERT INTO auth_users VALUES (?,?,?,?)',(user,salt,digest,role))
  except sqlite3.IntegrityError:raise ValueError('Username already exists.')
 if root:p.unlink(missing_ok=True)
 return {'username':user,'role':role}
def current(connect,cookie):
 try:
  c=SimpleCookie();c.load(cookie or '');token=c['kj_session'].value
 except (KeyError,Exception):return None
 with connect() as db:
  row=db.execute('SELECT u.username,u.role FROM auth_sessions s JOIN auth_users u USING(username) WHERE token_hash=? AND expires>?',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
  return dict(row) if row else None

def login(connect,data,client):
 if not isinstance(data,dict):raise ValueError('Invalid username or password.')
 user=data.get('username','');pw=data.get('password','')
 if not isinstance(user,str) or not isinstance(pw,str) or len(pw)>256:raise ValueError('Invalid username or password.')
 with connect() as db:
  db.execute('BEGIN IMMEDIATE')
  attempt=db.execute('SELECT * FROM auth_attempts WHERE client=?',(client,)).fetchone()
  if attempt and attempt['failures']>=8 and attempt['until']>time.time():raise ValueError('Too many attempts. Try again in 15 minutes.')
  row=db.execute('SELECT * FROM auth_users WHERE username=?',(user.strip().lower(),)).fetchone()
  digest=password_hash(pw,row['salt'] if row else '00'*16)
  valid=bool(row and hmac.compare_digest(digest,row['password_hash']))
  if not valid:
   failures=attempt['failures']+1 if attempt and attempt['until']>time.time() else 1
   db.execute('INSERT OR REPLACE INTO auth_attempts VALUES (?,?,?)',(client,failures,time.time()+900))
  else:
   db.execute('DELETE FROM auth_attempts WHERE client=?',(client,))
   db.execute('DELETE FROM auth_sessions WHERE expires<=?',(time.time(),))
   token=secrets.token_urlsafe(32)
   db.execute('INSERT INTO auth_sessions VALUES (?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),row['username'],time.time()+43200))
 if not valid:raise ValueError('Invalid username or password.')
 return token

def logout(connect,cookie):
 c=SimpleCookie();c.load(cookie or '')
 if 'kj_session' in c:
  with connect() as db:db.execute('DELETE FROM auth_sessions WHERE token_hash=?',(hashlib.sha256(c['kj_session'].value.encode()).hexdigest(),))
