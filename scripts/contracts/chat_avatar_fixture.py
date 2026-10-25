"""Synthetic multipart and public image boundary shared by native consumers."""

import base64
import json
import time
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import urlsplit


DATA = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts/fixtures/chat-avatar.json").read_text()
)
IMAGE = base64.b64decode(DATA["image_base64"])


def mutation(handler, method, runs, lock):
    if urlsplit(handler.path).path != "/api/chat/avatar":
        return False
    length = int(handler.headers.get("Content-Length", "0"))
    if not 0 < length <= 5 * 1024 * 1024 + 16384:
        handler.respond(413, {"detail": "fixture size"})
        handler.close_connection = True
        return True
    body = handler.rfile.read(length)
    token = handler.headers.get("Authorization", "").removeprefix("Bearer ")
    with lock:
        run = runs.setdefault(token, {"count": 0})
        run["count"] += 1
    if token == "avatar-disconnect":
        handler.close_connection = True
        return True
    errors = {"expired": 401, "avatar-rate": 429, "avatar-server": 503}
    if token in errors:
        handler.respond(errors[token], {"detail": "synthetic error"})
        return True
    if method == "DELETE":
        valid = json.loads(body) == {"session_id": DATA["session_id"]}
        count = {"avatar-negative": -1, "avatar-bool": True, "avatar-empty": 0}.get(token, 1)
        handler.respond(200 if valid else 400, {"deleted": count})
        return True
    mime = handler.headers.get("Content-Type", "")
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {mime}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
    )
    parts = list(message.iter_parts()) if message.is_multipart() else []
    fields = {part.get_param("name", header="content-disposition"): part for part in parts}
    valid = len(parts) == 2 and set(fields) == {"file", "session_id"}
    if valid:
        file = fields["file"]
        valid = (
            fields["session_id"].get_payload(decode=True).decode() == DATA["session_id"]
            and file.get_payload(decode=True) == IMAGE
            and file.get_filename() == "avatar.png"
            and file.get_content_type() == "image/png"
        )
    if not valid:
        handler.respond(400, {"detail": "multipart fields, Unicode or binary content changed"})
        return True
    path = DATA["upload_url"]
    if token == "avatar-wrong-owner":
        path = path.replace("ai_7_", "ai_8_")
    elif token == "avatar-wrong-session":
        path = path.replace(path.split("_")[2], "0" * 24)
    elif token == "avatar-preset":
        path = DATA["presets"]["normal"][0]
    elif token == "avatar-external":
        path = "https://example.test/avatar.png"
    handler.respond(200, {"avatar_url": path})
    return True


def resource(handler, runs, lock):
    path = urlsplit(handler.path).path
    known = [DATA["upload_url"], *DATA["presets"]["normal"], *DATA["presets"]["socratic"]]
    if path not in known:
        return False
    if handler.headers.get("Authorization") or handler.headers.get("Cookie"):
        handler.respond(400, {"detail": "public image must not receive credentials"})
        return True
    presets = DATA["presets"]["normal"]
    if path == presets[3]:
        handler.respond(302, {}, Location="/health")
        return True
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html" if path == presets[1] else "image/png")
    if path == presets[5]:
        with lock:
            runs["avatar-resource"] = {"count": 1, "closed": False}
        handler.send_header("Transfer-Encoding", "chunked")
        handler.end_headers()
        try:
            for _ in range(80):
                handler.wfile.write(b"20\r\n" + b"x" * 32 + b"\r\n")
                handler.wfile.flush()
                time.sleep(0.05)
            handler.wfile.write(b"0\r\n\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with lock:
                runs["avatar-resource"] = {"count": 1, "closed": True}
        return True
    body = b"" if path == presets[4] else IMAGE
    length = 5 * 1024 * 1024 + 1 if path == presets[2] else len(body)
    handler.send_header("Content-Length", str(length))
    handler.end_headers()
    handler.wfile.write(body)
    if path == presets[2]:
        handler.close_connection = True
    return True
