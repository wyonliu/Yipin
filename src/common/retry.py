from __future__ import annotations

"""Retry utilities with exponential backoff for API resilience."""

import asyncio
import functools
import logging
from typing import TypeVar, Callable, Any

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def retry_async(
    func: Callable,
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple = (Exception,),
    **kwargs: Any,
) -> Any:
    """Execute an async function with exponential backoff retry.

    Args:
        func: Async function to call
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds (doubles each retry)
        max_delay: Maximum delay between retries
        exceptions: Tuple of exception types to retry on
    """
    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except exceptions as e:
            last_exception = e
            if attempt == max_retries:
                logger.error(f"{func.__name__} failed after {max_retries + 1} attempts: {e}")
                raise
            delay = min(base_delay * (2 ** attempt), max_delay)
            logger.warning(
                f"{func.__name__} attempt {attempt + 1} failed: {e}. "
                f"Retrying in {delay:.1f}s..."
            )
            await asyncio.sleep(delay)
    raise last_exception  # Should never reach here


def with_retry(max_retries: int = 3, base_delay: float = 1.0, exceptions: tuple = (Exception,)):
    """Decorator version of retry for async functions."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await retry_async(
                func, *args,
                max_retries=max_retries,
                base_delay=base_delay,
                exceptions=exceptions,
                **kwargs,
            )
        return wrapper
    return decorator


def safe_json_parse(text: str, expect_type: str = "object") -> dict | list | None:
    """Safely extract and parse JSON from LLM response text.

    Args:
        text: Raw text that may contain JSON
        expect_type: "object" for {} or "array" for []

    Returns:
        Parsed JSON or None on failure
    """
    import json

    open_char = "{" if expect_type == "object" else "["
    close_char = "}" if expect_type == "object" else "]"

    try:
        start = text.index(open_char)
        # Find matching close by counting nesting
        depth = 0
        for i in range(start, len(text)):
            if text[i] == open_char:
                depth += 1
            elif text[i] == close_char:
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(f"JSON parse failed: {e}. Text preview: {text[:200]}")
        return None
