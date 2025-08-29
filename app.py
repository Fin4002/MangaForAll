# app.py — Flask + mysql-connector-python, built for YOUR schema
# Schema used (from your diagram):
#   users(user_id, username, joining_date, no_of_chapters_read, email)
#   user_auth(user_id, password_hash, admin_id)
#   admin(admin_id, name)
#   manga(manga_id, publication_status, Title, Author_name, synopsis, user_id, admin_id)

import os, re, json, urllib.parse
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template, redirect, url_for,
    request, flash, session, abort
)
from werkzeug.security import generate_password_hash, check_password_hash

import mysql.connector
from mysql.connector import pooling

# ---------------------------
# Config
# ---------------------------
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-change-me')

def parse_db_url():
    # Accept DATABASE_URL like: mysql://user:pass@127.0.0.1:3306/mangaforall
    url = os.getenv('DATABASE_URL', 'mysql://root:@127.0.0.1:3306/mangaforall')
    p = urllib.parse.urlparse(url)
    return {
        'user': urllib.parse.unquote(p.username or 'root'),
        'password': urllib.parse.unquote(p.password or ''),
        'host': p.hostname or '127.0.0.1',
        'port': p.port or 3306,
        'database': (p.path or '/mangaforall').lstrip('/'),
        'charset': 'utf8mb4',
        'autocommit': False
    }

DB_CFG = parse_db_url()
POOL = pooling.MySQLConnectionPool(pool_name="mfa_pool", pool_size=5, **DB_CFG)

def get_conn():
    return POOL.get_connection()

def query_all(sql, params=()):
    with get_conn() as cnx:
        with cnx.cursor(dictionary=True) as cur:
            cur.execute(sql, params)
            return cur.fetchall()

def query_one(sql, params=()):
    rows = query_all(sql, params)
    return rows[0] if rows else None

def execute(sql, params=()):
    with get_conn() as cnx:
        with cnx.cursor() as cur:
            cur.execute(sql, params)
            cnx.commit()
            return cur.lastrowid

# ---------------------------
# Paths
# ---------------------------
def resources_root():
    # static/Resources is the warehouse
    return os.path.join(app.static_folder, 'Resources')

# ---------------------------
# Auth helpers strictly per your schema
# ---------------------------
def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    # Join users + user_auth for convenience
    sql = """
        SELECT u.user_id, u.username, u.joining_date, u.no_of_chapters_read, u.email,
               ua.password_hash, ua.admin_id
        FROM users u
        LEFT JOIN user_auth ua ON ua.user_id = u.user_id
        WHERE u.user_id = %s
    """
    return query_one(sql, (uid,))

def is_admin(user_row):
    # In your schema, user_auth.admin_id indicates admin linkage
    return bool(user_row and user_row.get('admin_id'))

def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **k):
        if not current_user():
            flash('Login required', 'warning')
            return redirect(url_for('login', next=request.path))
        return fn(*a, **k)
    return wrapper

def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **k):
        u = current_user()
        if not u or not is_admin(u):
            abort(403)
        return fn(*a, **k)
    return wrapper

