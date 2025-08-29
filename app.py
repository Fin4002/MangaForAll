# app.py
import os, json, re
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, redirect, url_for,
    request, flash, session, abort
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

from sqlalchemy.ext.automap import automap_base
from sqlalchemy import MetaData, inspect, or_


# ---------------------------
# Config
# ---------------------------
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-change-me')

# Point to your XAMPP MySQL. Change DB/user/pass as needed.
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URL',
    'mysql+pymysql://root:@127.0.0.1:3306/mangaforall?charset=utf8mb4'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


# ---------------------------
# Automap existing schema
# ---------------------------
metadata = MetaData()
with app.app_context():
    metadata.reflect(bind=db.engine)

Base = automap_base(metadata=metadata)
Base.prepare()

# Resolve table -> class with common fallbacks
def map_class(*names):
    for n in names:
        try:
            return getattr(Base.classes, n)
        except AttributeError:
            continue
    return None

User    = map_class('users', 'user', 'tbl_users', 'account')
Manga   = map_class('manga', 'mangas', 'tbl_manga', 'manga_list')
Chapter = map_class('chapters', 'chapter', 'tbl_chapters')

if User is None:
    raise RuntimeError("Could not find a users table to map. "
                       "Expected one of: users, user, tbl_users, account")

# Column helpers that tolerate different names
def col(model, candidates):
    for name in candidates:
        if hasattr(model, name):
            return getattr(model, name)
    return None

def pk_column(model):
    # pick first PK column
    t = model.__table__
    pks = list(t.primary_key.columns)
    return pks[0] if pks else None

USER_ID     = pk_column(User)
USER_NAME   = col(User, ['username', 'user_name', 'name', 'uname', 'login'])
USER_EMAIL  = col(User, ['email', 'mail', 'email_address'])
USER_ROLE   = col(User, ['role', 'user_role', 'type', 'level'])
USER_PASS   = col(User, ['password_hash', 'password', 'pass_hash', 'passwd', 'pwd'])

MANGA_ID    = pk_column(Manga)     if Manga   else None
MANGA_TITLE = col(Manga, ['title', 'name'])
MANGA_AUTHOR= col(Manga, ['author', 'writer'])
MANGA_DESC  = col(Manga, ['description', 'desc', 'summary'])
MANGA_COVER = col(Manga, ['cover_url', 'cover', 'cover_path'])

CH_ID       = pk_column(Chapter)   if Chapter else None
CH_MANGA_ID = col(Chapter, ['manga_id', 'mangaId', 'manga_id_fk'])
CH_NUMBER   = col(Chapter, ['number', 'chapter_no', 'chap_no', 'no', 'num'])
CH_TITLE    = col(Chapter, ['title', 'name'])
CH_PAGES    = col(Chapter, ['pages_json', 'pages', 'images_json'])


# ---------------------------
# Auth helpers
# ---------------------------
def get_user_by_pk(uid):
    if uid is None:
        return None
    # db.session.get works with column object + value only in SA 2.0 for models, so filter by pk
    return db.session.query(User).filter(pk_column(User) == uid).first()

def current_user():
    uid = session.get('uid')
    return get_user_by_pk(uid)

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            flash('Login required', 'warning')
            return redirect(url_for('login', next=request.path))
        return fn(*args, **kwargs)
    return wrapper

def normalize_role(value):
    if value is None:
        return ''
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, int):
        # crude mapping for numeric roles if your DB uses them
        mapping = {0: 'member', 1: 'moderator', 2: 'content', 3: 'admin'}
        return mapping.get(value, str(value))
    return str(value).lower()

def role_required(*roles):
    want = {r.lower() for r in roles}
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                abort(403)
            user_role = normalize_role(getattr(user, USER_ROLE.key) if USER_ROLE is not None else '')
            if user_role not in want:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator

# Password checker that supports modern hashes and legacy md5/sha1
HEX_RE = re.compile(r'^[0-9a-fA-F]+$')

