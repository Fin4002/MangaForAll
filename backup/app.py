# app.py — Flask + mysql-connector-python, built to match your schema
# Schema used (from your diagram / dump):
#   users(user_id, username, joining_date, no_of_chapters_read, email)
#   user_auth(user_id, password_hash, admin_id)
#   admin(admin_id, name)
#   manga(manga_id, publication_status, Title, Author_name, synopsis, user_id, admin_id)
import filetype
import os, re, json, urllib.parse
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template, render_template_string, redirect, url_for,
    request, flash, session, abort
)
from werkzeug.security import generate_password_hash, check_password_hash

import mysql.connector
from mysql.connector import pooling


from flask import (
    Flask, render_template, render_template_string, redirect, url_for,
    request, flash, session, abort, Response  # ← add Response here
)
# or: from flask import Response, make_response


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
# Paths
# ---------------------------
def resources_root():
    # static/Resources is the manga warehouse
    return os.path.join(app.static_folder, 'Resources')

# ---------------------------
# User Auth
    # static/Resources is the warehouse
    return os.path.join(app.static_folder, 'Resources')

# ---------------------------
# Auth helpers strictly per your schema
# ---------------------------
def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    # Join users + user_auth query
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
    # check if user_row has admin_id or not
    return bool(user_row and user_row.get('admin_id'))

    # In your schema, user_auth.admin_id indicates admin linkage
    return bool(user_row and user_row.get('admin_id'))

def is_content_manager(user_row):
    """
    True only if the user's admin_id is present in Content_manager.
    """
    if not user_row or not user_row.get('admin_id'):
        return False
    row = query_one("SELECT 1 FROM Content_manager WHERE admin_id=%s", (user_row['admin_id'],))
    return bool(row)

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

@app.context_processor
def inject_user():
    return dict(user=current_user())
@app.context_processor
def inject_helpers():
    return dict(is_admin=is_admin, is_content_manager=is_content_manager)
# ---------------------------
# Auth routes (users + user_auth)
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

        # Create user, then user_auth (Register)
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
# Pages (public site)
# --------------------------- 
@app.route('/')
def index():
    mangas = query_all("""
        SELECT manga_id, Title, Author_name, synopsis, publication_status, CoverPath
        FROM manga
        ORDER BY manga_id DESC
    """) #gets manga information from manga table
    return render_template('index.html', mangas=mangas, user=current_user())

@app.route('/manga')
def manga_list():
    mangas = query_all("""
        SELECT manga_id, Title, Author_name, synopsis, publication_status, CoverPath
        FROM manga
        ORDER BY Title ASC
    """)
    return render_template('manga.html', mangas=mangas, user=current_user())

#work in progress
@app.route('/manga/<int:manga_id>')
def manga_detail(manga_id):
    # 1) Fetch clean fields from DB (no NULL, no stray spaces)
    row = query_one("""
        SELECT
          COALESCE(NULLIF(TRIM(Title), ''), '')            AS Title,
          COALESCE(NULLIF(TRIM(Author_name), ''), '')      AS Author_name,
          COALESCE(publication_status, '')                 AS publication_status,
          COALESCE(CoverPath, '')                          AS CoverPath,
          manga_id
        FROM manga
        WHERE manga_id = %s
    """, (manga_id,))
    if not row:
        abort(404)

    db_title  = row['Title']
    db_author = row['Author_name']
    coverpath = row['CoverPath']

    # 2) Infer folder (prefer CoverPath Resources/<folder>/Cover.jpg)
    folder = None
    if coverpath.startswith("Resources/"):
        parts = coverpath.split("/")
        if len(parts) >= 2 and parts[1]:
            folder = parts[1]

    # Fallback: match folder by Title
    base = resources_root()
    if not folder and db_title and os.path.isdir(base):
        for d in os.listdir(base):
            if os.path.isdir(os.path.join(base, d)) and d.lower() == db_title.lower():
                folder = d
                break

    # 3) Get meta from manga.txt if we found a folder
    meta = {"Author_name": "", "publication_status": "", "Title": ""}
    if folder:
        meta = parse_manga_txt(os.path.join(base, folder, "manga.txt")) or meta

    # 4) Final values: DB first, then meta, then folder name
    title_final  = db_title or (meta.get("Title") or "").strip() or (folder or "Untitled")
    author_final = db_author or (meta.get("Author_name") or "").strip() or "Unknown"
    status_final = (row.get("publication_status") or meta.get("publication_status") or "unknown").strip()

    # 5) Cover URL: Resources if exists, else DB CoverPath
    cover_url = None
    if folder:
        cover_fs = os.path.join(base, folder, "Cover.jpg")
        if os.path.isfile(cover_fs):
            cover_url = f"/static/Resources/{folder}/Cover.jpg"
    if not cover_url and coverpath:
        cover_url = f"/static/{coverpath}"

    # 6) Chapters
    chapters = []
    if folder:
        fpath = os.path.join(base, folder)
        if os.path.isdir(fpath):
            chapters = [
                d for d in os.listdir(fpath)
                if os.path.isdir(os.path.join(fpath, d)) and is_chapter_folder(d)
            ]
            chapters.sort(key=chapter_sort_key)

    # 7) Pass a clean, dependable dict to the template
    manga_ctx = dict(row)
    manga_ctx["Title"] = title_final
    manga_ctx["Author_name"] = author_final
    manga_ctx["publication_status"] = status_final

    return render_template(
        'manga_detail.html',
        manga=manga_ctx,
        folder=folder,
        cover_url=cover_url,
        chapters=chapters,
        meta=meta,
        user=current_user()
    )




