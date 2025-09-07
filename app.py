# app.py — Flask + mysql-connector-python, built to match your schema
# Schema used (from your diagram / dump):
#   users(user_id, username, joining_date, no_of_chapters_read, email)
#   user_auth(user_id, password_hash, admin_id)
#   admin(admin_id, name)
#   manga(manga_id, publication_status, Title, Author_name, synopsis, user_id, admin_id)
import filetype , mimetypes
import os, re, json, urllib.parse
from datetime import datetime, timedelta
from functools import wraps
from flask import (
    Flask, render_template, render_template_string, redirect, url_for,
    request, flash, session, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from flask import send_file, Response
import mysql.connector
from mysql.connector import pooling
import os, time, filetype
from flask import Flask, request, redirect, url_for, session, flash, g, abort
from urllib.parse import urlparse
import glob, time
from flask import (
    Flask, render_template, render_template_string, redirect, url_for,
    request, flash, session, abort, Response 
)


import os, time
from werkzeug.utils import secure_filename
from flask import session, redirect, url_for, flash, request

import re


# ---------------------------
# Config
# ---------------------------
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-change-me')

# uploads (for forum images saved in DB as BLOB we still check type/size)
UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB

# ---------------------------
# DB Pool
# ---------------------------
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

def query_all(query, args=()):
    conn = POOL.get_connection()
    cur = conn.cursor(dictionary=True)   # <-- important
    cur.execute(query, args)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

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
# Paths and FS helpers
# Paths
# ---------------------------
def resources_root():
    # static/Resources is the manga warehouse
    return os.path.join(app.static_folder, 'Resources')

IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.gif')

def natural_sort_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.findall(r'\d+|\D+', s)]

def parse_manga_txt(txt_path):
    meta = {"Author_name": "Unknown", "publication_status": "unknown", "Title": None}
    try:
        with open(txt_path, "r", encoding="utf-8") as f:
            line = f.readline().strip()
        if "," in line:
            parts = [p.strip() for p in line.split(",")]
        else:
            parts = [p.strip() for p in line.splitlines()]
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

def is_chapter_folder(name: str) -> bool:
    lname = name.lower()
    return lname.startswith("ch") or lname.startswith("chapter")

def chapter_sort_key(name: str):
    m = re.search(r'\d+', name)
    return int(m.group()) if m else name.casefold()

def list_dir_sorted(path):
    try:
        items = os.listdir(path)
    except FileNotFoundError:
        return []
    return sorted(items, key=natural_sort_key)

def list_images(folder_path):
    imgs = []
    try:
        for name in os.listdir(folder_path):
            ext = os.path.splitext(name)[1].lower()
            if ext in IMAGE_EXTS:
                imgs.append(name)
    except FileNotFoundError:
        return []
    imgs.sort(key=natural_sort_key)
    return imgs

# ---------------------------
# Auth helpers
# ---------------------------

def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    sql = """
        SELECT u.user_id, u.username, u.joining_date, u.no_of_chapters_read, u.email,
               u.Profile_pic,
               ua.password_hash, ua.admin_id
        FROM users u
        LEFT JOIN user_auth ua ON ua.user_id = u.user_id
        WHERE u.user_id = %s
    """
    return query_one(sql, (uid,))


def is_admin(user_row):
    # check if user_row has admin_id or not
    return bool(user_row and user_row.get('admin_id'))

def is_content_manager(user_row):
    """
    True only if the user's admin_id is present in Content_manager.
    """
    if not user_row or not user_row.get('admin_id'):
        return False
    row = query_one("SELECT 1 FROM Content_manager WHERE admin_id=%s", (user_row['admin_id'],))
    return bool(row)

def is_moderator(user_row):
    if not user_row:
        return False
    if is_admin(user_row):
        return True
    adm = user_row.get('admin_id')
    if not adm:
        return False
    row = query_one("SELECT 1 FROM moderator WHERE admin_id=%s", (adm,))
    return bool(row)

def user_is_banned(user_row):
    if not user_row or not user_row.get("is_banned"):
        return False
    until = user_row.get("ban_until")
    if until and isinstance(until, datetime) and until < datetime.utcnow():
        return False
    return True

def user_id_is_banned(user_id: int) -> bool:
    if not user_id:
        return False
    row = query_one("SELECT is_banned, ban_until FROM users WHERE user_id=%s", (user_id,))
    if not row or not row.get("is_banned"):
        return False
    until = row.get("ban_until")
    if until and isinstance(until, datetime) and until < datetime.utcnow():
        return False
    return True

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

