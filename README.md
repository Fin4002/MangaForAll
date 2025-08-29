# MangaForAll (Flask)

## Quickstart
```bash
python -m venv venv
venv\Scripts\activate  # Windows
# or: source venv/bin/activate  # macOS/Linux

pip install -r requirements.txt
flask --app app.py init-db
flask --app app.py run
```
Default admin: `admin` / `admin123`

## Routes
- `/` home
- `/manga` list
- `/manga/<id>` detail
- `/reader/<chapter_id>` image reader
- `/forum`
- `/profile`
- `/login`, `/register`, `/logout`
- `/dashboard` smart redirect per role
- `/dashboard/admin`, `/dashboard/moderator`, `/dashboard/content`