# ---------------------------
# Auth routes (users + user_auth)
# ---------------------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        uname = request.form['username'].strip()
        email = request.form['email'].strip().lower()
        pwd   = request.form['password']

        # Ensure unique username/email
        dup = query_one("SELECT 1 FROM users WHERE username=%s OR email=%s", (uname, email))
        if dup:
            flash('User already exists.', 'danger')
            return render_template('register.html')

        # Create user, then user_auth
        with get_conn() as cnx:
            try:
                cur = cnx.cursor()
                cur.execute(
                    "INSERT INTO users (username, joining_date, no_of_chapters_read, email) "
                    "VALUES (%s, %s, %s, %s)",
                    (uname, datetime.utcnow(), 0, email)
                )
                new_uid = cur.lastrowid
                cur.execute(
                    "INSERT INTO user_auth (user_id, password_hash, admin_id) VALUES (%s, %s, %s)",
                    (new_uid, generate_password_hash(pwd), None)
                )
                cnx.commit()
            finally:
                cur.close()
        flash('Registered. Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        uname = request.form['username'].strip()
        pwd   = request.form['password']

        sql = """
          SELECT u.user_id, u.username, ua.password_hash, ua.admin_id
          FROM users u
          LEFT JOIN user_auth ua ON ua.user_id = u.user_id
          WHERE u.username = %s
        """
        row = query_one(sql, (uname,))
        if row and row['password_hash'] and check_password_hash(row['password_hash'], pwd):
            session['user_id'] = row['user_id']
            flash('Welcome back.', 'success')
            return redirect(request.args.get('next') or url_for('index'))
        flash('Invalid credentials.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out.', 'info')
    return redirect(url_for('index'))

# ---------------------------
# Pages
# --------------------------- 
@app.route('/')
def index():
    # show latest or alphabetic manga
    mangas = query_all(f"SELECT manga_id, Title, Author_name, synopsis, publication_status FROM manga ORDER BY Title ASC")
    return render_template('index.html', mangas=mangas, user=current_user())

@app.route('/manga')
def manga_list():
    mangas = query_all("SELECT manga_id, Title, Author_name, synopsis, publication_status FROM manga ORDER BY Title ASC")
    return render_template('manga.html', mangas=mangas, user=current_user())

@app.route('/manga/<int:manga_id>')
def manga_detail(manga_id):
    m = query_one("SELECT * FROM manga WHERE manga_id=%s", (manga_id,))
    if not m:
        abort(404)
    # If you later add chapters/pages tables, you’d query them here.
    return render_template('manga_detail.html', manga=m, chapters=[], user=current_user())

@app.route('/dashboard/admin')
@admin_required
def admin_dashboard():
    users = query_all("SELECT user_id, username, email, joining_date FROM users ORDER BY joining_date DESC")
    return render_template('dash_admin.html', users=users, user=current_user())

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html', user=current_user())

@app.route('/forum')
def forum():
    return render_template('forum.html', user=current_user())

# ---------------------------
# Resources → DB sync (creates manga rows only, per your schema)
# Directory layout:
#   static/Resources/<MangaTitle>/
# We set: Title=<folder>, Author_name='Unknown', synopsis='Imported...', publication_status='ongoing'
# user_id = current user's id if logged in, else NULL
# admin_id = current admin_id if logged in as admin, else NULL
# ---------------------------
IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.gif')

def list_dir_sorted(path):
    try:
        items = os.listdir(path)
    except FileNotFoundError:
        return []
    # natural sort
    def keyfn(s):
        return [int(t) if t.isdigit() else t.lower() for t in re.findall(r'\d+|\D+', s)]
    return sorted(items, key=keyfn)

def ensure_manga_row(title_str, user_row):
    # Does a manga row with this Title exist?
    existing = query_one("SELECT manga_id FROM manga WHERE Title=%s", (title_str,))
    if existing:
        return existing['manga_id'], False

    pub_status = 'ongoing'
    author     = 'Unknown'
    synopsis   = f'Imported from Resources/{title_str}'
    uid        = user_row['user_id'] if user_row else None
    adm        = user_row['admin_id'] if is_admin(user_row) else None

    cols = ["publication_status", "Title", "Author_name", "synopsis", "user_id", "admin_id"]
    vals = [pub_status, title_str, author, synopsis, uid, adm]
    placeholders = ",".join(["%s"]*len(vals))
    new_id = execute(f"INSERT INTO manga ({','.join(cols)}) VALUES ({placeholders})", tuple(vals))
    return new_id, True

@app.post('/content/sync')
@login_required
def sync_from_resources_http():
    user = current_user()
    base = resources_root()
    if not os.path.isdir(base):
        flash('No static/Resources directory found.', 'warning')
        return redirect(url_for('content_dashboard') if is_admin(user) else url_for('index'))

    created = 0
    scanned = 0
    for folder in list_dir_sorted(base):
        path = os.path.join(base, folder)
        if not os.path.isdir(path):
            continue
        scanned += 1
        _, was_new = ensure_manga_row(folder, user)
        if was_new:
            created += 1

    flash(f'Scanned {scanned} folders. Created {created} manga rows.', 'success')
    return redirect(url_for('content_dashboard') if is_admin(user) else url_for('index'))
def natural_sort_keys(s):
    # "ch.2" before "ch.10"
    return [int(t) if t.isdigit() else t.lower() for t in re.findall(r'\d+|\D+', s)]

def parse_manga_txt(txt_path):
    """
    Expected format (single line, comma-separated):
      Author_name, publication_status, title
    Example:
      Eiichiro Oda, ongoing, One Piece
    """
    meta = {"Author_name": "Unknown", "publication_status": "unknown", "Title": None}
    try:
        with open(txt_path, "r", encoding="utf-8") as f:
            line = f.readline().strip()
        # allow either comma-separated or newline-separated just in case
        if "," in line:
            parts = [p.strip() for p in line.split(",")]
        else:
            parts = [p.strip() for p in line.splitlines()]
        # pad to length 3
        while len(parts) < 3:
            parts.append("")
        meta["Author_name"], meta["publication_status"], meta["Title"] = parts[:3]
    except FileNotFoundError:
        pass
    return meta

def read_synopsis(syn_path):
    try:
        with open(syn_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""

def scan_resources_content():
    """
    Walk static/Resources and return a list of manga dicts:
      {
        "Title": ...,
        "Author_name": ...,
        "publication_status": ...,
        "synopsis": ...,
        "cover_url": "/static/Resources/<folder>/cover.jpg" if exists else None,
        "folder": "<folder name>",
        "chapters": ["ch.000", "ch.001", ...]  # sorted naturally
      }
    Sorted by Title (case-insensitive). If Title is missing in manga.txt, fallback to folder name.
    """
    base = resources_root()
    items = []
    if not os.path.isdir(base):
        return items

    for folder in sorted(
        [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))],
        key=lambda s: s.lower()
    ):
        fpath = os.path.join(base, folder)
        meta = parse_manga_txt(os.path.join(fpath, "manga.txt"))
        title = meta.get("Title") or folder

        synopsis = read_synopsis(os.path.join(fpath, "synopsis.txt"))
        cover_fs = os.path.join(fpath, "cover.jpg")
        cover_url = f"/static/Resources/{folder}/cover.jpg" if os.path.isfile(cover_fs) else None

        # chapters = subfolders starting with "ch."
        ch_dirs = [
            d for d in os.listdir(fpath)
            if os.path.isdir(os.path.join(fpath, d)) and d.lower().startswith("ch.")
        ]
        ch_dirs.sort(key=natural_sort_keys)

        items.append({
            "Title": title,
            "Author_name": meta.get("Author_name") or "Unknown",
            "publication_status": meta.get("publication_status") or "unknown",
            "synopsis": synopsis,
            "cover_url": cover_url,
            "folder": folder,
            "chapters": ch_dirs
        })

    # final sort by Title in case manga.txt changed it from the folder name
    items.sort(key=lambda x: (x["Title"] or "").lower())
    return items

