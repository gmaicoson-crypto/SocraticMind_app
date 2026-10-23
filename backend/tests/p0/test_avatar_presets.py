from pathlib import Path

from fastapi.testclient import TestClient

from core import avatars
from models import User
from routers import auth


def test_preset_paths_match_public_assets():
    public = Path(__file__).resolve().parents[2] / "assets"
    assert len(auth.USER_AVATAR_PRESETS) == 20
    assert len(auth.AI_AVATAR_PRESETS) == 12
    for url in set(auth.USER_AVATAR_PRESETS) | auth.AI_AVATAR_PRESETS:
        assert (public / url.lstrip("/")).is_file(), url


def test_new_users_draw_independently_from_all_study_avatars(db_session, monkeypatch):
    options = iter(avatars.USER_AVATAR_PRESETS)
    monkeypatch.setattr(avatars.secrets, "choice", lambda _: next(options))
    users = [
        User(
            username=f"learner-{index}",
            email=f"learner-{index}@example.test",
            hashed_password="hash",
        )
        for index in range(20)
    ]

    db_session.add_all(users)
    db_session.flush()

    assert [user.avatar_url for user in users] == list(avatars.USER_AVATAR_PRESETS)


def test_avatar_presets_persist_and_remove_previous_upload(
    app, auth_user, db_session, tmp_path, monkeypatch
):
    app.include_router(auth.router)
    monkeypatch.setattr(auth, "UPLOAD_DIR", tmp_path)
    old_file = tmp_path / "old.webp"
    old_file.write_bytes(b"old avatar")
    auth_user.avatar_url = "/static/avatars/old.webp"
    db_session.commit()

    with TestClient(app) as client:
        response = client.put(
            "/api/auth/me",
            json={
                "avatar_url": "/avatars/study/girl-read.webp",
                "ai_avatar_url": "/avatars/AI/study/AI-female-2.webp",
            },
        )
        assert response.status_code == 200
        assert response.json()["avatar_url"] == "/avatars/study/girl-read.webp"
        assert response.json()["ai_avatar_url"] == "/avatars/AI/study/AI-female-2.webp"
        assert (
            client.get("/api/auth/me").json()["ai_avatar_url"] == response.json()["ai_avatar_url"]
        )
        normal = client.put(
            "/api/auth/me", json={"ai_avatar_url": "/avatars/AI/normal/AI_normal_2.webp"}
        )
        assert normal.status_code == 200
        assert normal.json()["ai_avatar_url"] == "/avatars/AI/normal/AI_normal_2.webp"
        assert not old_file.exists()


def test_avatar_presets_reject_unknown_paths_without_changing_profile(app, auth_user):
    app.include_router(auth.router)
    original_user_avatar = auth_user.avatar_url
    original_ai_avatar = auth_user.ai_avatar_url

    with TestClient(app) as client:
        for payload in (
            {"avatar_url": "/static/avatars/another-user.webp"},
            {"ai_avatar_url": "/avatars/AI/missing.webp"},
        ):
            response = client.put("/api/auth/me", json=payload)
            assert response.status_code == 422

        profile = client.get("/api/auth/me").json()
        assert profile["avatar_url"] == original_user_avatar
        assert profile["ai_avatar_url"] == original_ai_avatar
