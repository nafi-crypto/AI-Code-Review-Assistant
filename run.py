#!/usr/bin/env python3
"""
Launcher script for AI Code Review Assistant Unified Single Application.
Builds the React frontend if missing and runs FastAPI backend serving both on port 8000.
"""

import os
import sys
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT_DIR / "frontend"
FRONTEND_BUILD_DIR = FRONTEND_DIR / "build"
BACKEND_DIR = ROOT_DIR / "backend"


def build_frontend():
    print("============================================================")
    print("Building React Frontend static assets...")
    print("============================================================")
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"

    # Install frontend dependencies if needed
    if not (FRONTEND_DIR / "node_modules").exists():
        print("Installing frontend dependencies...")
        subprocess.run([npm_cmd, "install"], cwd=FRONTEND_DIR, check=True)

    # Build frontend
    subprocess.run([npm_cmd, "run", "build"], cwd=FRONTEND_DIR, check=True)
    print("Frontend build complete!")


def main():
    force_build = "--build" in sys.argv

    if force_build or not FRONTEND_BUILD_DIR.exists():
        build_frontend()

    print("============================================================")
    print("Starting AI Code Review Assistant Unified Server...")
    print("Application available at: http://localhost:8000")
    print("============================================================")

    import uvicorn
    import threading
    import webbrowser

    # Open browser automatically after 1.5 seconds
    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:8000")).start()

    sys.path.insert(0, str(BACKEND_DIR))
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False, app_dir=str(BACKEND_DIR))


if __name__ == "__main__":
    main()
