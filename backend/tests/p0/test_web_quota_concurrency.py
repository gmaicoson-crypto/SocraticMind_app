from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.config import settings
from core.database import Base
from models import User, WebSearchQuota
from services.chat_lifecycle import begin_chat_turn
from services.web_search_quota import reserve_web_queries


def test_two_sessions_share_one_atomic_daily_user_allowance(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "web_search_daily_query_limit", 1)
    monkeypatch.setattr(settings, "web_search_global_daily_query_limit", 10)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'quota-race.sqlite'}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    try:
        with sessions() as db:
            user = User(
                username="quota-race", email="quota-race@example.test", hashed_password="unused"
            )
            db.add(user)
            db.commit()
            user_id = user.id
            attempts = []
            for i in range(2):
                started = begin_chat_turn(
                    db,
                    user_id=user_id,
                    topic_id=None,
                    session_id=f"session-{i}",
                    request_id=f"request-{i}",
                    node_key="normal",
                    user_input="question",
                    mode="normal",
                    model_id="unused",
                )
                attempts.append((started.turn.request_id, started.turn.generation_token))
        barrier = Barrier(2)

        def attempt(identity):
            with sessions() as db:
                barrier.wait(timeout=5)
                return reserve_web_queries(
                    db,
                    user_id=user_id,
                    request_id=identity[0],
                    generation_token=identity[1],
                    queries=1,
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, attempts))
        assert sorted(results) == [False, True]
        with sessions() as db:
            assert {quota.scope: quota.used_queries for quota in db.query(WebSearchQuota)} == {
                "tavily": 1,
                f"user:{user_id}": 1,
            }
    finally:
        engine.dispose()
