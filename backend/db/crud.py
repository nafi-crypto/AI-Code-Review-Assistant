# ============================================================
# AI CODE REVIEW ASSISTANT
# backend/db/crud.py
# ============================================================

import json
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from .database import get_db_connection


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# USERS CRUD
# ============================================================

def upsert_user(user_id: str, email: str, full_name: Optional[str] = None, image_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Inserts or updates a user in the SQLite database linked to Clerk.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    now = _now_iso()

    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    existing = cursor.fetchone()

    if existing:
        cursor.execute("""
            UPDATE users
            SET email = ?,
                full_name = COALESCE(?, full_name),
                image_url = COALESCE(?, image_url),
                updated_at = ?
            WHERE id = ?
        """, (email, full_name, image_url, now, user_id))
    else:
        cursor.execute("""
            INSERT INTO users (id, email, full_name, image_url, theme_preference, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'dark', ?, ?)
        """, (user_id, email, full_name or "", image_url or "", now, now))

    conn.commit()

    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user_row = cursor.fetchone()
    conn.close()

    return dict(user_row) if user_row else {}


def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetches a user record by their Clerk user ID.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def update_user_theme(user_id: str, theme: str) -> bool:
    """
    Updates user's selected theme preference in SQLite.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    now = _now_iso()

    # Ensure user exists first or update
    cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO users (id, email, full_name, theme_preference, created_at, updated_at)
            VALUES (?, ?, '', ?, ?, ?)
        """, (user_id, f"{user_id}@user.local", theme, now, now))
    else:
        cursor.execute("""
            UPDATE users
            SET theme_preference = ?, updated_at = ?
            WHERE id = ?
        """, (theme, now, user_id))

    conn.commit()
    conn.close()
    return True


def get_user_theme(user_id: str) -> str:
    """
    Retrieves the user's saved theme preference (defaults to 'dark').
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT theme_preference FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row and row["theme_preference"]:
        return row["theme_preference"]
    return "dark"


# ============================================================
# UPLOADED FILES CRUD
# ============================================================

def create_uploaded_file(
    file_id: str,
    user_id: str,
    file_name: str,
    file_path: str,
    file_size: int,
    file_type: str
) -> Dict[str, Any]:
    """
    Records an uploaded file entry linked to a user.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    now = _now_iso()

    # Ensure foreign key target user exists
    cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    if not cursor.fetchone():
        upsert_user(user_id=user_id, email=f"{user_id}@user.local")

    cursor.execute("""
        INSERT INTO uploaded_files (id, user_id, file_name, file_path, file_size, file_type, upload_time)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (file_id, user_id, file_name, file_path, file_size, file_type, now))

    conn.commit()
    cursor.execute("SELECT * FROM uploaded_files WHERE id = ?", (file_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {}


def get_user_files(user_id: str) -> List[Dict[str, Any]]:
    """
    Returns all uploaded files for a specific user.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM uploaded_files
        WHERE user_id = ?
        ORDER BY upload_time DESC
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_uploaded_file(file_id: str, user_id: str) -> bool:
    """
    Deletes an uploaded file record belonging to the user.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM uploaded_files
        WHERE id = ? AND user_id = ?
    """, (file_id, user_id))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0


# ============================================================
# REVIEWS CRUD
# ============================================================

def create_review(
    review_id: str,
    user_id: str,
    project_name: str,
    language: str,
    question: str,
    score: Optional[float],
    confidence: Optional[float],
    issue_count: int,
    bugs_count: int,
    security_count: int,
    performance_count: int,
    quality_count: int,
    raw_review: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Saves a code review, its metrics, and complete AI-generated JSON results.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    now = _now_iso()

    # Ensure foreign key target user exists
    cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    if not cursor.fetchone():
        upsert_user(user_id=user_id, email=f"{user_id}@user.local")

    raw_json_str = json.dumps(raw_review)

    cursor.execute("""
        INSERT INTO reviews (
            id, user_id, project_name, language, question, score, confidence,
            issue_count, bugs_count, security_count, performance_count, quality_count,
            raw_review_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        review_id, user_id, project_name, language, question, score, confidence,
        issue_count, bugs_count, security_count, performance_count, quality_count,
        raw_json_str, now
    ))

    conn.commit()
    cursor.execute("SELECT * FROM reviews WHERE id = ?", (review_id,))
    row = cursor.fetchone()
    conn.close()

    result = dict(row) if row else {}
    if "raw_review_json" in result and isinstance(result["raw_review_json"], str):
        try:
            result["review"] = json.loads(result["raw_review_json"])
        except Exception:
            result["review"] = {}
    return result


def get_user_reviews(user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Returns list of reviews for the specified user (ordered newest first).
    Includes parsed review JSON for immediate access.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM reviews
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (user_id, limit))
    rows = cursor.fetchall()
    conn.close()

    results = []
    for r in rows:
        item = dict(r)
        # Parse json for convenience
        try:
            item["review"] = json.loads(item.get("raw_review_json", "{}"))
        except Exception:
            item["review"] = {}
        results.append(item)
    return results


def get_review_by_id(review_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves full details of a specific review if it belongs to the user.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM reviews
        WHERE id = ? AND user_id = ?
    """, (review_id, user_id))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    item = dict(row)
    try:
        item["review"] = json.loads(item.get("raw_review_json", "{}"))
    except Exception:
        item["review"] = {}
    return item


def delete_review(review_id: str, user_id: str) -> bool:
    """
    Deletes a review record belonging to the user.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM reviews
        WHERE id = ? AND user_id = ?
    """, (review_id, user_id))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def delete_all_reviews(user_id: str) -> int:
    """
    Deletes all review records for a user.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM reviews
        WHERE user_id = ?
    """, (user_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected
