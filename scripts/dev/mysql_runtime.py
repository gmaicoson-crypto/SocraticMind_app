"""Owned MySQL subprocesses only; never connect to a system service."""

import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import pymysql


def initialize(mysqld: str, data: Path, log: Path) -> None:
    if data.exists() and any(data.iterdir()):
        raise ValueError("Refusing to initialize a nonempty MySQL directory")
    with log.open("ab") as output:
        result = subprocess.run(
            [mysqld, "--no-defaults", "--initialize-insecure", f"--datadir={data}"],
            stdout=output,
            stderr=subprocess.STDOUT,
            timeout=60,
        )
    if result.returncode:
        raise RuntimeError(f"MySQL initialization failed; inspect {log}")


def wait_for_mysql(process: subprocess.Popen, socket_path: Path) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Owned MySQL exited before becoming ready; inspect its log")
        try:
            connection = pymysql.connect(
                user="root", unix_socket=str(socket_path), connect_timeout=1
            )
            connection.close()
            return
        except pymysql.OperationalError:
            time.sleep(0.2)
    raise TimeoutError("Owned MySQL did not become ready within 30 seconds")


def stop_owned(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@contextmanager
def running_mysql(mysqld: str, directory: Path):
    socket_path = directory / "mysql.sock"
    if len(str(socket_path).encode()) >= 100:
        raise ValueError("MySQL socket path is too long; use a shorter data directory")
    if not (directory / "mysql" / "mysql").is_dir():
        raise ValueError("MySQL has not been initialized in this directory")
    with (directory / "mysql.log").open("ab") as output:
        process = subprocess.Popen(
            [
                mysqld,
                "--no-defaults",
                f"--datadir={directory / 'mysql'}",
                f"--socket={socket_path}",
                f"--pid-file={directory / 'mysql.pid'}",
                "--skip-networking",
                "--mysqlx=OFF",
                "--innodb-buffer-pool-size=64M",
            ],
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        try:
            wait_for_mysql(process, socket_path)
            yield process, socket_path
        finally:
            stop_owned(process)
