"""Private persistent local configuration, distinct from disposable verification data."""

import fcntl
import json
import os
import secrets
import uuid
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy.engine import URL


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIRECTORY = ROOT / "local-data/backend"
DATABASE = "socraticmind_local"
MARKER = "socraticmind-local-v1"


@contextmanager
def exclusive_directory(directory: Path):
    if directory.is_symlink():
        raise ValueError("Local data directory must not be a symbolic link")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
        raise ValueError("Local data directory must be owned by this user with mode 700")
    with (directory / ".run.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Another command owns this local environment") from error
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def write_private(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(value)


def identity(directory: Path) -> dict:
    path = directory / "identity.json"
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError("Identity must be a private regular file (mode 600)")
    value = json.loads(path.read_text())
    if value.get("kind") != MARKER or not value.get("secret_key") or not value.get("id"):
        raise ValueError("Unrecognized local environment identity")
    return value


def prepare(directory: Path) -> bool:
    if (directory / "identity.json").exists():
        identity(directory)
        return False
    if any(path.name != ".run.lock" for path in directory.iterdir()):
        raise ValueError("Refusing to adopt a nonempty directory without a local identity")
    value = {"kind": MARKER, "id": uuid.uuid4().hex, "secret_key": secrets.token_urlsafe(48)}
    write_private(directory / "identity.json", json.dumps(value, indent=2) + "\n")
    write_private(
        directory / ".env",
        "# Local AI configuration; never commit this file.\n"
        "# Fill with a real compatible model; no fake responses are provided.\n"
        "LLM_MODELS=\nLLM_API_KEY=\nLLM_BASE_URL=\nLLM_MODEL=\n"
        "SMTP_HOST=\nWEB_SEARCH_ENABLED=false\nTAVILY_API_KEY=\n",
    )
    for name in ("attachments", "avatars", "logs"):
        (directory / name).mkdir(mode=0o700)
    return True


def child_environment(directory: Path) -> dict[str, str]:
    value = identity(directory)
    # Do not inherit another project's database, model, mail, or signing secrets.
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "HOME", "LANG", "TMPDIR", "SYSTEMROOT"} or key.startswith("LC_")
    }
    url = URL.create(
        "mysql+pymysql",
        username="root",
        database=DATABASE,
        query={"unix_socket": str(directory / "mysql.sock"), "charset": "utf8mb4"},
    )
    environment.update(
        PYTHONPATH=str(ROOT / "backend"),
        PYTHONUNBUFFERED="1",
        DATABASE_URL=url.render_as_string(hide_password=False),
        SECRET_KEY=value["secret_key"],
        ATTACHMENT_STORAGE_DIR=str(directory / "attachments"),
        AVATAR_STORAGE_DIR=str(directory / "avatars"),
        SOCRATIC_LOCAL_ID=value["id"],
    )
    return environment