def content_manager_required(fn):
    @wraps(fn)
    def wrapper(*a, **k):
        u = current_user()
        if not u:
            flash('Login required', 'warning')
            return redirect(url_for('login', next=request.path))
        if not is_content_manager(u):
            abort(403)
        return fn(*a, **k)
    return wrapper

def moderator_required(fn):
    @wraps(fn)
    def wrapper(*a, **k):
        u = current_user()
        if not u:
            flash('Login required', 'warning')
            return redirect(url_for('login', next=request.path))
        if not is_moderator(u):
            abort(403)
        return fn(*a, **k)
    return wrapper

@app.context_processor
def inject_everything():
    # one place to inject helpers into Jinja
    return dict(
        user=current_user(),
        is_admin=is_admin,
        is_content_manager=is_content_manager,
        is_moderator=is_moderator,
        user_is_banned=user_is_banned,
        user_id_is_banned=user_id_is_banned,
    )

# ---------------------------
# Auth routes
# ---------------------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        uname = request.form['username'].strip()
        email = request.form['email'].strip().lower()
        pwd   = request.form['password']

        # checks for existing username/email
        # Ensure unique username/email
        dup = query_one("SELECT 1 FROM users WHERE username=%s OR email=%s", (uname, email))
        if dup:
            flash('User already exists.', 'danger')
            return render_template('register.html')

        with get_conn() as cnx:
            cur = cnx.cursor()
            try:
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
# Public pages
# ---------------------------
# Pages (public site)
# --------------------------- 
@app.route('/')
def index():
    mangas = query_all("""
        SELECT manga_id, Title, Author_name, synopsis, publication_status, CoverPath
        FROM manga
        ORDER BY manga_id DESC
    """)
    return render_template('index.html', mangas=mangas, user=current_user())

@app.route('/manga', methods=['GET'])
def manga_list():
    q = (request.args.get('q') or '').strip()
    base_sql = """
        SELECT manga_id, Title, Author_name, synopsis, publication_status, CoverPath
        FROM manga
    """
    params = ()
    if q:
        like = f"%{q}%"
        sql = base_sql + """
            WHERE Title LIKE %s
               OR Author_name LIKE %s
               OR synopsis LIKE %s
            ORDER BY Title ASC
        """
        params = (like, like, like)
    else:
        sql = base_sql + " ORDER BY Title ASC"
    mangas = query_all(sql, params)
    return render_template('manga.html', mangas=mangas, q=q, user=current_user())
@app.route('/manga/<int:manga_id>')
def manga_detail(manga_id):
    m = query_one("SELECT * FROM manga WHERE manga_id=%s", (manga_id,))
    if not m:
        abort(404)

    db_title  = (m.get('Title') or '').strip()
    db_author = (m.get('Author_name') or '').strip()
    coverpath = (m.get('CoverPath') or '').strip()

    # infer folder from CoverPath or Title
    folder = None
    if coverpath.startswith("Resources/"):
        parts = coverpath.split("/")
        if len(parts) >= 2 and parts[1]:
            folder = parts[1]
    if not folder and db_title:
        base = resources_root()
        if os.path.isdir(base):
            for d in os.listdir(base):
                if os.path.isdir(os.path.join(base, d)) and d.lower() == db_title.lower():
                    folder = d
                    break

    base = resources_root()
    meta = {"Author_name": "", "publication_status": "", "Title": ""}
    synopsis_text = (m.get("synopsis") or "").strip()
    u=current_user()
    favorited = is_favorited(u["user_id"], manga_id) if u else False
    if folder:
        fpath = os.path.join(base, folder)
        meta = parse_manga_txt(os.path.join(fpath, "manga.txt")) or meta
        if not synopsis_text:
            syn_path = os.path.join(fpath, "synopsis.txt")
            if os.path.isfile(syn_path):
                synopsis_text = read_synopsis(syn_path)

    title_final  = db_title or meta.get("Title") or folder or "Untitled"
    author_final = db_author or meta.get("Author_name") or "Unknown"
    status_final = m.get("publication_status") or meta.get("publication_status") or "unknown"

    cover_url = None
    if folder:
        cover_fs = os.path.join(base, folder, "Cover.jpg")
        if os.path.isfile(cover_fs):
            cover_url = f"/static/Resources/{folder}/Cover.jpg"
    if not cover_url and coverpath:
        cover_url = f"/static/{coverpath}"

    chapters = []
    if folder:
        fpath = os.path.join(base, folder)
        if os.path.isdir(fpath):
            chapters = [
                d for d in os.listdir(fpath)
                if os.path.isdir(os.path.join(fpath, d)) and is_chapter_folder(d)
            ]
            chapters.sort(key=chapter_sort_key)

    manga_ctx = dict(m)
    manga_ctx["Title"] = title_final
    manga_ctx["Author_name"] = author_final
    manga_ctx["publication_status"] = status_final
    manga_ctx["synopsis"] = synopsis_text

    return render_template(
        "manga_detail.html",
        manga=manga_ctx,
        folder=folder,
        cover_url=cover_url,
        chapters=chapters,
        meta=meta,
        favorited=favorited,
        user=current_user()
    )