def is_md5(s):
    return isinstance(s, str) and len(s) == 32 and HEX_RE.match(s)

def is_sha1(s):
    return isinstance(s, str) and len(s) == 40 and HEX_RE.match(s)

def check_and_upgrade_password(user, plain_pwd):
    if USER_PASS is None:
        return False
    stored = getattr(user, USER_PASS.key, None)
    if not stored:
        return False

    # Modern werkzeug hash
    try:
        if stored.startswith('pbkdf2:') or stored.startswith('scrypt:'):
            if check_password_hash(stored, plain_pwd):
                return True
    except Exception:
        pass

    # Legacy MD5 / SHA1 compatibility, then upgrade
    try:
        import hashlib
        if is_md5(stored):
            if hashlib.md5(plain_pwd.encode()).hexdigest() == stored:
                # upgrade
                new_hash = generate_password_hash(plain_pwd)
                setattr(user, USER_PASS.key, new_hash)
                db.session.commit()
                return True
        if is_sha1(stored):
            if hashlib.sha1(plain_pwd.encode()).hexdigest() == stored:
                new_hash = generate_password_hash(plain_pwd)
                setattr(user, USER_PASS.key, new_hash)
                db.session.commit()
                return True
    except Exception:
        pass

    # Last try: maybe it is a plain text column (yikes)
    if stored == plain_pwd:
        try:
            new_hash = generate_password_hash(plain_pwd)
            setattr(user, USER_PASS.key, new_hash)
            db.session.commit()
        except Exception:
            pass
        return True
    return False


# ---------------------------
# Routes
# ---------------------------
@app.route('/')
def index():
    mangas = []
    if Manga:
        q = db.session.query(Manga)
        if MANGA_TITLE is not None:
            q = q.order_by(MANGA_TITLE.asc())
        elif MANGA_ID is not None:
            q = q.order_by(MANGA_ID.desc())
        mangas = q.all()
    return render_template('index.html', mangas=mangas, user=current_user())

@app.route('/manga')
def manga_list():
    mangas = []
    if Manga:
        q = db.session.query(Manga)
        if MANGA_TITLE is not None:
            q = q.order_by(MANGA_TITLE.asc())
        mangas = q.all()
    return render_template('manga.html', mangas=mangas, user=current_user())

@app.route('/manga/<int:manga_id>')
def manga_detail(manga_id):
    if not Manga:
        abort(404)
    m = db.session.query(Manga).filter(MANGA_ID == manga_id).first() if MANGA_ID is not None else None
    if not m:
        abort(404)

    chapters = []
    if Chapter and CH_MANGA_ID is not None:
        q = db.session.query(Chapter).filter(CH_MANGA_ID == manga_id)
        if CH_NUMBER is not None:
            q = q.order_by(CH_NUMBER.asc())
        chapters = q.all()

    return render_template('manga_detail.html', manga=m, chapters=chapters, user=current_user())

@app.route('/reader/<int:chapter_id>')
def reader(chapter_id):
    if not Chapter:
        abort(404)
    ch = db.session.query(Chapter).filter(CH_ID == chapter_id).first() if CH_ID is not None else None
    if not ch:
        abort(404)
    pages = []
    if CH_PAGES is not None:
        raw = getattr(ch, CH_PAGES.key)
        try:
            pages = json.loads(raw) if raw else []
        except Exception:
            pages = []
    return render_template('reader.html', chapter=ch, pages=pages, user=current_user())

@app.route('/forum')
def forum():
    return render_template('forum.html', user=current_user())

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html', user=current_user())

@app.route('/dashboard')
@login_required
def dashboard():
    user = current_user()
    role = normalize_role(getattr(user, USER_ROLE.key) if USER_ROLE is not None else '')
    if role == 'admin':
        return redirect(url_for('admin_dashboard'))
    if role == 'moderator':
        return redirect(url_for('moderator_dashboard'))
    if role == 'content':
        return redirect(url_for('content_dashboard'))
    return redirect(url_for('user_dashboard'))

