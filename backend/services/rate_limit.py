"""
Per-user AI rate limiting — an in-process sliding-window counter keyed on user id.
Valid because the app runs as a single Waitress process (no cross-process state to
share). Cloud (Anthropic) calls are limited more tightly than local Ollama.
"""

import threading
import time

_PER_MINUTE = {"anthropic": 10, "ollama": 30}
_PER_DAY = {"anthropic": 100, "ollama": 1000}
_DEFAULT_MINUTE, _DEFAULT_DAY = 10, 100

_lock = threading.Lock()
_hits: dict = {}  # (user_id, provider) -> list[timestamp]


def check_and_consume(user_id, provider: str) -> tuple[bool, str]:
    """Returns (allowed, message). Consumes one token when allowed."""
    now = time.time()
    per_min = _PER_MINUTE.get(provider, _DEFAULT_MINUTE)
    per_day = _PER_DAY.get(provider, _DEFAULT_DAY)
    key = (user_id, provider)
    with _lock:
        hits = [t for t in _hits.get(key, []) if now - t < 86400]
        in_last_minute = sum(1 for t in hits if now - t < 60)
        if in_last_minute >= per_min:
            _hits[key] = hits
            return False, (f"You've hit the rate limit ({per_min} requests/minute for this "
                           "model). Please wait a moment and try again.")
        if len(hits) >= per_day:
            _hits[key] = hits
            return False, (f"Daily limit reached ({per_day} requests for this model). "
                           "Please try again tomorrow.")
        hits.append(now)
        _hits[key] = hits
        return True, ""
