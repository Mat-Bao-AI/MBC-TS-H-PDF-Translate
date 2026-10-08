from app.auth.ratelimit import SlidingWindow


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_blocks_at_limit_and_recovers_after_window():
    clock = Clock()
    limiter = SlidingWindow(limit=2, window_seconds=60, clock=clock)
    assert not limiter.blocked("k")
    limiter.hit("k")
    limiter.hit("k")
    assert limiter.blocked("k")
    clock.now += 61
    assert not limiter.blocked("k")


def test_keys_are_independent_and_reset_clears():
    limiter = SlidingWindow(limit=1, window_seconds=60, clock=Clock())
    limiter.hit("a")
    assert limiter.blocked("a") and not limiter.blocked("b")
    limiter.reset("a")
    assert not limiter.blocked("a")


def test_attempt_checks_and_records_atomically():
    clock = Clock()
    limiter = SlidingWindow(limit=2, window_seconds=60, clock=clock)
    assert limiter.attempt("k") and limiter.attempt("k")
    assert not limiter.attempt("k")  # bị chặn: không ghi thêm lượt, cửa sổ không bị kéo dài
    clock.now += 61
    assert limiter.attempt("k")


def test_forgive_removes_only_the_latest_hit():
    limiter = SlidingWindow(limit=2, window_seconds=60, clock=Clock())
    limiter.hit("k")
    limiter.hit("k")
    limiter.forgive("k")
    assert not limiter.blocked("k")
    limiter.forgive("khong-co")  # không lỗi
    limiter.forgive("k")
    limiter.forgive("k")
    assert not limiter.blocked("k")


def test_expired_keys_are_swept_so_memory_stays_bounded():
    clock = Clock()
    limiter = SlidingWindow(limit=5, window_seconds=60, clock=clock)
    for index in range(1000):
        limiter.hit(f"rac-{index}")
    clock.now += 61
    for index in range(SlidingWindow.SWEEP_EVERY):
        limiter.hit(f"moi-{index}")
    assert not any(key.startswith("rac-") for key in limiter._hits)
