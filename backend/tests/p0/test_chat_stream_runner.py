import threading
from time import monotonic

import pytest

from ai.agent import ChatStreamError
from services import chat_stream_runner as runner
from services.web_search import BoundedExecutor


@pytest.fixture
def pool(monkeypatch):
    pool = BoundedExecutor(1, 0)
    closer = BoundedExecutor(1, 0)
    monkeypatch.setattr(runner, "_executor", lambda: pool)
    monkeypatch.setattr(runner, "_close_executor", lambda: closer)
    yield pool
    pool.shutdown()
    closer.shutdown()


def test_streaming_keeps_order_and_propagates_error(pool):
    def factory(control):
        yield "first"
        yield "second"
        raise ChatStreamError("AI_OUTPUT_LIMIT", "limit", retryable=False)

    stream = runner.cancellable_chat_stream(factory, lambda: None)
    assert next(stream) == "first"
    assert next(stream) == "second"
    with pytest.raises(ChatStreamError, match="limit"):
        next(stream)


def test_cancel_while_waiting_for_first_token_closes_upstream(pool):
    entered, closed, finished = (threading.Event() for _ in range(3))

    class WaitingUpstream:
        def close(self):
            closed.set()

    def factory(control):
        control.attach(WaitingUpstream())
        entered.set()
        try:
            assert closed.wait(2)
            yield "late"
        finally:
            finished.set()

    class Cancelled(Exception):
        pass

    def check():
        if entered.is_set():
            raise Cancelled()

    with pytest.raises(Cancelled):
        list(runner.cancellable_chat_stream(factory, check))
    assert closed.wait(1)
    assert finished.wait(1)


def test_timed_out_connect_keeps_capacity_until_worker_really_exits(pool):
    entered, release, finished = (threading.Event() for _ in range(3))

    def factory(control):
        entered.set()
        try:
            release.wait(2)
            return iter(["late"])
        finally:
            finished.set()

    try:
        with pytest.raises(ChatStreamError) as error:
            list(runner.cancellable_chat_stream(factory, lambda: None, timeout_seconds=0.04))
        assert error.value.code == "AI_STREAM_INCOMPLETE"
        assert entered.is_set()
        with pytest.raises(ChatStreamError) as busy:
            list(runner.cancellable_chat_stream(lambda _: iter(["new"]), lambda: None))
        assert busy.value.code == "AI_BUSY"
    finally:
        release.set()
    assert finished.wait(1)


def test_completed_stream_closes_attached_upstream(pool):
    closed = threading.Event()

    class Upstream:
        def close(self):
            closed.set()

    def factory(control):
        control.attach(Upstream())
        yield "answer"

    assert list(runner.cancellable_chat_stream(factory, lambda: None)) == ["answer"]
    assert closed.wait(1)


def test_blocking_upstream_close_does_not_block_cancellation_or_release_model_capacity(pool):
    entered, closing, release_close, release_read, finished = (threading.Event() for _ in range(5))

    class BlockingClose:
        def close(self):
            closing.set()
            release_close.wait(3)
            release_read.set()

    def factory(control):
        control.attach(BlockingClose())
        entered.set()
        try:
            release_read.wait(3)
            yield "late"
        finally:
            finished.set()

    class Cancelled(Exception):
        pass

    def check():
        if entered.is_set():
            raise Cancelled()

    began = monotonic()
    try:
        with pytest.raises(Cancelled):
            list(runner.cancellable_chat_stream(factory, check))
        assert monotonic() - began < 1
        assert closing.wait(1)
        assert not finished.is_set()
        with pytest.raises(ChatStreamError) as busy:
            list(runner.cancellable_chat_stream(lambda _: iter(["new"]), lambda: None))
        assert busy.value.code == "AI_BUSY"
    finally:
        release_close.set()
        release_read.set()
    assert finished.wait(1)


def test_saturated_close_pool_leaves_cleanup_to_original_worker_without_blocking_cancel(pool):
    closer_entered, release_closer, entered, release_read, closed = (
        threading.Event() for _ in range(5)
    )
    identities = {}

    def occupy_closer():
        closer_entered.set()
        release_closer.wait(3)

    runner._close_executor().submit(occupy_closer)
    assert closer_entered.wait(1)

    class Upstream:
        def close(self):
            identities["closer"] = threading.get_ident()
            closed.set()

    def factory(control):
        identities["worker"] = threading.get_ident()
        control.attach(Upstream())
        entered.set()
        release_read.wait(3)
        yield "late"

    class Cancelled(Exception):
        pass

    def check():
        if entered.is_set():
            raise Cancelled()

    began = monotonic()
    try:
        with pytest.raises(Cancelled):
            list(runner.cancellable_chat_stream(factory, check))
        assert monotonic() - began < 1
        assert not closed.is_set()
        with pytest.raises(ChatStreamError) as busy:
            list(runner.cancellable_chat_stream(lambda _: iter(["new"]), lambda: None))
        assert busy.value.code == "AI_BUSY"
        release_read.set()
        assert closed.wait(1)
        assert identities["closer"] == identities["worker"]
    finally:
        release_read.set()
        release_closer.set()


def test_upstream_attached_after_timeout_is_closed_without_publishing_late_text(pool):
    entered, release_connect, closed, finished = (threading.Event() for _ in range(4))
    observed = []

    class Upstream:
        def close(self):
            closed.set()

    def factory(control):
        entered.set()
        try:
            release_connect.wait(3)
            observed.append(control.cancelled.is_set())
            control.attach(Upstream())
            return iter(["late"])
        finally:
            finished.set()

    try:
        with pytest.raises(ChatStreamError) as timeout:
            list(runner.cancellable_chat_stream(factory, lambda: None, timeout_seconds=0.04))
        assert timeout.value.code == "AI_STREAM_INCOMPLETE"
        assert entered.is_set()
    finally:
        release_connect.set()
    assert closed.wait(1)
    assert finished.wait(1)
    assert observed == [True]


def test_repeated_stop_submits_at_most_one_close_for_an_attached_upstream(pool):
    entered, release = threading.Event(), threading.Event()
    calls = []

    class Upstream:
        def close(self):
            calls.append(threading.get_ident())
            entered.set()
            release.wait(3)

    control = runner.StreamControl()
    control.attach(Upstream())
    try:
        for _ in range(5):
            control.stop()
        assert entered.wait(1)
        assert len(calls) == 1
    finally:
        release.set()
