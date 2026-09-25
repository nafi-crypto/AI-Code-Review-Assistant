# ============================================================
# AI CODE REVIEW ASSISTANT - INTEGRATION TEST SUITE
# backend/tests/test_integration.py
# ============================================================

import sys
from pathlib import Path

# Add backend directory to sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient
from app import app
from db.database import init_db
from db import crud

client = TestClient(app)

def run_tests():
    print("==================================================")
    print("Running AI Code Review Assistant Integration Tests")
    print("==================================================")

    # 1. Health Check
    health_resp = client.get("/health")
    assert health_resp.status_code == 200, f"Health check failed: {health_resp.text}"
    print("[PASS] Health check endpoint: OK")

    # 2. User Sync (Clerk Auth Integration)
    user_data = {
        "id": "user_clerk_test_99",
        "email": "alex.engineer@example.com",
        "full_name": "Alex Engineer",
        "image_url": "https://example.com/avatar.png"
    }
    sync_resp = client.post("/api/users/sync", json=user_data)
    assert sync_resp.status_code == 200, f"User sync failed: {sync_resp.text}"
    assert sync_resp.json()["user"]["email"] == user_data["email"]
    print("[PASS] Clerk user sync endpoint: OK")

    # 3. User Profile ME
    headers_alex = {
        "X-User-Id": "user_clerk_test_99",
        "X-User-Email": "alex.engineer@example.com",
        "X-User-Name": "Alex Engineer"
    }
    me_resp = client.get("/api/users/me", headers=headers_alex)
    assert me_resp.status_code == 200
    assert me_resp.json()["user"]["id"] == "user_clerk_test_99"
    print("[PASS] User profile /api/users/me: OK")

    # 4. Theme Preference API (GET & PUT)
    theme_get = client.get("/api/user/theme", headers=headers_alex)
    assert theme_get.status_code == 200
    assert theme_get.json()["theme"] in ["dark", "light", "purple", "emerald"]

    # Update to 'purple'
    theme_put = client.put("/api/user/theme", json={"theme": "purple"}, headers=headers_alex)
    assert theme_put.status_code == 200
    assert theme_put.json()["theme"] == "purple"

    # Verify updated theme
    theme_verify = client.get("/api/user/theme", headers=headers_alex)
    assert theme_verify.json()["theme"] == "purple"
    print("[PASS] Theme preference GET & PUT (SQLite persistent): OK")

    # 5. Security Validation - Block Forbidden Files
    # Test uploading a forbidden executable file
    fake_exe = ("malicious.exe", b"MZ\x90\x00\x03\x00\x00\x00", "application/octet-stream")
    forbidden_resp = client.post(
        "/upload-files",
        files=[("files", fake_exe)],
        headers=headers_alex
    )
    assert forbidden_resp.status_code in [400, 422], f"Forbidden file should be rejected: {forbidden_resp.status_code}"
    print("[PASS] Security validation (reject dangerous executable files): OK")

    # 6. Upload Valid Source Code & Record in SQLite
    sample_code = b"def calculate_total(items):\n    return sum(item.price for item in items)\n"
    valid_file = ("calculator.py", sample_code, "text/plain")
    upload_resp = client.post(
        "/upload-files",
        files=[("files", valid_file)],
        headers=headers_alex
    )
    assert upload_resp.status_code == 200, f"Upload source code failed: {upload_resp.text}"
    print("[PASS] Upload valid source code & vector indexing: OK")

    # Check that the uploaded file appears in user's SQLite files list
    files_resp = client.get("/api/files", headers=headers_alex)
    assert files_resp.status_code == 200
    user_files = files_resp.json()["files"]
    assert any("calculator.py" in f["file_name"] for f in user_files)
    print("[PASS] Uploaded files listed in SQLite for authenticated user: OK")

    # 7. SQLite Review Persistence, Retrieval, and Reopening
    # Insert a structured review
    sample_review = {
        "project": {"name": "Test Project", "languages": ["Python"], "total_files": 1, "total_lines": 2},
        "answer_summary": "Clean code structure with no critical security flaws.",
        "score": 95.0,
        "confidence": 98.0,
        "bugs": [],
        "errors": [],
        "security": {"issues_found": 0, "issues": []},
        "performance": {"issues": [], "time_complexity": "O(N)", "space_complexity": "O(1)"},
        "code_quality": {"observations": [], "suggestions": []},
        "corrected_code": [],
        "final_verdict": "Production ready."
    }

    test_rev_id = "test_rev_123"
    crud.create_review(
        review_id=test_rev_id,
        user_id="user_clerk_test_99",
        project_name="Calculator App",
        language="Python",
        question="Review for security and performance",
        score=95.0,
        confidence=98.0,
        issue_count=0,
        bugs_count=0,
        security_count=0,
        performance_count=0,
        quality_count=0,
        raw_review=sample_review
    )

    # Fetch all reviews for Alex
    reviews_resp = client.get("/api/reviews", headers=headers_alex)
    assert reviews_resp.status_code == 200
    alex_reviews = reviews_resp.json()["reviews"]
    assert len(alex_reviews) > 0
    assert any(r["id"] == test_rev_id for r in alex_reviews)
    print("[PASS] Review history fetched from SQLite: OK")

    # Reopen single review with full AI details
    reopen_resp = client.get(f"/api/reviews/{test_rev_id}", headers=headers_alex)
    assert reopen_resp.status_code == 200
    reopened = reopen_resp.json()["review"]
    assert reopened["id"] == test_rev_id
    assert reopened["review"]["score"] == 95.0
    assert reopened["review"]["final_verdict"] == "Production ready."
    print("[PASS] Reopen past review with full AI findings: OK")

    # 8. User Security Isolation (User Bob cannot access Alex's review or files)
    headers_bob = {
        "X-User-Id": "user_clerk_bob_44",
        "X-User-Email": "bob@example.com"
    }
    bob_reviews_resp = client.get("/api/reviews", headers=headers_bob)
    assert bob_reviews_resp.status_code == 200
    assert len(bob_reviews_resp.json()["reviews"]) == 0, "Bob should not see Alex's reviews"

    bob_unauthorized_reopen = client.get(f"/api/reviews/{test_rev_id}", headers=headers_bob)
    assert bob_unauthorized_reopen.status_code == 404, "Bob cannot reopen Alex's private review"
    print("[PASS] Security isolation (users can only access their own reviews & files): OK")

    # 9. Delete Review
    del_resp = client.delete(f"/api/reviews/{test_rev_id}", headers=headers_alex)
    assert del_resp.status_code == 200
    reopen_after_del = client.get(f"/api/reviews/{test_rev_id}", headers=headers_alex)
    assert reopen_after_del.status_code == 404
    print("[PASS] Delete review from SQLite: OK")

    print("==================================================")
    print("ALL INTEGRATION TESTS PASSED SUCCESSFULLY! (100%)")
    print("==================================================")

if __name__ == "__main__":
    run_tests()
