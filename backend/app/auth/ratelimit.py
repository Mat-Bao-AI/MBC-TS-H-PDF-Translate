from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable


class SlidingWindow:
    """Đếm sự kiện theo khoá trong RAM. Mất khi restart — chấp nhận với một container."""

    SWEEP_EVERY = 512  # sau ngần này lượt ghi thì dọn các khoá đã hết hạn (khoá do người lạ tự đặt)

    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._writes = 0

    def _live(self, key: str) -> deque[float] | None:
        hits = self._hits.get(key)
        if hits is None:
            return None
        cutoff = self._clock() - self.window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if not hits:
            del self._hits[key]
            return None
        return hits

    def _record(self, key: str, hits: deque[float] | None) -> None:
        if hits is None:
            hits = self._hits[key] = deque()
        hits.append(self._clock())
        self._writes += 1
        if self._writes % self.SWEEP_EVERY == 0:
            # Khoá chỉ tự xoá khi được hỏi lại; khoá rác (email/IP ngẫu nhiên) thì không bao giờ
            # được hỏi lại — không dọn định kỳ thì RAM phình mãi.
            cutoff = self._clock() - self.window
            for stale in [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]:
                del self._hits[stale]

    def blocked(self, key: str) -> bool:
        with self._lock:
            hits = self._live(key)
            return hits is not None and len(hits) >= self.limit

    def hit(self, key: str) -> None:
        with self._lock:
            self._record(key, self._live(key))

    def attempt(self, key: str) -> bool:
        """Kiểm + ghi trong CÙNG một lần khoá: N request song song không lọt quá `limit`.

        Trả False (và không ghi) khi đã chạm trần."""
        with self._lock:
            hits = self._live(key)
            if hits is not None and len(hits) >= self.limit:
                return False
            self._record(key, hits)
            return True

    def forgive(self, key: str) -> None:
        """Bỏ lượt ghi gần nhất — cho lượt đã ghi trước nhưng hoá ra hợp lệ."""
        with self._lock:
            hits = self._live(key)
            if hits:
                hits.pop()
                if not hits:
                    del self._hits[key]

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
