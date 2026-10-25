"""Keep the owning chat thread responsive while a synchronous provider waits."""

import logging
import threading
from functools import lru_cache
from queue import Empty, Full, Queue
from time import monotonic
from typing import Callable, Iterator

from ai.agent import ChatStreamError
from core.config import settings
from services.web_search import BoundedExecutor, CapacityExceeded

log = logging.getLogger(__name__)


class StreamControl:
    def __init__(self):
        self.cancelled = threading.Event()
        self._lock = threading.Lock()
        self._upstream = None

    def attach(self, upstream):
        with self._lock:
            self._upstream = upstream
        if self.cancelled.is_set():
            self.stop()

    def stop(self):
        """Publish cancellation without waiting on provider-specific close locks."""
        self.cancelled.set()
        with self._lock:
            if self._upstream is None:
                return
            try:
                _close_executor().submit(self._close, self._upstream)
            except (CapacityExceeded, RuntimeError):
                # The bounded closer can be occupied by slow provider cleanup.
                # Leave ownership here so the original worker closes it on exit;
                # its model slot remains occupied while the provider still waits.
                return
            self._upstream = None

    def close_from_worker(self):
        with self._lock:
            upstream, self._upstream = self._upstream, None
        self._close(upstream)

    @staticmethod
    def _close(upstream):
        close = getattr(upstream, "close", None)
        if close:
            try:
                close()
            except Exception:
                log.debug("chat_upstream_close_failed")


@lru_cache(maxsize=1)
def _executor():
    return BoundedExecutor(settings.chat_stream_max_workers, 0)


@lru_cache(maxsize=1)
def _close_executor():
    # A slow sync close must not block the owning thread, and it must not create
    # one detached thread per request. With no pending queue, total close tasks
    # are bounded independently of model tasks even if providers never return.
    return BoundedExecutor(settings.chat_stream_max_workers, 0)


def cancellable_chat_stream(
    factory: Callable[[StreamControl], Iterator[str]],
    check_active: Callable[[], None],
    *,
    timeout_seconds: float = 300,
) -> Iterator[str]:
    """No DB access in the worker, no unbounded buffering or orphaned capacity."""
    control = StreamControl()
    messages = Queue(maxsize=8)
    deadline = monotonic() + timeout_seconds

    def publish(kind, value=None):
        while not control.cancelled.is_set():
            try:
                messages.put((kind, value), timeout=0.1)
                return True
            except Full:
                pass
        return False

    def produce():
        stream = None
        try:
            if control.cancelled.is_set():
                return
            stream = factory(control)
            for chunk in stream:
                if not publish("chunk", chunk):
                    break
        except Exception as error:
            publish("error", error)
        else:
            publish("done")
        finally:
            close = getattr(stream, "close", None)
            if close:
                try:
                    close()
                except Exception:
                    log.debug("chat_generator_close_failed")
            control.close_from_worker()

    check_active()
    try:
        future = _executor().submit(produce)
    except CapacityExceeded as error:
        raise ChatStreamError(
            "AI_BUSY", "当前生成请求较多，请稍后重试。", retryable=True
        ) from error
    try:
        while True:
            check_active()
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise ChatStreamError("AI_TIMEOUT", "等待模型回复超时，请重试。", retryable=True)
            try:
                kind, value = messages.get(timeout=min(0.2, remaining))
            except Empty:
                continue
            check_active()
            if kind == "done":
                return
            if kind == "error":
                raise value
            yield value
    finally:
        control.stop()
        future.cancel()