@app.route('/profile')
@login_required
def profile():
    u = current_user()
    favorites = user_favorites(u["user_id"])
    return render_template("profile.html", user=u, favorites=favorites)

# ---------------------------
# Resources scanning helpers
# ---------------------------
IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.gif')

def natural_sort_keys(s):
    #sorts manga chapter folders
    return [int(t) if t.isdigit() else t.lower() for t in re.findall(r'\d+|\D+', s)]

def parse_manga_txt(txt_path):
    meta = {"Author_name": "Unknown", "publication_status": "unknown", "Title": None}
    try:
        with open(txt_path, "r", encoding="utf-8") as f:
            line = f.readline().strip()
        if "," in line:
            parts = [p.strip() for p in line.split(",")]
        else:
            parts = [p.strip() for p in line.splitlines()]
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
#checks if chapter folder is in ch format or chapter format
def is_chapter_folder(name: str) -> bool:
    lname = name.lower()
    return lname.startswith("ch") or lname.startswith("chapter")
#sorts based on the integer value ch or chapter 
def chapter_sort_key(name: str):
    m = re.search(r'\d+', name)
    return int(m.group()) if m else name.casefold()
#Accept "ch.001", "ch1", "chapter 1", "Chapter-12", etc.
def is_chapter_folder(name: str) -> bool:
    lname = name.lower()
    return lname.startswith("ch") or lname.startswith("chapter")

def scan_resources_content():
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
        cover_fs = os.path.join(fpath, "Cover.jpg")
        cover_url = f"/static/Resources/{folder}/Cover.jpg" if os.path.isfile(cover_fs) else None
        ch_dirs = [
            d for d in os.listdir(fpath)
            if os.path.isdir(os.path.join(fpath, d)) and is_chapter_folder(d)
        ]
        ch_dirs.sort(key=chapter_sort_key)
        items.append({
            "Title": title,
            "Author_name": meta.get("Author_name") or "Unknown",
            "publication_status": meta.get("publication_status") or "unknown",
            "synopsis": synopsis,
            "cover_url": cover_url,
            "folder": folder,
            "chapters": ch_dirs
        })
    items.sort(key=lambda x: (x["Title"] or "").lower())
    return items

@app.route('/dashboard/content')
@content_manager_required
def content_dashboard():
    u = current_user()
    mangas = scan_resources_content()
    return render_template('dash_content.html', mangas=mangas, user=u)

@app.route('/dashboard/content/<folder>')
@content_manager_required
def content_detail(folder):
    u = current_user()
    base = resources_root()
    fpath = os.path.join(base, folder)
    if not os.path.isdir(fpath):
        flash("Folder not found.", "danger")
        return redirect(url_for('content_dashboard'))

    meta = parse_manga_txt(os.path.join(fpath, "manga.txt"))
    title = meta.get("Title") or folder
    synopsis = read_synopsis(os.path.join(fpath, "synopsis.txt"))
    cover_fs = os.path.join(fpath, "Cover.jpg")
    cover_url = f"/static/Resources/{folder}/Cover.jpg" if os.path.isfile(cover_fs) else None

    chapters = [
        d for d in os.listdir(fpath)
        if os.path.isdir(os.path.join(fpath, d)) and is_chapter_folder(d)
    ]
    chapters.sort(key=chapter_sort_key)

    existing = query_one("SELECT manga_id FROM manga WHERE Title=%s", (title,))
    approved = bool(existing)

    return render_template(
        "content_detail.html",
        user=u,
        folder=folder,
        meta=meta,
        title=title,
        synopsis=synopsis,
        cover_url=cover_url,
        chapters=chapters,
        approved=approved
    )

