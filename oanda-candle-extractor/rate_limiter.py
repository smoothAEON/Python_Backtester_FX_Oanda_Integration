"""Rate limiter with paced permits for OANDA API compliance."""
import logging
import threading
import time
from collections import deque
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class RequestPriority(Enum):
    """Priority levels for API requests."""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


class RateLimiter:
    """
    Thread-safe paced rate limiter.

    Permits are spaced evenly across the configured window so concurrent
    callers share one global ceiling instead of bunching into bursts.
    """

    def __init__(self, max_requests: int = 119, window_seconds: float = 1.0):
        """
        Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed in window
            window_seconds: Time window in seconds
        """
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")

        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._interval_seconds = window_seconds / max_requests
        self._requests: deque = deque()
        self._lock = threading.Lock()
        self._backoff_until: Optional[float] = None
        self._consecutive_429s = 0
        self._next_available_at = 0.0

    def _cleanup_old_requests(self) -> None:
        """Remove requests older than the window."""
        cutoff = time.monotonic() - self._window_seconds
        while self._requests and self._requests[0] < cutoff:
            self._requests.popleft()
    
    def acquire(
        self,
        timeout: float = 30.0,
        priority: RequestPriority = RequestPriority.NORMAL
    ) -> bool:
        """
        Acquire permission to make a request.
        
        Blocks until rate limit allows or timeout is reached.
        
        Args:
            timeout: Maximum time to wait in seconds
            priority: Request priority level
            
        Returns:
            True if acquired, False if timeout
        """
        del priority  # Reserved for backward compatibility; permits are shared equally.
        start_time = time.monotonic()

        while True:
            with self._lock:
                now = time.monotonic()
                if self._backoff_until and now < self._backoff_until:
                    permit_at = self._backoff_until
                else:
                    self._backoff_until = None
                    permit_at = max(now, self._next_available_at)
                    self._next_available_at = permit_at + self._interval_seconds
                    self._requests.append(permit_at)
                    self._cleanup_old_requests()
                    wait_time = max(0.0, permit_at - now)
                    break

                wait_time = max(0.0, permit_at - now)

            elapsed = time.monotonic() - start_time
            if elapsed + wait_time > timeout:
                logger.warning("Rate limiter: timeout after %.2fs", timeout)
                return False
            if wait_time > 0:
                time.sleep(wait_time)

        if wait_time > 0:
            time.sleep(wait_time)
        return True

    def record_429(self, retry_after_seconds: Optional[float] = None) -> None:
        """Record a 429 (rate limit) response and apply backoff."""
        with self._lock:
            self._consecutive_429s += 1
            if retry_after_seconds is not None:
                backoff_seconds = max(0.0, retry_after_seconds)
            else:
                backoff_seconds = min(2 ** self._consecutive_429s, 60)

            until = time.monotonic() + backoff_seconds
            self._backoff_until = max(self._backoff_until or 0.0, until)
            self._next_available_at = max(self._next_available_at, self._backoff_until)
            logger.warning("Rate limiter: 429 received, backing off for %.2fs", backoff_seconds)
    
    def record_success(self) -> None:
        """Record a successful request and reset backoff."""
        with self._lock:
            self._consecutive_429s = 0
            self._backoff_until = None
    
    def get_current_rate(self) -> float:
        """Get current request rate (requests per second)."""
        with self._lock:
            self._cleanup_old_requests()
            return float(len(self._requests)) / self._window_seconds

    def get_available_capacity(self) -> int:
        """Get number of requests available in current window."""
        with self._lock:
            self._cleanup_old_requests()
            return max(0, self._max_requests - len(self._requests))
