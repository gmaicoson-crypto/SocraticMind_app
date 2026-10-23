from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


BACKEND_DIR = Path(__file__).resolve().parents[1]


def required_revisions() -> set[str]:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return set(ScriptDirectory.from_config(config).get_heads())


def assert_database_at_head(engine: Engine) -> None:
    with engine.connect() as connection:
        if "alembic_version" not in inspect(connection).get_table_names():
            raise RuntimeError(
                "Database schema is not managed by Alembic. Run `alembic upgrade head` "
                "for an empty database, or verify and stamp a legacy database first."
            )
        current = {
            row[0] for row in connection.execute(text("SELECT version_num FROM alembic_version"))
        }
    required = required_revisions()
    if current != required:
        raise RuntimeError(
            "Database migration required: "
            f"current={sorted(current) or ['none']} required={sorted(required)}. "
            "Run `alembic upgrade head` before starting the API."
        )
