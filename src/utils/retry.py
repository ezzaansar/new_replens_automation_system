"""
Retry utility with exponential backoff for API calls.

Usage:
    @retry_with_backoff(max_retries=3, base_delay=1.0, backoff_factor=2.0)
    def my_api_call():
        ...
"""

import functools
import logging
import time
from typing import Tuple, Type

import requests

logger = logging.getLogger(__name__)

# Transient HTTP errors that are safe to retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Exception types that indicate transient failures
RETRYABLE_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
    ConnectionResetError,
    TimeoutError,
)


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = RETRYABLE_EXCEPTIONS,
):
    """
    Decorator that retries a function with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds before first retry
        backoff_factor: Multiplier for delay after each retry
        retryable_exceptions: Tuple of exception types to retry on
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    result = func(*args, **kwargs)

                    # Check for retryable HTTP responses
                    if isinstance(result, requests.Response) and result.status_code in RETRYABLE_STATUS_CODES:
                        if attempt < max_retries:
                            delay = base_delay * (backoff_factor ** attempt)
                            if result.status_code == 429:
                                delay = int(result.headers.get("Retry-After", delay))
                            logger.warning(
                                f"{func.__name__}: HTTP {result.status_code}, "
                                f"retry {attempt + 1}/{max_retries} in {delay:.1f}s"
                            )
                            time.sleep(delay)
                            continue
                    return result

                except retryable_exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = base_delay * (backoff_factor ** attempt)
                        logger.warning(
                            f"{func.__name__}: {type(e).__name__}, "
                            f"retry {attempt + 1}/{max_retries} in {delay:.1f}s"
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"{func.__name__}: failed after {max_retries} retries: {e}"
                        )
                        raise

            if last_exception:
                raise last_exception

        return wrapper
    return decorator
