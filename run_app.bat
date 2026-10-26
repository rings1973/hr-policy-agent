@echo off
REM Start the HR Policy Agent web app and open it in the browser.
REM Double-click this file, or run run_app.bat from a terminal. Press Ctrl+C to stop.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo No .venv found. Set it up first:
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -r requirements-dev.txt
    pause
    exit /b 1
)

if not exist ".env" (
    echo WARNING: no .env file. The app will start, but answers need GROQ_API_KEY in .env.
)

if not exist "app\data\index\tfidf\manifest.json" (
    echo Building the policy index ^(first run only, about 2 minutes^)...
    ".venv\Scripts\python" -m app.rag.ingest --embedder all
)

REM Open the browser a few seconds after the server starts.
start "" cmd /c "timeout /t 5 /nobreak >nul & start http://127.0.0.1:8000"

echo Starting the web app at http://127.0.0.1:8000  (Ctrl+C to stop)
".venv\Scripts\python" -m uvicorn app.main:app --port 8000
pause
