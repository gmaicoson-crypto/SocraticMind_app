"""Export/check the provider schema without loading real env files or starting workers."""

import argparse
import json
import os
from pathlib import Path
import socket
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "contracts/openapi/socraticmind.json"


def deny_network(*_arguments, **_keywords):
    raise RuntimeError("Network access is forbidden during contract export")


def provider_schema() -> dict:
    # This is a standalone process. Do not import the application before isolation.
    os.environ.clear()
    os.environ.update(
        DATABASE_URL="sqlite://",
        SECRET_KEY="contract-export-test-only",
        LLM_API_KEY="contract-placeholder",
        LLM_BASE_URL="https://models.example.invalid/v1",
        LLM_MODEL="contract-model",
        WEB_SEARCH_ENABLED="false",
        SMTP_HOST="",
    )
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    socket.create_connection = deny_network
    sys.path.insert(0, str(ROOT / "backend"))
    with tempfile.TemporaryDirectory(prefix="socratic-contract-") as temporary:
        os.chdir(temporary)
        from core import avatar_uploads

        avatar_uploads.UPLOAD_DIR = Path(temporary) / "avatars"
        from main import app

        # No lifespan, workers, HTTP calls or database connections are needed here.
        return app.openapi()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    schema = provider_schema()
    serialized = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if arguments.check:
        if not SNAPSHOT.exists() or SNAPSHOT.read_text() != serialized:
            print("OpenAPI snapshot is missing or stale; review provider changes before exporting.")
            return 1
        print(f"OpenAPI snapshot matches provider ({len(schema['paths'])} paths).")
        return 0
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(serialized)
    print(f"Exported {len(schema['paths'])} paths to {SNAPSHOT.relative_to(ROOT)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
