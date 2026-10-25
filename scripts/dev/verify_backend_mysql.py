"""Run migration/startup checks against a private, disposable MySQL instance."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from mysql_runtime import initialize, running_mysql


ROOT = Path(__file__).resolve().parents[2]
TEST_FILE = "tests/integration/test_mysql_baseline.py"
TESTS = {
    "test_mysql_empty_database_upgrades_to_head": TEST_FILE,
    "test_mysql_previous_revision_upgrade_keeps_unicode_user": TEST_FILE,
    "test_mysql_application_lifespan_and_health": TEST_FILE,
    "test_mysql_history_window_and_unicode_projection": "tests/integration/test_mysql_chat_history.py",
    "test_mysql_usage_checkpoint_and_new_turn_fence": "tests/integration/test_mysql_chat_feedback.py",
}


def run(mysqld: str, selected: list[str]) -> int:
    # Disposable checks reuse the same MySQL process owner as persistent local development.
    with tempfile.TemporaryDirectory(prefix="sm-mysql-", dir="/tmp") as temporary:
        directory = Path(temporary)
        initialize(mysqld, directory / "mysql", directory / "mysql.log")
        with running_mysql(mysqld, directory) as (_, socket_path):
            environment = os.environ.copy()
            environment["SOCRATIC_TEST_MYSQL_SOCKET"] = str(socket_path)
            print("Disposable MySQL ready (Unix socket only); running explicitly selected tests.")
            return subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "--tb=short",
                    *[f"{TESTS[name]}::{name}" for name in selected],
                ],
                cwd=ROOT / "backend",
                env=environment,
                timeout=120,
            ).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysqld", default=shutil.which("mysqld"))
    parser.add_argument("--test", action="append", choices=TESTS)
    arguments = parser.parse_args()
    if not arguments.mysqld:
        parser.error("mysqld is required; this command never connects to an existing server")
    return run(arguments.mysqld, arguments.test or list(TESTS))


if __name__ == "__main__":
    raise SystemExit(main())