@app.route('/dashboard/content/<folder>/approve', methods=['POST', 'GET'])
@content_manager_required
def content_approve(folder):
    u = current_user()
    base = resources_root()
    fpath = os.path.join(base, folder)
    if not os.path.isdir(fpath):
        flash("Folder not found in static/Resources.", "danger")
        return redirect(url_for('content_detail', folder=folder))

    meta = parse_manga_txt(os.path.join(fpath, "manga.txt"))
    title = (meta.get("Title") or folder).strip()
    synopsis = read_synopsis(os.path.join(fpath, "synopsis.txt"))

    cover_rel = None
    cover_fs = os.path.join(fpath, "Cover.jpg")
    if os.path.isfile(cover_fs):
        cover_rel = f"Resources/{folder}/Cover.jpg"

    exists = query_one("SELECT manga_id, CoverPath FROM manga WHERE Title=%s", (title,))
    if exists:
        if cover_rel and not exists.get("CoverPath"):
            try:
                execute("UPDATE manga SET CoverPath=%s WHERE manga_id=%s", (cover_rel, exists["manga_id"]))
                flash("Already approved. CoverPath was missing and is now set.", "info")
            except Exception as e:
                flash(f"Already approved; failed to set CoverPath: {e}", "warning")
        else:
            flash("Already approved.", "info")
        return redirect(url_for('content_detail', folder=folder))

    cols = ["publication_status", "Title", "Author_name", "synopsis"]
    vals = [
        meta.get("publication_status") or "unknown",
        title,
        meta.get("Author_name") or "Unknown",
        synopsis
    ]
    if cover_rel:
        cols.append("CoverPath")
        vals.append(cover_rel)
    if u and u.get("user_id") is not None:
        cols.append("user_id")
        vals.append(u["user_id"])
    if u and is_admin(u) and u.get("admin_id") is not None:
        cols.append("admin_id")
        vals.append(u["admin_id"])

    placeholders = ",".join(["%s"] * len(vals))
    sql = f"INSERT INTO manga ({','.join(cols)}) VALUES ({placeholders})"

    try:
        execute(sql, tuple(vals))
        flash("Manga approved and stored in database (with cover).", "success")
    except Exception as e:
        flash(f"DB insert failed: {e}", "danger")

    return redirect(url_for('content_detail', folder=folder))

@app.route('/dashboard/content/<folder>/remove', methods=['POST'])
@content_manager_required
def content_remove(folder):
    base = resources_root()
    fpath = os.path.join(base, folder)
    cover_rel = f"Resources/{folder}/Cover.jpg"
    row = query_one("SELECT manga_id FROM manga WHERE CoverPath=%s", (cover_rel,))
    if not row:
        meta = parse_manga_txt(os.path.join(fpath, "manga.txt"))
        title = (meta.get("Title") or folder).strip()
        row = query_one("SELECT manga_id FROM manga WHERE Title=%s", (title,))
    if row:
        try:
            execute("DELETE FROM manga WHERE manga_id=%s", (row["manga_id"],))
            flash("Manga removed from database. Files were left untouched in static/Resources.", "success")
        except Exception as e:
            flash(f"Failed to delete from database: {e}", "danger")
    else:
        flash("No approved database record found for this folder. Nothing deleted.", "info")
    return redirect(url_for('content_dashboard'))

# ---------------------------
# Reader
# ---------------------------
@app.route('/reader/<folder>/<chapter>')
def reader(folder, chapter):
    base = resources_root()
    chapter_dir = os.path.join(base, folder, chapter)
    if not os.path.isdir(chapter_dir):
        abort(404)

    files = list_images(chapter_dir)
    pages = [f"/static/Resources/{folder}/{chapter}/{fn}" for fn in files]

    manga_dir = os.path.join(base, folder)
    siblings = [
        d for d in os.listdir(manga_dir)
        if os.path.isdir(os.path.join(manga_dir, d)) and is_chapter_folder(d)
    ]
    siblings.sort(key=chapter_sort_key)

    try:
        idx = siblings.index(chapter)
    except ValueError:
        idx = -1
    prev_ch = siblings[idx - 1] if idx > 0 else None
    next_ch = siblings[idx + 1] if 0 <= idx < len(siblings) - 1 else None

    meta = parse_manga_txt(os.path.join(manga_dir, "manga.txt"))
    title = meta.get("Title") or folder

    _num = re.search(r'\d+', chapter)
    chapter_ctx = {"number": _num.group() if _num else chapter, "title": f"{title} · {chapter}"}
    # --- increment chapter count for the logged-in user ---
    u = current_user()
    if u:
        try:
            execute(
                "UPDATE users SET no_of_chapters_read = COALESCE(no_of_chapters_read, 0) + 1 WHERE user_id=%s",
                (u["user_id"],)
            )
        except Exception as e:
            # Don't break the reader if the DB update fails
            print("Failed to update chapter count:", e)

    return render_template("reader.html", folder=folder, chapter=chapter_ctx, pages=pages,
                           prev_chapter=prev_ch, next_chapter=next_ch,chapters=siblings)

# ---------------------------
# Resources → DB sync (manual)
# ---------------------------
def ensure_manga_row(title_str, user_row):
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