@app.route('/dashboard/user')
@login_required
def user_dashboard():
    return render_template('dash_user.html', user=current_user())

@app.route('/dashboard/admin')
@role_required('admin')
def admin_dashboard():
    users = db.session.query(User).order_by(
        (col(User, ['created_at', 'created', 'createdon']) or USER_ID).desc()
    ).all()
    return render_template('dash_admin.html', users=users, user=current_user())

@app.route('/dashboard/moderator')
@role_required('moderator', 'admin')
def moderator_dashboard():
    return render_template('dash_moderator.html', user=current_user())

@app.route('/dashboard/content')
@role_required('content', 'admin')
def content_dashboard():
    mangas = []
    if Manga:
        mangas = db.session.query(Manga).all()
    return render_template('dash_content.html', mangas=mangas, user=current_user())


# ---------------------------
# Auth
# ---------------------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    # Only meaningful if your users table allows inserts and has expected columns
    if request.method == 'POST':
        if not all([USER_NAME, USER_EMAIL, USER_PASS]):
            flash('Registration is disabled: users table lacks expected columns.', 'danger')
            return render_template('register.html')

        uname = request.form['username'].strip()
        email = request.form['email'].strip().lower()
        pwd   = request.form['password']

        # Uniqueness check
        exists = db.session.query(User).filter(
            or_(USER_NAME == uname, USER_EMAIL == email)
        ).first()
        if exists:
            flash('User already exists.', 'danger')
            return render_template('register.html')

        # Build instance
        u = User()
        setattr(u, USER_NAME.key, uname)
        setattr(u, USER_EMAIL.key, email)
        if USER_ROLE is not None:
            setattr(u, USER_ROLE.key, 'member')
        setattr(u, USER_PASS.key, generate_password_hash(pwd))

        db.session.add(u)
        db.session.commit()
        flash('Registered. Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if not USER_NAME or not USER_PASS:
            flash('Login is unavailable: users table lacks expected columns.', 'danger')
            return render_template('login.html')

        uname = request.form['username'].strip()
        pwd   = request.form['password']

        user = db.session.query(User).filter(USER_NAME == uname).first()
        if user and check_and_upgrade_password(user, pwd):
            # find PK value to stash in session
            uid_value = None
            if USER_ID is not None:
                uid_value = getattr(user, USER_ID.key)
            session['uid'] = uid_value
            flash('Welcome back.', 'success')
            nxt = request.args.get('next') or url_for('index')
            return redirect(nxt)

        flash('Invalid credentials.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('uid', None)
    flash('Logged out.', 'info')
    return redirect(url_for('index'))


# ---------------------------
# Safe admin seed (no schema changes)
# ---------------------------
from sqlalchemy import inspect as _insp

@app.cli.command('seed-admin')
def seed_admin():
    """Insert an admin user if none exists. Does NOT create tables."""
    insp = _insp(db.engine)
    tables = set(insp.get_table_names())
    # try common user table names
    if 'users' not in tables and 'user' not in tables and 'tbl_users' not in tables and 'account' not in tables:
        print('No users table found. Not seeding.')
        return

    if not USER_NAME or not USER_PASS:
        print('Users table lacks username/password columns. Not seeding.')
        return

    existing = db.session.query(User).filter(USER_NAME == 'admin').first()
    if existing:
        print('Admin already exists.')
        return

    admin = User()
    setattr(admin, USER_NAME.key, 'admin')
    if USER_EMAIL:
        setattr(admin, USER_EMAIL.key, 'admin@example.com')
    if USER_ROLE:
        setattr(admin, USER_ROLE.key, 'admin')
    setattr(admin, USER_PASS.key, generate_password_hash('admin123'))
    db.session.add(admin)
    db.session.commit()
    print('Admin created: admin / admin123')


# ---------------------------
# App entrypoint
# ---------------------------
if __name__ == '__main__':
    # DO NOT call db.create_all() — your tables already exist.
    app.run(debug=True)
