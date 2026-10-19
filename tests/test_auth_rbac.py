"""
tests/test_auth_rbac.py
Comprehensive test suite verifying user authentication, registration, session management,
PBKDF2 cryptographic hashing, and Role-Based Access Control (RBAC) in AegisRuntime.
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import (
    init_db,
    seed_default_users,
    authenticate_user,
    hash_password,
    verify_password,
    get_user_by_username,
    update_user_role
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def ensure_db():
    init_db()
    seed_default_users()


def test_password_hashing():
    password = "SecretPassword123!"
    pw_hash, salt = hash_password(password)
    assert len(pw_hash) == 64
    assert len(salt) == 32
    assert verify_password(password, pw_hash, salt) is True
    assert verify_password("WrongPassword", pw_hash, salt) is False


def test_seed_default_personas():
    # SuperAdmin Wania
    admin_user = authenticate_user("superadmin", "admin123")
    assert admin_user is not None
    assert admin_user["username"] == "superadmin"
    assert admin_user["role"] == "SUPERADMIN"
    assert "Wania" in admin_user["full_name"]

    # Compliance
    comp_user = authenticate_user("compliance", "compliance123")
    assert comp_user is not None
    assert comp_user["role"] == "COMPLIANCE_OFFICER"

    # Operator
    op_user = authenticate_user("operator", "operator123")
    assert op_user is not None
    assert op_user["role"] == "OPERATOR"

    # Auditor
    auditor_user = authenticate_user("auditor", "auditor123")
    assert auditor_user is not None
    assert auditor_user["role"] == "VIEWER"


def test_api_login_success():
    res = client.post("/api/auth/login", json={
        "username": "superadmin",
        "password": "admin123"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert "session_token" in data
    assert data["user"]["role"] == "SUPERADMIN"
    assert "Wania" in data["user"]["full_name"]


def test_api_login_invalid_password():
    res = client.post("/api/auth/login", json={
        "username": "superadmin",
        "password": "wrongpassword"
    })
    assert res.status_code == 401
    data = res.json()
    assert "Invalid username or password" in data["detail"]


def test_api_login_by_email():
    res = client.post("/api/auth/login", json={
        "username": "admin@aegis.runtime",
        "password": "admin123"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert data["user"]["username"] == "superadmin"


def test_api_register_new_user():
    import uuid
    rand_id = uuid.uuid4().hex[:6]
    username = f"user_{rand_id}"
    email = f"user_{rand_id}@test.org"

    res = client.post("/api/auth/register", json={
        "username": username,
        "email": email,
        "full_name": "Test Engineer",
        "role": "OPERATOR",
        "password": "Passw0rdSecure!"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert data["user"]["username"] == username
    assert data["user"]["role"] == "OPERATOR"
    assert "session_token" in data

    # Verify duplicate registration fails
    dup_res = client.post("/api/auth/register", json={
        "username": username,
        "email": f"other_{rand_id}@test.org",
        "full_name": "Duplicate User",
        "role": "OPERATOR",
        "password": "Passw0rdSecure!"
    })
    assert dup_res.status_code == 400


def test_api_auth_me_and_logout():
    # Login as Superadmin
    login_res = client.post("/api/auth/login", json={
        "username": "superadmin",
        "password": "admin123"
    })
    token = login_res.json()["session_token"]

    # Call /api/auth/me with Bearer token
    me_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["user"]["username"] == "superadmin"

    # Call /api/auth/logout
    logout_res = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout_res.status_code == 200
    assert logout_res.json()["status"] == "SUCCESS"

    # Me should now fail or be revoked
    me_after = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_after.status_code == 401


def test_api_quick_switch():
    personas = ["superadmin", "compliance", "operator", "auditor"]
    for p in personas:
        res = client.post("/api/auth/quick_switch", json={"persona": p})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "SUCCESS"
        assert "session_token" in data
        assert data["user"]["username"] == p


def test_api_list_and_update_roles():
    # Login as superadmin to get token
    login_res = client.post("/api/auth/login", json={
        "username": "superadmin",
        "password": "admin123"
    })
    token = login_res.json()["session_token"]

    # List users
    users_res = client.get("/api/auth/users", headers={"Authorization": f"Bearer {token}"})
    assert users_res.status_code == 200
    users = users_res.json()["users"]
    assert len(users) >= 4

    # Find operator and change role to COMPLIANCE_OFFICER
    op = next(u for u in users if u["username"] == "operator")
    update_res = client.post(
        f"/api/auth/users/{op['id']}/role",
        headers={"Authorization": f"Bearer {token}"},
        json={"role": "COMPLIANCE_OFFICER"}
    )
    assert update_res.status_code == 200
    assert update_res.json()["status"] == "SUCCESS"

    # Verify updated role persisted
    updated_op = get_user_by_username("operator")
    assert updated_op["role"] == "COMPLIANCE_OFFICER"

    # Restore operator role
    update_user_role(op["id"], "OPERATOR")
    restored_op = get_user_by_username("operator")
    assert restored_op["role"] == "OPERATOR"