#########============================######

import os
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


dbconfig = {
    "host": "127.0.0.1",
    "user": "root",
    "password": "",
    "database": "mangaforall"
}

POOL = pooling.MySQLConnectionPool(pool_name="mypool", pool_size=5, **dbconfig)

def get_all_posts():
    conn = POOL.get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM forum_posts ORDER BY date_posted DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

from werkzeug.utils import secure_filename

# Forum: list posts
@app.route('/forum')
def forum():
    # Get posts
    posts = query_all("""
        SELECT
            f.post_id,
            f.title,
            f.content,
            f.image,
            u.user_id   AS author_id,
            u.username  AS author
        FROM forum_posts f
        LEFT JOIN users u ON u.user_id = f.user_id
        ORDER BY f.post_id DESC
    """)


    # Get Top 10 contributors (users with the most posts + comments)
    top_contributors = query_all("""
        SELECT u.user_id, u.username AS author, SUM(t.cnt) AS total_contributions
        FROM (
            SELECT user_id, COUNT(*) AS cnt
            FROM forum_posts
            WHERE user_id IS NOT NULL
            GROUP BY user_id
            UNION ALL
            SELECT user_id, COUNT(*) AS cnt
            FROM forum_comments
            WHERE user_id IS NOT NULL
            GROUP BY user_id
        ) AS t
        JOIN users u ON u.user_id = t.user_id
        GROUP BY u.user_id, u.username
        ORDER BY total_contributions DESC
        LIMIT 10
    """)

    comments_by_post = {}
    if posts:
        ids = [p["post_id"] for p in posts]
        placeholders = ",".join(["%s"] * len(ids))
        rows = query_all(f"""
            SELECT
                fc.post_id,
                fc.comment_id,
                fc.content,
                u.username,
                u.user_id
            FROM forum_comments fc
            LEFT JOIN users u ON u.user_id = fc.user_id
            WHERE fc.post_id IN ({placeholders})
            ORDER BY fc.comment_id ASC
        """, tuple(ids))


        for r in rows:
            comments_by_post.setdefault(r["post_id"], []).append(r)

    return render_template("forum.html",
                           posts=posts,
                           comments_by_post=comments_by_post,
                           top_contributors=top_contributors,
                           user=current_user())

