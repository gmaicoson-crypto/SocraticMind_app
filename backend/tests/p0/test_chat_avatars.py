from core.auth import hash_password
from core.deps import get_current_user
from models import User
from routers import auth, chat


def upload(client, session_id: str, name: str = "portrait.webp", data: bytes = b"image"):
    return client.post(
        "/api/chat/avatar",
        data={"session_id": session_id},
        files={"file": (name, data, "image/webp")},
    )


def test_chat_avatar_upload_replaces_only_the_same_session(
    client, app, auth_user, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(chat, "UPLOAD_DIR", tmp_path)
    first = upload(client, "session-a")
    assert first.status_code == 200
    first_path = tmp_path / first.json()["avatar_url"].rsplit("/", 1)[-1]
    assert first_path.read_bytes() == b"image"

    replacement = upload(client, "session-a", data=b"replacement")
    other_session = upload(client, "session-b")
    assert replacement.status_code == other_session.status_code == 200
    assert not first_path.exists()
    replacement_path = tmp_path / replacement.json()["avatar_url"].rsplit("/", 1)[-1]
    other_path = tmp_path / other_session.json()["avatar_url"].rsplit("/", 1)[-1]
    assert replacement_path.read_bytes() == b"replacement"
    assert other_path.exists()

    other_user = User(
        username="other-avatar", email="other-avatar@example.test", hashed_password="hash"
    )
    db_session.add(other_user)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: other_user
    assert client.request(
        "DELETE", "/api/chat/avatar", json={"session_id": "session-a"}
    ).json() == {"deleted": 0}
    assert replacement_path.exists()

    app.dependency_overrides[get_current_user] = lambda: auth_user
    assert client.request(
        "DELETE", "/api/chat/avatar", json={"session_id": "session-a"}
    ).json() == {"deleted": 1}
    assert not replacement_path.exists()
    assert other_path.exists()


def test_chat_avatar_rejects_invalid_files_without_removing_current(client, tmp_path, monkeypatch):
    monkeypatch.setattr(chat, "UPLOAD_DIR", tmp_path)
    current = upload(client, "session-a").json()["avatar_url"]
    current_path = tmp_path / current.rsplit("/", 1)[-1]

    assert upload(client, "session-a", name="bad.svg").status_code == 400
    assert upload(client, "session-a", data=b"x" * (5 * 1024 * 1024 + 1)).status_code == 400
    assert current_path.exists()


def test_chat_avatar_upload_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(chat.rate_limit, "hit", lambda *_args, **_kwargs: False)
    assert upload(client, "session-a").status_code == 429


def test_deleting_session_or_account_removes_chat_avatars(
    client, app, auth_user, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(chat, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(auth, "UPLOAD_DIR", tmp_path)
    session_avatar = upload(client, "session-a").json()["avatar_url"]
    session_path = tmp_path / session_avatar.rsplit("/", 1)[-1]
    assert (
        client.request("DELETE", "/api/chat/session", json={"session_id": "session-a"}).status_code
        == 200
    )
    assert not session_path.exists()

    account_avatar = upload(client, "session-b").json()["avatar_url"]
    account_path = tmp_path / account_avatar.rsplit("/", 1)[-1]
    auth_user.hashed_password = hash_password("Password123")
    db_session.commit()
    app.include_router(auth.router)
    assert (
        client.request(
            "DELETE", "/api/auth/me", json={"password": "Password123", "confirm": "DELETE"}
        ).status_code
        == 200
    )
    assert not account_path.exists()
