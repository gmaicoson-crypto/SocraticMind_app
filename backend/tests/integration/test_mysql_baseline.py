"""MySQL-dialect migration and application startup checks for the imported baseline."""

import os
from pathlib import Path
import subprocess
import sys
import uuid

from alembic import command
from alembic.config import Config
import pymysql
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL

from core.migrations import assert_database_at_head


BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture()
def mysql_database():
    socket_path = os.environ.get("SOCRATIC_TEST_MYSQL_SOCKET")
    if not socket_path:
        pytest.fail("Run through scripts/dev/verify_backend_mysql.py; no existing database is used")
    socket_file = Path(socket_path)
    if not socket_file.parent.name.startswith("sm-mysql-") or not socket_file.is_socket():
        pytest.fail("Expected the disposable harness Unix socket")
    database = "socratic_test_" + uuid.uuid4().hex
    connection = pymysql.connect(user="root", unix_socket=socket_path, autocommit=True)
    created = False
    engine = None
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4")
        created = True
        url = URL.create(
            "mysql+pymysql",
            username="root",
            database=database,
            query={"unix_socket": socket_path, "charset": "utf8mb4"},
        )
        engine = create_engine(url)
        config = Config(str(BACKEND / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND / "alembic"))
        config.set_main_option("sqlalchemy.url", url.render_as_string().replace("%", "%%"))
        yield engine, config, url.render_as_string()
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with connection.cursor() as cursor:
                cursor.execute(f"DROP DATABASE `{database}`")
        connection.close()


def test_mysql_empty_database_upgrades_to_head(mysql_database):
    engine, config, _ = mysql_database
    command.upgrade(config, "head")
    assert_database_at_head(engine)
    inspector = inspect(engine)
    assert {"users", "nodes", "chat_turns", "attachments", "agent_runs"}.issubset(
        inspector.get_table_names()
    )
    assert "uq_chat_turns_user_request" in {
        index["name"] for index in inspector.get_indexes("chat_turns")
    }
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT VERSION()"))
        assert connection.scalar(text("SELECT COUNT(*) FROM alembic_version")) == 1


def test_mysql_previous_revision_upgrade_keeps_unicode_user(mysql_database):
    engine, config, _ = mysql_database
    command.upgrade(config, "0012_chat_attachments")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (username, email, hashed_password, avatar_url, is_active) "
                "VALUES (:name, :email, :password, :avatar, 1)"
            ),
            {
                "name": "中文学习者",
                "email": "migration@example.test",
                "password": "test-only",
                "avatar": "/avatars/study/boy-read.webp",
            },
        )
    command.upgrade(config, "head")
    assert_database_at_head(engine)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT username FROM users")) == "中文学习者"
    assert "chat_session_titles" in inspect(engine).get_table_names()


def test_mysql_application_lifespan_and_health(mysql_database, tmp_path):
    _, config, url = mysql_database
    command.upgrade(config, "head")
    environment = os.environ.copy()
    environment.update(
        DATABASE_URL=url,
        SECRET_KEY="isolated-mysql-test-secret",
        LLM_MODELS="",
        LLM_API_KEY="test-key",
        LLM_BASE_URL="http://127.0.0.1:1/v1",
        LLM_MODEL="test-model",
        WEB_SEARCH_ENABLED="false",
        SMTP_HOST="",
        ATTACHMENT_STORAGE_DIR=str(tmp_path / "attachments"),
        PYTHONPATH=str(BACKEND),
    )
    code = (
        "from fastapi.testclient import TestClient\n"
        "from main import app\n"
        "with TestClient(app) as client:\n"
        "    response = client.get('/health')\n"
        "    assert response.status_code == 200, response.text\n"
        "    assert response.json() == {'status': 'ok'}\n"
        "print('lifespan and health passed')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "lifespan and health passed" in result.stdout
