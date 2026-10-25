"""Shared native avatar boundaries exercised against the real provider with synthetic files."""

import base64
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.staticfiles import StaticFiles

from core.avatars import AI_AVATAR_PRESETS, PRESET_ASSET_DIR
from core.deps import get_current_user
from routers import chat


DATA = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts/fixtures/chat-avatar.json").read_text()
)


def test_native_multipart_unicode_resource_and_idempotent_cleanup(
    client, app, tmp_path, monkeypatch
):
    monkeypatch.setattr(chat, "UPLOAD_DIR", tmp_path)
    monkeypatch.setitem(
        app.dependency_overrides, get_current_user, lambda: SimpleNamespace(id=DATA["owner_id"])
    )
    app.mount("/static/avatars", StaticFiles(directory=tmp_path))
    image = base64.b64decode(DATA["image_base64"])
    result = client.post(
        "/api/chat/avatar",
        data={"session_id": DATA["session_id"]},
        files={"file": ("avatar.png", image, "image/png")},
    )
    assert result.status_code == 200
    path = result.json()["avatar_url"]
    assert path.startswith(DATA["upload_url"].rsplit("_", 1)[0] + "_") and path.endswith(".png")
    response = client.get(path)
    assert response.status_code == 200 and response.content == image
    assert response.headers["content-type"] == "image/png"
    for expected in [1, 0]:
        deletion = client.request(
            "DELETE", "/api/chat/avatar", json={"session_id": DATA["session_id"]}
        )
        assert deletion.status_code == 200 and deletion.json() == {"deleted": expected}
    assert client.get(path).status_code == 404


def test_native_preset_catalog_matches_provider_and_public_assets(client, app):
    assert set(DATA["presets"]["normal"] + DATA["presets"]["socratic"]) == AI_AVATAR_PRESETS
    app.mount("/avatars", StaticFiles(directory=PRESET_ASSET_DIR))
    for paths in DATA["presets"].values():
        result = client.get(paths[0])
        assert result.status_code == 200 and result.headers["content-type"] == "image/webp"
        assert 0 < len(result.content) <= 5 * 1024 * 1024