# ---------------------------
#work in progress
# ---------------------------

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html', user=current_user())

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
        cover_fs = os.path.join(fpath, "Cover.jpg")
        cover_url = f"/static/Resources/{folder}/Cover.jpg" if os.path.isfile(cover_fs) else None

        # AFTER
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

# ---------------------------
# Content dashboard
# ---------------------------
@app.route('/dashboard/content')
@content_manager_required
def content_dashboard():
    u = current_user()
    mangas = scan_resources_content()
    # NOTE: to make cards clickable, ensure your dash_content.html wraps each card
    # with: <a href="{{ url_for('content_detail', folder=m.folder) }}">...</a>
    return render_template('dash_content.html', mangas=mangas, user=u)

# Per-manga detail: list chapters, metadata, approve button
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

    # AFTER
    chapters = [
            d for d in os.listdir(fpath)
            if os.path.isdir(os.path.join(fpath, d)) and is_chapter_folder(d)
        ]
    chapters.sort(key=chapter_sort_key)


    existing = query_one("SELECT manga_id FROM manga WHERE Title=%s", (title,))
    approved = bool(existing)

    return render_template(
        "content_detail.html",  # create this template or swap to render_template_string
        user=u,
        folder=folder,
        meta=meta,
        title=title,
        synopsis=synopsis,
        cover_url=cover_url,
        chapters=chapters,
        approved=approved
    )

# Approve handler: insert metadata into DB only when approved
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

    # cover path (relative to /static)
    cover_rel = None
    cover_fs = os.path.join(fpath, "Cover.jpg")
    if os.path.isfile(cover_fs):
        cover_rel = f"Resources/{folder}/Cover.jpg"

    # no dupes by Title
    exists = query_one("SELECT manga_id, CoverPath FROM manga WHERE Title=%s", (title,))
    if exists:
        # if already approved but missing cover, quietly backfill it
        if cover_rel and not exists.get("CoverPath"):
            try:
                execute("UPDATE manga SET CoverPath=%s WHERE manga_id=%s", (cover_rel, exists["manga_id"]))
                flash("Already approved. CoverPath was missing and is now set.", "info")
            except Exception as e:
                flash(f"Already approved; failed to set CoverPath: {e}", "warning")
        else:
            flash("Already approved.", "info")
        return redirect(url_for('content_detail', folder=folder))

    # build insert columns/values (only include what we actually have)
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

# ---------------------------# ---------------------------# ---------------------------# ---------------------------# ---------------------------
@app.route('/dashboard/content/<folder>/remove', methods=['POST'])
@content_manager_required
def content_remove(folder):
    """
    Remove the approved manga record from the database ONLY.
    Do NOT delete anything under static/Resources/<folder>.
    """
    base = resources_root()
    fpath = os.path.join(base, folder)

    # Prefer matching by CoverPath (ties DB row to folder reliably)
    cover_rel = f"Resources/{folder}/Cover.jpg"
    row = query_one(
        "SELECT manga_id FROM manga WHERE CoverPath=%s",
        (cover_rel,)
    )

    # Fallback: match by Title from manga.txt, else by folder name
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
def list_images(folder_path):
    imgs = []
    try:
        for name in os.listdir(folder_path):
            ext = os.path.splitext(name)[1].lower()
            if ext in IMAGE_EXTS:
                imgs.append(name)
    except FileNotFoundError:
        return []
    # Natural-sort page filenames like 001.jpg, 2.png, 10.png
    def keyfn(s):
        return [int(t) if t.isdigit() else t.lower() for t in re.findall(r'\d+|\D+', s)]
    imgs.sort(key=keyfn)
    return imgs

@app.route('/reader/<folder>/<chapter>')
def reader(folder, chapter):
    """
    Render pages for a chapter located at:
      static/Resources/<folder>/<chapter>/
    """
    base = resources_root()
    chapter_dir = os.path.join(base, folder, chapter)
    if not os.path.isdir(chapter_dir):
        abort(404)

    # Build image URLs
    files = list_images(chapter_dir)
    pages = [f"/static/Resources/{folder}/{chapter}/{fn}" for fn in files]

    # nav: prev/next chapter by scanning sibling ch.* dirs
    manga_dir = os.path.join(base, folder)
    # AFTER
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

    # light metadata (optional)
    meta = parse_manga_txt(os.path.join(manga_dir, "manga.txt"))
    title = meta.get("Title") or folder

    _num = re.search(r'\d+', chapter)
    chapter_ctx = {
        "number": _num.group() if _num else chapter,
        "title": f"{title} · {chapter}"
    }


    return render_template(
        "reader.html",
        folder=folder,
        chapter=chapter_ctx,
        pages=pages,
        prev_chapter=prev_ch,
        next_chapter=next_ch
    )

