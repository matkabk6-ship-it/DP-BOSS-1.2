#!/usr/bin/env python3
"""DP BOSS application server. Standard-library only for reproducible local operation."""
import os, json, sqlite3, secrets, hashlib, hmac, base64, time, re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

ROOT=Path(__file__).parent; DATA=ROOT/'data'; DATA.mkdir(exist_ok=True)
DB_PATH=DATA/'dpboss.db'; SECRET=os.getenv('SESSION_SECRET','development-only-change-me').encode()
ADMIN_EMAIL=os.getenv('ADMIN_EMAIL','saisa46571@gmail.com').lower(); ADMIN_PASSWORD=os.getenv('ADMIN_PASSWORD')
USERNAME=re.compile(r'^[a-zA-Z0-9_]{3,30}$'); EMAIL=re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

def now(): return datetime.now(timezone.utc).isoformat()
def db():
 c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c
def password_hash(p):
 salt=secrets.token_bytes(16); key=hashlib.scrypt(p.encode(),salt=salt,n=2**14,r=8,p=1)
 return base64.b64encode(salt+key).decode()
def password_ok(p, saved):
 raw=base64.b64decode(saved); return hmac.compare_digest(hashlib.scrypt(p.encode(),salt=raw[:16],n=2**14,r=8,p=1),raw[16:])
def init():
 c=db(); c.executescript('''
 CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL COLLATE NOCASE, display_name TEXT NOT NULL, email TEXT UNIQUE NOT NULL COLLATE NOCASE, password_hash TEXT NOT NULL, bio TEXT DEFAULT '', private INTEGER DEFAULT 0, role TEXT DEFAULT 'member', status TEXT DEFAULT 'active', created_at TEXT NOT NULL, last_active_at TEXT, deleted_at TEXT);
 CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id), expires_at TEXT NOT NULL, created_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY, author_id INTEGER NOT NULL REFERENCES users(id), body TEXT NOT NULL, visibility TEXT NOT NULL DEFAULT 'public', created_at TEXT NOT NULL, updated_at TEXT, deleted_at TEXT);
 CREATE TABLE IF NOT EXISTS likes(user_id INTEGER REFERENCES users(id), post_id INTEGER REFERENCES posts(id), created_at TEXT NOT NULL, PRIMARY KEY(user_id,post_id));
 CREATE TABLE IF NOT EXISTS comments(id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id), author_id INTEGER NOT NULL REFERENCES users(id), parent_id INTEGER REFERENCES comments(id), body TEXT NOT NULL, created_at TEXT NOT NULL, deleted_at TEXT);
 CREATE TABLE IF NOT EXISTS follows(follower_id INTEGER REFERENCES users(id), following_id INTEGER REFERENCES users(id), status TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(follower_id,following_id));
 CREATE TABLE IF NOT EXISTS blocks(blocker_id INTEGER REFERENCES users(id), blocked_id INTEGER REFERENCES users(id), created_at TEXT NOT NULL, PRIMARY KEY(blocker_id,blocked_id));
 CREATE TABLE IF NOT EXISTS saved_posts(user_id INTEGER REFERENCES users(id), post_id INTEGER REFERENCES posts(id), created_at TEXT NOT NULL, PRIMARY KEY(user_id,post_id));
 CREATE TABLE IF NOT EXISTS stories(id INTEGER PRIMARY KEY, author_id INTEGER REFERENCES users(id), body TEXT NOT NULL, visibility TEXT DEFAULT 'public', expires_at TEXT NOT NULL, created_at TEXT NOT NULL, deleted_at TEXT);
 CREATE TABLE IF NOT EXISTS story_views(story_id INTEGER REFERENCES stories(id), viewer_id INTEGER REFERENCES users(id), viewed_at TEXT NOT NULL, PRIMARY KEY(story_id,viewer_id));
 CREATE TABLE IF NOT EXISTS conversations(id INTEGER PRIMARY KEY, created_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS participants(conversation_id INTEGER REFERENCES conversations(id), user_id INTEGER REFERENCES users(id), last_read_at TEXT, PRIMARY KEY(conversation_id,user_id));
 CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, conversation_id INTEGER REFERENCES conversations(id), sender_id INTEGER REFERENCES users(id), body TEXT NOT NULL, created_at TEXT NOT NULL, deleted_at TEXT);
 CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), actor_id INTEGER REFERENCES users(id), type TEXT NOT NULL, target_type TEXT, target_id INTEGER, created_at TEXT NOT NULL, read_at TEXT);
 CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY, reporter_id INTEGER REFERENCES users(id), target_type TEXT NOT NULL, target_id INTEGER NOT NULL, reason TEXT NOT NULL, details TEXT, status TEXT DEFAULT 'pending', created_at TEXT NOT NULL, resolved_at TEXT, resolver_id INTEGER);
 CREATE TABLE IF NOT EXISTS subscriptions(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), plan_code TEXT NOT NULL, amount_paise INTEGER NOT NULL, provider_ref TEXT UNIQUE NOT NULL, status TEXT NOT NULL, starts_at TEXT, expires_at TEXT, created_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY, admin_id INTEGER REFERENCES users(id), action TEXT NOT NULL, target_type TEXT, target_id INTEGER, reason TEXT, metadata TEXT, created_at TEXT NOT NULL);
 CREATE INDEX IF NOT EXISTS idx_posts_feed ON posts(created_at DESC); CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id,created_at DESC); CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id,created_at);
 ''')
 if ADMIN_PASSWORD and not c.execute('SELECT 1 FROM users WHERE email=?',(ADMIN_EMAIL,)).fetchone():
  c.execute('INSERT INTO users(username,display_name,email,password_hash,role,created_at) VALUES(?,?,?,?,?,?)',('dpboss_admin','DP BOSS Admin',ADMIN_EMAIL,password_hash(ADMIN_PASSWORD),'super_admin',now()))
 c.commit(); c.close()