@app.route("/forum/new", methods=["GET", "POST"])
@login_required
def new_post():
    u = current_user()
    if user_is_banned(u):
        flash("You are banned and cannot create posts.", "danger")
        return redirect(url_for("forum"))
    if request.method == "POST":
        title   = request.form["title"].strip()
        content = request.form["content"].strip()
        author  = u["username"]

        image_bytes = None
        image_mime  = None
        file = request.files.get("image")
        if file and file.filename:
            if not (file.mimetype or "").startswith("image/"):
                flash("Only image files are allowed.", "warning")
                return redirect(url_for("new_post"))
            image_bytes = file.read()
            image_mime  = file.mimetype

        execute(
            """
            INSERT INTO forum_posts (title, content, author, image, image_mime, user_id, admin_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                title, content, author,
                image_bytes, image_mime,
                u["user_id"],
                u["admin_id"] if is_admin(u) else None,
            ),
        )
        flash("Post created!", "success")
        return redirect(url_for("forum"))
    return render_template("new_post.html", user=u)

@app.route("/forum/<int:post_id>", methods=["GET", "POST"])
def post_detail(post_id):
    post = query_one("SELECT * FROM forum_posts WHERE post_id=%s", (post_id,))
    if not post:
        abort(404)

    # Helper to render either full page or modal partial
    def render_partial_or_full():
        is_partial = request.args.get("partial") or request.headers.get("X-Requested-With") == "fetch"
        template = "post_detail_modal.html" if is_partial else "post_detail.html"

        # Include commenter user_id so we can render their avatars
        comments = query_all(
            """
            SELECT
                fc.comment_id,
                fc.content,
                fc.post_id,
                u.username,
                u.user_id
            FROM forum_comments fc
            LEFT JOIN users u ON u.user_id = fc.user_id
            WHERE fc.post_id = %s
            ORDER BY fc.comment_id ASC
            """,
            (post_id,)
        )

        return render_template(template, post=post, comments=comments, user=current_user())

    if request.method == "POST":
        u = current_user()
        if not u:
            flash("Login required to comment.", "warning")
            return redirect(url_for("login", next=request.path))
        if user_is_banned(u):
            if request.args.get("partial") or request.headers.get("X-Requested-With") == "fetch":
                flash("You are banned and cannot comment.", "danger")
                return render_partial_or_full()
            flash("You are banned and cannot comment.", "danger")
            return redirect(url_for("post_detail", post_id=post_id))

        content = (request.form.get("content") or "").strip()
        if not content:
            if request.args.get("partial") or request.headers.get("X-Requested-With") == "fetch":
                flash("Comment cannot be empty.", "warning")
                return render_partial_or_full()
            flash("Comment cannot be empty.", "warning")
            return redirect(url_for("post_detail", post_id=post_id))

        execute(
            "INSERT INTO forum_comments (content, user_id, post_id, admin_id) VALUES (%s, %s, %s, %s)",
            (content, u["user_id"], post_id, u["admin_id"] if is_admin(u) else None)
        )

        # If this was an Ajax/modal submit, return the updated partial
        if request.args.get("partial") or request.headers.get("X-Requested-With") == "fetch":
            return render_partial_or_full()

        # Normal full-page POST → redirect
        return redirect(url_for("post_detail", post_id=post_id))

    # GET: render appropriate template
    return render_partial_or_full()




@app.route("/post_image/<int:post_id>", endpoint="post_image_blob")
def post_image(post_id):
    row = query_one(
        "SELECT image, image_mime FROM forum_posts WHERE post_id=%s",
        (post_id,),
    )
    if not row or not row.get("image"):
        abort(404)

    # Prefer stored mime if present
    mime = row.get("image_mime")
    if not mime:
        # Detect from raw bytes; falls back to JPEG if unknown
        mime = filetype.guess_mime(row["image"]) or "image/jpeg"

    return Response(row["image"], mimetype=mime)

@app.route('/add_comment/<int:post_id>', methods=['POST'])
@login_required
def add_comment(post_id):
    user = current_user()
    if user_is_banned(user):
        flash("You are banned and cannot comment.", "danger")
        return redirect(url_for("forum"))
    content = (request.form.get("content") or "").strip()
    if not content:
        flash("Comment cannot be empty.", "warning")
        return redirect(url_for('forum'))

    execute(
        "INSERT INTO forum_comments (content, user_id, post_id, admin_id) VALUES (%s, %s, %s, %s)",
        (content, user["user_id"], post_id, user["admin_id"] if is_admin(user) else None)
    )
    flash("Comment added!", "success")
    return redirect(url_for('forum'))

# ---------------------------
# Moderator tools
# ---------------------------
def _safe_redirect(next_url, fallback):
    # Avoid open redirects; only allow same-path redirects
    if not next_url:
        return redirect(fallback)
    # Optional: allow only relative URLs
    if urlparse(next_url).netloc:
        return redirect(fallback)
    return redirect(next_url)

@app.route("/mod/ban/<int:user_id>", methods=["POST"])
@moderator_required
def mod_ban_user(user_id):
    u = current_user()
    if u["user_id"] == user_id:
        flash("You cannot ban yourself.", "warning")
        return _safe_redirect(request.form.get("next"), url_for("forum"))

    reason = (request.form.get("reason") or "").strip()
    days = request.form.get("days")
    until = None
    if days:
        try:
            until = datetime.utcnow() + timedelta(days=int(days))
        except Exception:
            until = None

    execute(
        "UPDATE users SET is_banned=1, ban_reason=%s, ban_until=%s WHERE user_id=%s",
        (reason, until, user_id)
    )
    flash("User banned.", "success")
    return _safe_redirect(request.form.get("next"), request.referrer or url_for("forum"))

@app.route("/mod/unban/<int:user_id>", methods=["POST"])
@moderator_required
def mod_unban_user(user_id):
    execute("UPDATE users SET is_banned=0, ban_reason=NULL, ban_until=NULL WHERE user_id=%s", (user_id,))
    flash("User unbanned.", "success")
    return _safe_redirect(request.form.get("next"), request.referrer or url_for("forum"))

@app.route("/mod/posts/<int:post_id>/delete", methods=["POST"])
@moderator_required
def mod_delete_post(post_id):
    post = query_one("SELECT post_id FROM forum_posts WHERE post_id=%s", (post_id,))
    if not post:
        flash("Post not found.", "warning")
        return _safe_redirect(request.form.get("next"), url_for("forum"))
    execute("DELETE FROM forum_comments WHERE post_id=%s", (post_id,))
    execute("DELETE FROM forum_posts WHERE post_id=%s", (post_id,))
    flash("Post deleted.", "success")
    return _safe_redirect(request.form.get("next"), url_for("forum"))

#########============================######


# --- Avatar upload (uses your existing pool + helpers) ---

AVATAR_FOLDER = os.path.join(app.static_folder, "avatars")
os.makedirs(AVATAR_FOLDER, exist_ok=True)
ALLOWED_AVATAR_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}

def _allowed_avatar(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_AVATAR_EXTS

@app.post("/profile/avatar")
@login_required
def upload_avatar():
    file = request.files.get("avatar")
    if not file or not file.filename:
        flash("No file selected.", "warning")
        return redirect(url_for("profile"))

    if not _allowed_avatar(file.filename):
        flash("Unsupported image type. Use PNG/JPG/GIF/WEBP.", "danger")
        return redirect(url_for("profile"))

    u = current_user()
    uid = u["user_id"]

    # remove any previous avatar files (any extension)
    for old in glob.glob(os.path.join(AVATAR_FOLDER, f"user_{uid}.*")):
        try: os.remove(old)
        except OSError: pass

    ts  = int(time.time())
    ext = file.filename.rsplit(".", 1)[1].lower()
    fname = f"user_{uid}_{ts}.{ext}"
    save_fs = os.path.join(AVATAR_FOLDER, fname)
    file.save(save_fs)

    # store RELATIVE path ONLY (relative to /static)
    rel_path = f"avatars/{fname}"

    # write to DB using your helper (same pool)
    execute("UPDATE users SET Profile_pic=%s WHERE user_id=%s", (rel_path, uid))

    # cache-bust for the template
    session["avatar_ver"] = ts

    flash("Profile picture updated!", "success")
    return redirect(url_for("profile"))


# ...


@app.get("/u/<int:uid>/avatar", endpoint="user_avatar")
def user_avatar(uid: int):
    """
    Serve a user's avatar supporting three storage styles:
    1) users.Profile_pic is IMAGE BYTES (BLOB of the actual image)
    2) users.Profile_pic is BYTES of a PATH STRING (BLOB containing e.g. b'avatars/user_1_123.jpg')
    3) users.Profile_pic is a STRING path ('avatars/user_1_123.jpg')
    """
    row = query_one("SELECT username, Profile_pic FROM users WHERE user_id=%s", (uid,))
    username = (row.get("username") if row else "U") or "U"
    pic = row.get("Profile_pic") if row else None

    def serve_file(fs_path):
        if os.path.isfile(fs_path):
            mt = mimetypes.guess_type(fs_path)[0] or "image/jpeg"
            resp = send_file(fs_path, mimetype=mt, conditional=True)
            resp.headers["Cache-Control"] = "no-store"
            return resp
        return None

    # ---- Case A: pic is bytes (BLOB) ----
    if isinstance(pic, (bytes, bytearray)) and pic:
        data = bytes(pic)

        # If these bytes look like an actual image, serve them directly.
        # filetype.guess returns None for plain text/path bytes.
        if filetype.guess(data) or filetype.guess_mime(data):
            resp = Response(data, mimetype=(filetype.guess_mime(data) or "image/jpeg"))
            resp.headers["Cache-Control"] = "no-store"
            return resp

        # Otherwise try to interpret the bytes as a UTF-8 path string
        try:
            path_str = data.decode("utf-8", errors="strict").strip().strip("\x00").strip("'").strip('"')
        except Exception:
            path_str = None

        if path_str:
            # Allow either 'avatars/...' or 'static/avatars/...'
            fs_path = (
                os.path.join(app.static_folder, path_str.replace("/", os.sep))
                if not path_str.startswith("static/")
                else os.path.join(app.root_path, path_str.replace("/", os.sep))
            )
            served = serve_file(fs_path)
            if served:
                return served
        # If decode/path check fails, fall through to default.

    # ---- Case B: pic is a normal string path ----
    if isinstance(pic, str) and pic:
        path_str = pic.strip().strip("\x00").strip("'").strip('"')
        fs_path = (
            os.path.join(app.static_folder, path_str.replace("/", os.sep))
            if not path_str.startswith("static/")
            else os.path.join(app.root_path, path_str.replace("/", os.sep))
        )
        served = serve_file(fs_path)
        if served:
            return served

    # ---- Default file fallback ----
    default_fs = os.path.join(app.static_folder, "avatars", "default.png")
    served = serve_file(default_fs)
    if served:
        return served

    # ---- Final inline SVG fallback (never fails) ----
    initial = (username[:1] or "U").upper()
    svg = f"""<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 96 96'>
      <defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>
        <stop offset='0%' stop-color='#22d3ee'/><stop offset='100%' stop-color='#0891b2'/>
      </linearGradient></defs>
      <circle cx='48' cy='48' r='46' fill='url(#g)'/>
      <text x='50%' y='56%' text-anchor='middle' font-family='Arial,Helvetica,sans-serif'
            font-size='36' fill='#001018' font-weight='900'>{initial}</text>
    </svg>"""
    resp = Response(svg, mimetype="image/svg+xml")
    resp.headers["Cache-Control"] = "no-store"
    return resp


#########============================######

# --- Wishlist helpers ---

def is_favorited(user_id, manga_id):
    row = query_one("SELECT 1 FROM wishlist WHERE user_id=%s AND manga_id=%s", (user_id, manga_id))
    return bool(row)

def user_favorites(user_id):
    return query_all("""
        SELECT m.manga_id, m.Title, m.Author_name, m.CoverPath
        FROM wishlist w
        JOIN manga m ON m.manga_id = w.manga_id
        WHERE w.user_id=%s
        ORDER BY w.added_at DESC
    """, (user_id,))


@app.post("/wishlist/<int:manga_id>/toggle")
@login_required
def wishlist_toggle(manga_id):
    u = current_user()
    if not query_one("SELECT manga_id FROM manga WHERE manga_id=%s", (manga_id,)):
        abort(404)

    existing = query_one("SELECT wishlist_id FROM wishlist WHERE user_id=%s AND manga_id=%s",
                         (u["user_id"], manga_id))
    if existing:
        execute("DELETE FROM wishlist WHERE wishlist_id=%s", (existing["wishlist_id"],))
    else:
        execute("INSERT INTO wishlist (user_id, manga_id, added_at) VALUES (%s, %s, NOW())",
                (u["user_id"], manga_id))

    return redirect(url_for("manga_detail", manga_id=manga_id))
# --------------valid_email-------------#
EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.I)
def is_valid_email(s: str) -> bool:
    return bool(EMAIL_RE.match((s or "").strip()))

# --- Change E-mail ---
@app.route('/profile/email', methods=['POST'])
@login_required
def change_email():
    u = current_user()
    new_email = (request.form.get('email') or '').strip().lower()

    if not new_email:
        flash('Email cannot be empty.', 'warning')
        return redirect(url_for('profile'))

    if not is_valid_email(new_email):
        flash('Please enter a valid email address.', 'warning')
        return redirect(url_for('profile'))

    # unchanged?
    if (u.get('email') or '').strip().lower() == new_email:
        flash('No changes to save.', 'info')
        return redirect(url_for('profile'))

    # already taken by someone else?
    taken = query_one("SELECT 1 FROM users WHERE email=%s AND user_id<>%s", (new_email, u['user_id']))
    if taken:
        flash('That email is already in use.', 'danger')
        return redirect(url_for('profile'))

    try:
        execute("UPDATE users SET email=%s WHERE user_id=%s", (new_email, u['user_id']))
        flash('Email updated.', 'success')
    except Exception as e:
        flash(f'Could not update email: {e}', 'danger')

    return redirect(url_for('profile'))
# --- Change password ---
@app.get('/profile/password')
@login_required
def password_form():
    # Standalone page opened in a new tab
    return render_template('change_password.html', user=current_user())
@app.get('/chapter-not-found')
def chapter_not_found():
    # Back link defaults to home if referrer is missing
    back = request.args.get('back') or request.referrer or url_for('index')
    return render_template('chapter_not_found.html', back=back)

@app.route('/profile/password', methods=['POST'])
@login_required
def change_password():
    u = current_user()
    if not u or not u.get('password_hash'):
        flash('Cannot change password for this account.', 'danger')
        return redirect(url_for('profile'))

    current_pw = (request.form.get('current_password') or '').strip()
    new_pw     = (request.form.get('new_password') or '').strip()
    confirm_pw = (request.form.get('confirm_password') or '').strip()

    # 1) Verify current password
    if not current_pw or not check_password_hash(u['password_hash'], current_pw):
        flash('Current password is incorrect.', 'danger')
        return redirect(url_for('profile'))

    # 3) Confirm match
    if new_pw != confirm_pw:
        flash('New password and confirmation do not match.', 'warning')
        return redirect(url_for('profile'))

    # 4) Don’t allow same-as-old
    if check_password_hash(u['password_hash'], new_pw):
        flash('New password cannot be the same as your current password.', 'info')
        return redirect(url_for('profile'))

    # 5) Update
    try:
        execute("UPDATE user_auth SET password_hash=%s WHERE user_id=%s",
                (generate_password_hash(new_pw), u['user_id']))
        flash('Password updated.', 'success')
    except Exception as e:
        flash(f'Could not update password: {e}', 'danger')

    return redirect(url_for('profile'))

# ---------------------------
# Entrypoint
# ---------------------------
if __name__ == '__main__':
    # Use environment PORT/HOST in deployment
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "1") == "1"
    app.run(host=host, port=port, debug=debug)
