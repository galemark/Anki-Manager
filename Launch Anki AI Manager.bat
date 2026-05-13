@echo off
cd /d "%~dp0anki-manager"
start "" http://localhost:5050
python app.py