def row(r): return dict(r) if r else None
def profile(c, u, viewer=None):
 d={'id':u['id'],'username':u['username'],'displayName':u['display_name'],'bio':u['bio'],'private':bool(u['private']),'createdAt':u['created_at'],'role':u['role'] if viewer==u['id'] else None}
 d['followers']=c.execute("SELECT count(*) FROM follows WHERE following_id=? AND status='accepted'",(u['id'],)).fetchone()[0]; d['following']=c.execute("SELECT count(*) FROM follows WHERE follower_id=? AND status='accepted'",(u['id'],)).fetchone()[0]
 return d
def notify(c, uid, actor, typ, target_type=None,target_id=None):
 if uid!=actor: c.execute('INSERT INTO notifications(user_id,actor_id,type,target_type,target_id,created_at) VALUES(?,?,?,?,?,?)',(uid,actor,typ,target_type,target_id,now()))

class App(SimpleHTTPRequestHandler):
 rate={}
 def end_headers(self): self.send_header('X-Content-Type-Options','nosniff'); self.send_header('X-Frame-Options','DENY'); self.send_header('Referrer-Policy','same-origin'); super().end_headers()
 def log_message(self,*a): pass
 def json(self,status,data):
  raw=json.dumps(data).encode(); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
 def body(self):
  try: return json.loads(self.rfile.read(int(self.headers.get('Content-Length','0')) or 0) or b'{}')
  except: raise ValueError('Invalid JSON request.')
 def user(self, required=True):
  token=next((x.split('=',1)[1] for x in self.headers.get('Cookie','').split('; ') if x.startswith('dpboss_session=')),None)
  if not token:
   if required: raise PermissionError('Please sign in to continue.')
   return None
  c=db(); r=c.execute('SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?',(hashlib.sha256(token.encode()).hexdigest(),now())).fetchone(); c.close()
  if not r or r['status']!='active':
   if required: raise PermissionError('Your session has expired or account is unavailable.')
   return None
  return r
 def session(self,u):
  token=secrets.token_urlsafe(32); c=db(); c.execute('INSERT INTO sessions(token_hash,user_id,expires_at,created_at) VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),u['id'],(datetime.now(timezone.utc)+timedelta(days=30)).isoformat(),now())); c.execute('UPDATE users SET last_active_at=? WHERE id=?',(now(),u['id'])); c.commit();c.close(); return token
 def blocked(self,c,a,b): return bool(c.execute('SELECT 1 FROM blocks WHERE (blocker_id=? AND blocked_id=?) OR (blocker_id=? AND blocked_id=?)',(a,b,b,a)).fetchone())
 def api(self,method,path):
  if method in ('POST','PATCH','DELETE'):
   k=self.client_address[0]+path.split('/')[2] if len(path.split('/'))>2 else self.client_address[0]; t=time.time(); self.rate[k]=[x for x in self.rate.get(k,[]) if x>t-60]
   if len(self.rate[k])>90: return self.json(429,{'error':'Too many requests. Please try again shortly.'})
   self.rate[k].append(t)
  try:
   if path=='/api/health': return self.json(200,{'status':'ok'})
   if path=='/api/auth/me' and method=='GET':
    u=self.user(False); return self.json(200,{'user':profile(db(),u,u['id']) if u else None})
   if path=='/api/auth/signup' and method=='POST':
    x=self.body(); name=str(x.get('displayName','')).strip(); username=str(x.get('username','')).strip(); email=str(x.get('email','')).strip().lower(); pw=str(x.get('password',''))
    if not name or not USERNAME.fullmatch(username) or not EMAIL.fullmatch(email) or len(pw)<10: return self.json(422,{'error':'Use a display name, 3–30 character username, valid email, and password of at least 10 characters.'})
    c=db()
    try: c.execute('INSERT INTO users(username,display_name,email,password_hash,created_at) VALUES(?,?,?,?,?)',(username,name,email,password_hash(pw),now())); c.commit(); u=c.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
    except sqlite3.IntegrityError: c.close(); return self.json(409,{'error':'That email or username is already in use.'})
    c.close(); token=self.session(u); return self.auth_json(201, token, {'user':profile(db(),u,u['id'])})
   if path=='/api/auth/login' and method=='POST':
    x=self.body(); c=db(); u=c.execute('SELECT * FROM users WHERE email=?',(str(x.get('email','')).lower(),)).fetchone(); c.close()
    if not u or not password_ok(str(x.get('password','')),u['password_hash']): return self.json(401,{'error':'Invalid email or password.'})
    if u['status']!='active': return self.json(403,{'error':'This account is not available.'})
    token=self.session(u); return self.auth_json(200, token, {'user':profile(db(),u,u['id'])})
   if path=='/api/auth/logout' and method=='POST':
    token=next((x.split('=',1)[1] for x in self.headers.get('Cookie','').split('; ') if x.startswith('dpboss_session=')),None); c=db(); c.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256((token or '').encode()).hexdigest(),));c.commit();c.close(); self.send_response(204);self.send_header('Set-Cookie','dpboss_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0');self.end_headers();return
   u=self.user(); c=db()
   if path=='/api/feed' and method=='GET':
    posts=c.execute("SELECT p.*,u.username,u.display_name FROM posts p JOIN users u ON p.author_id=u.id WHERE p.deleted_at IS NULL AND u.status='active' AND (p.visibility='public' OR p.author_id=? OR (p.visibility='followers' AND EXISTS(SELECT 1 FROM follows f WHERE f.follower_id=? AND f.following_id=p.author_id AND f.status='accepted'))) AND NOT EXISTS(SELECT 1 FROM blocks b WHERE (b.blocker_id=? AND b.blocked_id=p.author_id) OR (b.blocker_id=p.author_id AND b.blocked_id=?)) ORDER BY p.created_at DESC LIMIT 30",(u['id'],u['id'],u['id'],u['id'])).fetchall()
    return self.json(200,{'posts':[self.post(c,p,u['id']) for p in posts]})
   if path=='/api/posts' and method=='POST':
    x=self.body(); body=str(x.get('body','')).strip(); vis=x.get('visibility','public')
    if not body or len(body)>5000 or vis not in ('public','followers','private'): return self.json(422,{'error':'Post content or visibility is invalid.'})
    cur=c.execute('INSERT INTO posts(author_id,body,visibility,created_at) VALUES(?,?,?,?)',(u['id'],body,vis,now()));c.commit(); p=c.execute('SELECT p.*,u.username,u.display_name FROM posts p JOIN users u ON u.id=p.author_id WHERE p.id=?',(cur.lastrowid,)).fetchone();return self.json(201,{'post':self.post(c,p,u['id'])})
   m=re.fullmatch(r'/api/posts/(\d+)/(like|comments)',path)
   if m and method=='POST':
    pid,action=int(m[1]),m[2]; p=c.execute('SELECT * FROM posts WHERE id=? AND deleted_at IS NULL',(pid,)).fetchone()
    if not p or self.blocked(c,u['id'],p['author_id']): return self.json(404,{'error':'Post unavailable.'})
    if action=='like':
     exists=c.execute('SELECT 1 FROM likes WHERE user_id=? AND post_id=?',(u['id'],pid)).fetchone(); c.execute('DELETE FROM likes WHERE user_id=? AND post_id=?',(u['id'],pid)) if exists else (c.execute('INSERT INTO likes VALUES(?,?,?)',(u['id'],pid,now())),notify(c,p['author_id'],u['id'],'like','post',pid));c.commit();return self.json(200,{'liked':not bool(exists)})
    x=self.body(); body=str(x.get('body','')).strip(); parent=x.get('parentId')
    if not body or len(body)>1000:return self.json(422,{'error':'A comment must contain 1–1000 characters.'})
    q=c.execute('INSERT INTO comments(post_id,author_id,parent_id,body,created_at) VALUES(?,?,?,?,?)',(pid,u['id'],parent,body,now()));notify(c,p['author_id'],u['id'],'comment','post',pid);c.commit();return self.json(201,{'id':q.lastrowid})
   m=re.fullmatch(r'/api/posts/(\d+)',path)
   if m and method=='DELETE':
    r=c.execute('UPDATE posts SET deleted_at=? WHERE id=? AND author_id=? AND deleted_at IS NULL',(now(),int(m[1]),u['id']));c.commit();return self.json(204,{}) if r.rowcount else self.json(404,{'error':'Post unavailable.'})
   m=re.fullmatch(r'/api/users/([^/]+)/(follow|block)',path)
   if m and method=='POST':
    target=c.execute('SELECT * FROM users WHERE username=? COLLATE NOCASE',(m[1],)).fetchone()
    if not target or target['id']==u['id']: return self.json(404,{'error':'User unavailable.'})
    if m[2]=='block': c.execute('INSERT OR IGNORE INTO blocks VALUES(?,?,?)',(u['id'],target['id'],now()));c.execute('DELETE FROM follows WHERE (follower_id=? AND following_id=?) OR (follower_id=? AND following_id=?)',(u['id'],target['id'],target['id'],u['id']));c.commit();return self.json(200,{'blocked':True})
    if self.blocked(c,u['id'],target['id']):return self.json(403,{'error':'This action is not available.'})
    e=c.execute('SELECT 1 FROM follows WHERE follower_id=? AND following_id=?',(u['id'],target['id'])).fetchone()
    if e:c.execute('DELETE FROM follows WHERE follower_id=? AND following_id=?',(u['id'],target['id'])); following=False
    else: status='pending' if target['private'] else 'accepted';c.execute('INSERT INTO follows VALUES(?,?,?,?)',(u['id'],target['id'],status,now()));notify(c,target['id'],u['id'],'follow_request' if status=='pending' else 'follow','user',u['id']);following=True
    c.commit();return self.json(200,{'following':following})
   if path=='/api/notifications' and method=='GET':
    ns=c.execute('SELECT n.*,u.username,u.display_name FROM notifications n LEFT JOIN users u ON u.id=n.actor_id WHERE n.user_id=? ORDER BY n.created_at DESC LIMIT 50',(u['id'],)).fetchall();return self.json(200,{'notifications':[row(x) for x in ns]})
   if path=='/api/notifications/read-all' and method=='POST':c.execute('UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL',(now(),u['id']));c.commit();return self.json(204,{})
   if path=='/api/report' and method=='POST':
    x=self.body(); typ=x.get('targetType'); tid=x.get('targetId'); reason=str(x.get('reason','')).strip()
    if typ not in ('post','comment','user','message') or not isinstance(tid,int) or len(reason)<3:return self.json(422,{'error':'Choose a report target and reason.'})
    c.execute('INSERT INTO reports(reporter_id,target_type,target_id,reason,details,created_at) VALUES(?,?,?,?,?,?)',(u['id'],typ,tid,reason,str(x.get('details',''))[:1000],now()));c.commit();return self.json(201,{'ok':True})
   if path=='/api/messages' and method=='GET':
    cs=c.execute('SELECT c.id, MAX(m.created_at) last_at, MAX(m.body) last_message FROM conversations c JOIN participants p ON p.conversation_id=c.id LEFT JOIN messages m ON m.conversation_id=c.id WHERE p.user_id=? GROUP BY c.id ORDER BY last_at DESC',(u['id'],)).fetchall();return self.json(200,{'conversations':[row(x) for x in cs]})
   if path=='/api/admin/overview' and method=='GET':
    if u['role'] not in ('super_admin','moderator','support'):return self.json(403,{'error':'Administrator access required.'})
    keys={'members':'users','posts':'posts','comments':'comments','messages':'messages','pendingReports':"reports WHERE status='pending'",'activeSubscriptions':"subscriptions WHERE status='active'"}; data={k:c.execute(f'SELECT count(*) FROM {v}').fetchone()[0] for k,v in keys.items()};return self.json(200,{'metrics':data})
   return self.json(404,{'error':'Endpoint not found.'})
  except PermissionError as e:return self.json(401,{'error':str(e)})
  except ValueError as e:return self.json(400,{'error':str(e)})
  except Exception as e: return self.json(500,{'error':'The server could not complete that request.'})
 def auth_json(self,status,token,data):
  raw=json.dumps(data).encode(); self.send_response(status); self.send_header('Set-Cookie',f'dpboss_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000'); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
 def post(self,c,p,viewer):
  d=row(p); d['displayName']=d.pop('display_name');d['likeCount']=c.execute('SELECT count(*) FROM likes WHERE post_id=?',(p['id'],)).fetchone()[0];d['commentCount']=c.execute('SELECT count(*) FROM comments WHERE post_id=? AND deleted_at IS NULL',(p['id'],)).fetchone()[0];d['liked']=bool(c.execute('SELECT 1 FROM likes WHERE post_id=? AND user_id=?',(p['id'],viewer)).fetchone());return d
 def do_GET(self):
  path=urlparse(self.path).path
  if path.startswith('/api/'):return self.api('GET',path)
  self.path='/index.html' if path=='/' or not (ROOT/path.lstrip('/')).exists() else path; return super().do_GET()
 def do_POST(self): self.api('POST',urlparse(self.path).path)
 def do_DELETE(self): self.api('DELETE',urlparse(self.path).path)

if __name__=='__main__': init(); port=int(os.getenv('PORT','8000')); print(f'DP BOSS running on http://127.0.0.1:{port}'); ThreadingHTTPServer(('0.0.0.0',port),App).serve_forever()
