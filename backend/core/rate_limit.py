import time
from collections import defaultdict, deque
from threading import Lock

# 进程内滑动窗口限流，单实例部署已足够；若需多实例横向扩展，应换用 Redis 实现
_buckets: dict[str, deque[float]] = defaultdict(deque)
_locks: dict[str, Lock] = defaultdict(Lock)
_global_lock = Lock()  # 保护 _locks 字典本身的并发写入

# 登录失败记录：email -> (累计失败次数, 锁定截止时间戳)
_login_fail: dict[str, tuple[int, float]] = {}

LOGIN_MAX_FAILS = 5  # 连续失败超过此次数后触发账号锁定
LOGIN_LOCK_SECONDS = 15 * 60  # 锁定时长：15 分钟


def _get_lock(key: str) -> Lock:
    """为每个限流 key 分配独立锁，避免不同 key 之间的互斥竞争。"""
    with _global_lock:
        return _locks[key]


def hit(key: str, max_calls: int, window_seconds: int) -> bool:
    """滑动窗口计数：返回 True 表示允许本次请求，False 表示已触发限流。

    每次调用时顺带清理窗口外的过期记录，防止 deque 无限增长。
    """
    now = time.time()
    cutoff = now - window_seconds
    lock = _get_lock(key)
    with lock:
        q = _buckets[key]
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= max_calls:
            return False
        q.append(now)
        return True


def remaining_seconds(key: str, window_seconds: int) -> int:
    """触发限流后，返回用户还需等待多少秒才能再次请求（取队首时间戳计算）。"""
    q = _buckets.get(key)
    if not q:
        return 0
    now = time.time()
    wait = int(q[0] + window_seconds - now)
    return max(wait, 0)


def is_login_locked(email: str) -> int:
    """检查账号是否处于登录锁定状态，返回剩余锁定秒数；0 表示未锁定。"""
    rec = _login_fail.get(email)
    if not rec:
        return 0
    _, lock_until = rec
    rem = int(lock_until - time.time())
    return rem if rem > 0 else 0


def record_login_fail(email: str) -> int:
    """记录一次登录失败，达到阈值后锁定账号。返回当前累计失败次数。

    若上次锁定已自然到期，则重置计数器重新累计。
    """
    now = time.time()
    fails, lock_until = _login_fail.get(email, (0, 0.0))
    if lock_until and now > lock_until:
        fails = 0  # 锁定已过期，重置计数
    fails += 1
    if fails >= LOGIN_MAX_FAILS:
        lock_until = now + LOGIN_LOCK_SECONDS
    _login_fail[email] = (fails, lock_until)
    return fails


def reset_login_fail(email: str) -> None:
    """登录成功或注销账号后清除该邮箱的失败记录，避免状态残留影响重新注册。"""
    _login_fail.pop(email, None)