# ---------------------------
# Resources → DB sync (manual)
# ---------------------------
def list_dir_sorted(path):
    try:
        items = os.listdir(path)
    except FileNotFoundError:
        return []
    def keyfn(s):
        return [int(t) if t.isdigit() else t.lower() for t in re.findall(r'\d+|\D+', s)]
    return sorted(items, key=keyfn)

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
        SELECT post_id, title, content, author, image
        FROM forum_posts
        ORDER BY post_id DESC
    """)

    # Get Top 10 contributors (users with the most posts + comments)
    top_contributors = query_all("""
        SELECT author, 
               COUNT(DISTINCT f.post_id) + COUNT(DISTINCT c.comment_id) AS total_contributions
        FROM forum_posts f
        LEFT JOIN forum_comments c ON c.post_id = f.post_id
        GROUP BY author
        ORDER BY total_contributions DESC
        LIMIT 10
    """)

    comments_by_post = {}
    if posts:
        ids = [p["post_id"] for p in posts]
        placeholders = ",".join(["%s"] * len(ids))
        rows = query_all(f"""
            SELECT fc.post_id, fc.comment_id, fc.content, u.username
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






# Forum: new post
@app.route("/forum/new", methods=["GET", "POST"])
@login_required
def new_post():
    if request.method == "POST":
        title   = request.form["title"].strip()
        content = request.form["content"].strip()
        author  = current_user()["username"]

        # Optional: limit upload size
        app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB

        image_bytes = None
        image_mime  = None

        file = request.files.get("image")
        if file and file.filename:
            # basic guard: only images
            if not (file.mimetype or "").startswith("image/"):
                flash("Only image files are allowed.", "warning")
                return redirect(url_for("new_post"))
            image_bytes = file.read()         # <-- raw bytes go into MEDIUMBLOB
            image_mime  = file.mimetype       # e.g., image/jpeg

        # Make sure your table has image_mime VARCHAR(64)
        execute(
            """
            INSERT INTO forum_posts (title, content, author, image, image_mime, user_id, admin_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                title, content, author,
                image_bytes, image_mime,
                current_user()["user_id"],
                current_user()["admin_id"] if is_admin(current_user()) else None,
            ),
        )
        flash("Post created!", "success")
        return redirect(url_for("forum"))   # use your actual endpoint name

    return render_template("new_post.html", user=current_user())


# Forum: post detail + comments
@app.route("/forum/<int:post_id>", methods=["GET", "POST"])
def post_detail(post_id):
    post = query_one("SELECT * FROM forum_posts WHERE post_id=%s", (post_id,))
    if not post:
        abort(404)

    # helper to render either full page or modal partial
    def render_partial_or_full():
        is_partial = request.args.get("partial") or request.headers.get("X-Requested-With") == "fetch"
        template = "post_detail_modal.html" if is_partial else "post_detail.html"
        comments = query_all(
            """
            SELECT fc.comment_id, fc.content, fc.post_id, u.username
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
        content = (request.form.get("content") or "").strip()
        if not content:
            if request.args.get("partial"):
                # return the current partial with a tiny warning if you want
                return render_partial_or_full()
            flash("Comment cannot be empty.", "warning")
            return redirect(url_for("post_detail", post_id=post_id))

        execute(
            "INSERT INTO forum_comments (content, user_id, post_id, admin_id) VALUES (%s, %s, %s, %s)",
            (content, u["user_id"], post_id, u["admin_id"] if is_admin(u) else None)
        )
        if request.args.get("partial") or request.headers.get("X-Requested-With") == "fetch":
            # return the updated partial for the modal
            return render_partial_or_full()
        return redirect(url_for("post_detail", post_id=post_id))

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


#########============Reader for users================######
def folder_from_manga_row(m):
    """Figure out the Resources/<folder> from DB row."""
    # If CoverPath is like "Resources/<folder>/Cover.jpg"
    cp = (m or {}).get("CoverPath")
    if cp and cp.startswith("Resources/"):
        parts = cp.split("/")
        if len(parts) >= 2:
            return parts[1]
    # Fallback: try to find a folder matching the Title
    base = resources_root()
    title = (m or {}).get("Title") or ""
    if not title or not os.path.isdir(base):
        return None
    # case-insensitive exact match on folder name
    for d in os.listdir(base):
        if os.path.isdir(os.path.join(base, d)) and d.lower() == title.lower():
            return d
    return None

def list_chapter_dirs(folder):
    """Return sorted chapter folder names for a given Resources folder."""
    base = resources_root()
    fpath = os.path.join(base, folder) if folder else None
    if not fpath or not os.path.isdir(fpath):
        return []
    ch_dirs = [
        d for d in os.listdir(fpath)
        if os.path.isdir(os.path.join(fpath, d)) and is_chapter_folder(d)
    ]
    ch_dirs.sort(key=chapter_sort_key)
    return ch_dirs





# ---------------------------
# Entrypoint
# ---------------------------
if __name__ == '__main__':
    app.run(debug=True)
