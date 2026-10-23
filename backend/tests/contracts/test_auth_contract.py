import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from core.database import get_db
from models.topic import Topic
from models.user import User
from routers import auth


FIXTURE = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts/fixtures/auth.json").read_text()
)
FIELDS = FIXTURE["credentials"]


@pytest.fixture()
def auth_client(db_session, monkeypatch):
    app = FastAPI()
    app.include_router(auth.router)
    app.dependency_overrides[get_db] = lambda: db_session
    monkeypatch.setattr(auth, "generate_code", lambda: FIELDS["code"])
    monkeypatch.setattr(auth, "send_verification_email", lambda *_args: None)
    monkeypatch.setattr(auth, "choose_user_avatar", lambda: FIXTURE["user"]["avatar_url"])
    # Wire behavior is deterministic; rate-limit policy is outside this contract selection.
    monkeypatch.setattr(auth.rate_limit, "hit", lambda *_args, **_kwargs: True)
    with TestClient(app) as client:
        yield client


def register(client):
    sent = client.post(
        "/api/auth/send-code", json={"email": FIELDS["email"], "purpose": "register"}
    )
    assert sent.status_code == 200
    assert sent.json() == {"message": FIXTURE["messages"]["code"]}
    response = client.post(
        "/api/auth/register",
        json={key: FIELDS[key] for key in ("username", "email", "password", "code")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_register_login_and_profile_share_native_fixture(auth_client):
    registered = register(auth_client)
    assert registered["user"] == FIXTURE["user"]
    assert registered["token_type"] == FIXTURE["grant"]["token_type"]
    assert registered["access_token"]
    login = auth_client.post(
        "/api/auth/login",
        data={"username": FIELDS["email"].upper(), "password": FIELDS["password"]},
    )
    assert login.status_code == 200
    assert login.json()["user"] == FIXTURE["user"]
    profile = auth_client.get(
        "/api/auth/me", headers={"Authorization": "Bearer " + login.json()["access_token"]}
    )
    assert profile.status_code == 200
    assert profile.json() == FIXTURE["user"]


def test_wrong_credentials_and_duplicate_registration_do_not_create_another_user(
    auth_client, db_session
):
    register(auth_client)
    duplicate = auth_client.post(
        "/api/auth/register",
        json={key: FIELDS[key] for key in ("username", "email", "password", "code")},
    )
    assert duplicate.status_code == 400
    assert db_session.query(User).count() == 1
    assert db_session.query(Topic).count() == 1
    wrong = auth_client.post(
        "/api/auth/login", data={"username": FIELDS["email"], "password": "wrong"}
    )
    assert wrong.status_code == 401
    assert wrong.json() == {"detail": "邮箱或密码错误"}
    assert (
        auth_client.get("/api/auth/me", headers={"Authorization": "Bearer expired"}).status_code
        == 401
    )


def test_reset_uses_its_own_code_and_requires_new_password(auth_client):
    register(auth_client)
    request = {key: FIELDS[key] for key in ("email", "code", "new_password")}
    assert auth_client.post("/api/auth/reset-password", json=request).status_code == 400
    sent = auth_client.post(
        "/api/auth/send-code", json={"email": FIELDS["email"], "purpose": "reset"}
    )
    assert sent.status_code == 200
    reset = auth_client.post("/api/auth/reset-password", json=request)
    assert reset.status_code == 200
    assert reset.json() == {"message": FIXTURE["messages"]["reset"]}
    assert auth_client.post("/api/auth/reset-password", json=request).status_code == 400
    assert (
        auth_client.post(
            "/api/auth/login", data={"username": FIELDS["email"], "password": FIELDS["password"]}
        ).status_code
        == 401
    )
    assert (
        auth_client.post(
            "/api/auth/login",
            data={"username": FIELDS["email"], "password": FIELDS["new_password"]},
        ).status_code
        == 200
    )
