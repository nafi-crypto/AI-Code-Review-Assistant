import pytest

def test_safe_execute_with_valid_data():
    from src.services.auth_handler import safe_execute
    res = safe_execute({"data": {"key": "value"}})
    assert res["status"] == "success"

def test_safe_execute_prevents_null_pointer_regression():
    from src.services.auth_handler import safe_execute
    res = safe_execute({"data": None})
    assert res["status"] == "error"
    assert "null" in res["message"].lower()

def test_safe_execute_with_empty_payload():
    from src.services.auth_handler import safe_execute
    res = safe_execute({})
    assert res["status"] == "error"
