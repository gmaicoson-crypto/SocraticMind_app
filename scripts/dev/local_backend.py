"""Initialize and supervise the repository's persistent, loopback-only backend."""

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pymysql

from scripts.dev.local_environment import (
    DATABASE,
    DEFAULT_DIRECTORY,
    ROOT,
    child_environment,
    exclusive_directory,
    identity,
    prepare,
)
from scripts.dev.mysql_runtime import initialize, running_mysql, stop_owned


def check_configuration(directory: Path) -> dict:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/dev/serve_backend.py"), "--check-config"],
        cwd=directory,
        env=child_environment(directory),
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    return json.loads(result.stdout)


def migrate(directory: Path, socket_path: Path) -> None:
    connection = pymysql.connect(user="root", unix_socket=str(socket_path), autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DATABASE}` CHARACTER SET utf8mb4")
    finally:
        connection.close()
    with (directory / "logs/migrations.log").open("ab") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                str(ROOT / "backend/alembic.ini"),
                "upgrade",
                "head",
            ],
            cwd=directory,
            env=child_environment(directory),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            if process.wait(timeout=60):
                raise RuntimeError("Migration failed; inspect logs/migrations.log before retrying")
        finally:
            stop_owned(process)


def wait_for_api(process: subprocess.Popen, url: str) -> None:
    deadline = time.monotonic() + 30
    with httpx.Client(trust_env=False, timeout=1) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Backend exited; inspect logs/backend.log")
            try:
                response = client.get(url + "/health")
                if response.status_code == 200 and response.json() == {"status": "ok"}:
                    return
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(0.2)
    raise TimeoutError("Backend did not become ready within 30 seconds")


def run(directory: Path, mysqld: str, port: int) -> int:
    configuration = check_configuration(directory)
    if not configuration["settings_valid"]:
        raise ValueError("Invalid local .env configuration; values are not printed")
    if not configuration["models_configured"]:
        print("Model configuration missing/invalid: AI functions remain unavailable.", flush=True)
    # Reserve the exact loopback socket and pass it to our child, avoiding a readiness/port race.
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", port))
        listener.listen(128)
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        with running_mysql(mysqld, directory) as (mysql, socket_path):
            migrate(directory, socket_path)
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "scripts/dev/serve_backend.py"),
                    "--fd",
                    str(listener.fileno()),
                ],
                cwd=directory,
                env=child_environment(directory),
                pass_fds=(listener.fileno(),),
            )
            try:
                wait_for_api(process, url)
                runtime = {"id": identity(directory)["id"], "url": url, "pid": process.pid}
                (directory / "runtime.json").write_text(json.dumps(runtime) + "\n")
                print(
                    f"Ready: {url} — Ctrl+C stops owned processes and preserves data.", flush=True
                )
                print(
                    f"Private logs and development email codes: {directory / 'logs/backend.log'}",
                    flush=True,
                )
                while process.poll() is None and mysql.poll() is None:
                    time.sleep(0.25)
                raise RuntimeError("A supervised process exited unexpectedly; inspect local logs")
            finally:
                stop_owned(process)
                (directory / "runtime.json").unlink(missing_ok=True)


def status(directory: Path) -> dict:
    current = identity(directory)
    runtime_file = directory / "runtime.json"
    if not runtime_file.exists():
        return {"state": "stopped", "data_preserved": True}
    runtime = json.loads(runtime_file.read_text())
    address = urlsplit(runtime["url"])
    if (
        runtime["id"] != current["id"]
        or address.scheme != "http"
        or address.hostname != "127.0.0.1"
        or address.username is not None
        or address.password is not None
        or address.path
        or address.query
        or address.fragment
        or address.port is None
    ):
        raise ValueError("Unrecognized runtime record")
    try:
        with httpx.Client(trust_env=False, timeout=2) as client:
            response = client.get(runtime["url"] + "/health")
            healthy = response.status_code == 200 and response.json() == {"status": "ok"}
    except (httpx.HTTPError, ValueError):
        healthy = False
    return {"state": "healthy" if healthy else "unreachable", "url": runtime["url"]}


def interrupt(_signal, _frame):
    raise KeyboardInterrupt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "run", "status", "doctor"))
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument("--mysqld", default=shutil.which("mysqld"))
    parser.add_argument("--port", type=int, default=8765)
    arguments = parser.parse_args()
    if not 0 <= arguments.port <= 65535:
        parser.error("Port must be between 0 and 65535")
    directory = arguments.directory.absolute()
    os.umask(0o077)
    signal.signal(signal.SIGTERM, interrupt)
    try:
        if arguments.command == "status":
            print(json.dumps(status(directory)))
            return 0
        with exclusive_directory(directory):
            if arguments.command == "doctor":
                result = check_configuration(directory)
                print(json.dumps(result))
                return int(not result["settings_valid"])
            if not arguments.mysqld:
                parser.error("mysqld is required; no system database is used")
            if arguments.command == "init":
                prepare(directory)
                if not (directory / "mysql/mysql").is_dir():
                    initialize(arguments.mysqld, directory / "mysql", directory / "mysql.log")
                print(f"Local environment initialized: {directory}")
                return 0
            identity(directory)
            return run(directory, arguments.mysqld, arguments.port)
    except KeyboardInterrupt:
        print("Stopped owned processes; persistent data retained.")
        return 0
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(f"Local environment error ({type(error).__name__}): {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
