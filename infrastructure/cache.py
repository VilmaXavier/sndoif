"""
Simple in-memory, time-based cache for slow infrastructure lookups
(WHOIS, certificate transparency, DNS resolution).

These external services are frequently slow or unreliable (crt.sh
especially, observed failing repeatedly during development), and the
same domains get re-checked on nearly every search. Caching results
for a bounded time avoids redundant slow/flaky calls without risking
badly stale data, since infrastructure facts (registrar, certificates,
IPs) change infrequently.
"""

import functools
import logging
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 3600

_cache: dict[str, tuple[Any, float]] = {}


def cached(ttl_seconds: int = DEFAULT_TTL_SECONDS, skip_empty: bool = True) -> Callable:
    """Decorator: cache a function's return value, keyed by its
    arguments, for ttl_seconds.

    Args:
        ttl_seconds: How long a cached entry remains valid.
        skip_empty: If True (default), a falsy result (empty list,
            empty dict, None, etc.) is NOT cached. This matters because
            an empty result from these functions usually means the
            lookup failed (e.g. crt.sh returned a 502) rather than
            meaning "genuinely zero results" -- caching a failure would
            make the retry logic's recovery pointless, since every
            subsequent call would just replay the cached failure
            instead of trying again.

    Returns:
        A decorator to apply to a function whose arguments are all
        hashable (e.g. strings).
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = f"{func.__name__}:{args}{sorted(kwargs.items())}"

            if key in _cache:
                value, cached_at = _cache[key]
                age = time.time() - cached_at
                if age < ttl_seconds:
                    logger.info("Cache hit for %s (age %.0fs)", key, age)
                    return value
                logger.info("Cache expired for %s (age %.0fs)", key, age)

            result = func(*args, **kwargs)

            if skip_empty and not result:
                logger.info("Not caching empty/failed result for %s", key)
            else:
                _cache[key] = (result, time.time())

            return result

        return wrapper
    return decorator


def clear_cache() -> None:
    """Clear all cached entries. Useful for tests or manual reset."""
    _cache.clear()
