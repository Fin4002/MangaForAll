@echo off
REM === Activate virtual environment ===
call .venv\Scripts\activate

REM === Install/update dependencies ===
pip install -r requirements.txt

REM === Set Flask app and run ===
set FLASK_APP=app.py
set FLASK_ENV=development
flask run --host=127.0.0.1 --port=5000

REM Keep window open if something fails
pause