# Optional: simple content dashboard for non-ORM world
@app.route('/dashboard/content')
@login_required
def content_dashboard():
    u = current_user()
    mangas = scan_resources_content()
    return render_template('dash_content.html', mangas=mangas, user=u)


# ---------------------------
# Admin: create default admin if NOT present
# This creates: admin(name='Admin'), users + user_auth linked to that admin.
# ---------------------------
@app.post('/admin/seed')
def seed_admin():
    # If an admin-linked user already exists, bail
    row = query_one("""
        SELECT u.user_id FROM users u
        JOIN user_auth ua ON ua.user_id = u.user_id
        WHERE ua.admin_id IS NOT NULL
        LIMIT 1
    """)
    if row:
        flash('An admin already exists.', 'info')
        return redirect(url_for('admin_dashboard'))

    with get_conn() as cnx:
        cur = cnx.cursor()
        try:
            # 1) create admin row
            cur.execute("INSERT INTO admin (name) VALUES (%s)", ('Admin',))
            admin_id = cur.lastrowid
            # 2) create user
            cur.execute(
                "INSERT INTO users (username, joining_date, no_of_chapters_read, email) "
                "VALUES (%s, %s, %s, %s)",
                ('admin', datetime.utcnow(), 0, 'admin@example.com')
            )
            uid = cur.lastrowid
            # 3) create auth linking to admin
            cur.execute(
                "INSERT INTO user_auth (user_id, password_hash, admin_id) VALUES (%s, %s, %s)",
                (uid, generate_password_hash('admin123'), admin_id)
            )
            cnx.commit()
            flash('Admin created: admin / admin123', 'success')
        finally:
            cur.close()
    return redirect(url_for('login'))

# ---------------------------
# Entrypoint
# ---------------------------
if __name__ == '__main__':
    app.run(debug=True)
