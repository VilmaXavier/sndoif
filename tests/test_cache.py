"""
Tests for the infrastructure cache decorator.
"""

import time

from infrastructure.cache import cached, clear_cache


def test_cached_function_returns_same_result_without_recomputing():
    call_count = {"n": 0}

    @cached()
    def slow_function(x):
        call_count["n"] += 1
        return x * 2

    assert slow_function(5) == 10
    assert slow_function(5) == 10
    assert call_count["n"] == 1  # only computed once, second call was a cache hit


def test_cached_does_not_cache_empty_result_by_default():
    """Regression test for a real bug found during development: an
    empty/failed result (e.g. from a crt.sh outage) must NOT be
    cached, since that would make the underlying function's own retry
    logic pointless -- every subsequent call would just replay the
    cached failure instead of trying again.
    """
    call_count = {"n": 0}

    @cached()
    def flaky_function():
        call_count["n"] += 1
        return []  # simulates a failed lookup

    flaky_function()
    flaky_function()

    assert call_count["n"] == 2  # NOT cached -- recomputed every time


def test_cached_expires_after_ttl():
    call_count = {"n": 0}

    @cached(ttl_seconds=0.1)
    def quick_expiry_function():
        call_count["n"] += 1
        return "real result"

    quick_expiry_function()
    time.sleep(0.2)
    quick_expiry_function()

    assert call_count["n"] == 2  # recomputed after the short TTL expired


def test_clear_cache_removes_all_entries():
    call_count = {"n": 0}

    @cached()
    def cached_function():
        call_count["n"] += 1
        return "value"

    cached_function()
    clear_cache()
    cached_function()

    assert call_count["n"] == 2  # recomputed after explicit clear
