# ============================================================
# AI CODE REVIEW ASSISTANT
# backend/db/database.py
# ============================================================

import sqlite3
import os
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "code_review.db"


def get_db_connection() -> sqlite3.Connection:
    """
    Returns a configured SQLite database connection with row factory
    enabled for dictionary-like column access.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_db():
    """
    Initializes the SQLite database tables if they do not already exist.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Users Table (Linked with Clerk)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            full_name TEXT,
            image_url TEXT,
            theme_preference TEXT DEFAULT 'dark',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # 2. Uploaded Files Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS uploaded_files (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            file_type TEXT NOT NULL,
            upload_time TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # 3. Reviews Table (Code Review History & Full AI Results)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            project_name TEXT NOT NULL,
            language TEXT,
            question TEXT NOT NULL,
            score REAL,
            confidence REAL,
            issue_count INTEGER DEFAULT 0,
            bugs_count INTEGER DEFAULT 0,
            security_count INTEGER DEFAULT 0,
            performance_count INTEGER DEFAULT 0,
            quality_count INTEGER DEFAULT 0,
            raw_review_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # Indices for fast queries
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reviews_user_id ON reviews(user_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reviews_created_at ON reviews(created_at DESC);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_user_id ON uploaded_files(user_id);")

    conn.commit()
    conn.close()
    print(f"[DB] SQLite database initialized successfully at: {DB_PATH}")


if __name__ == "__main__":
    init_db()
