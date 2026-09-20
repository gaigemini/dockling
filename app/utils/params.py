"""Shared helpers for parsing conversion request parameters."""

import sys
from typing import Optional, Tuple


def parse_bool(value: str) -> bool:
    """Parse a string form value into a boolean."""
    return value.lower() in ["true", "1", "yes", "on", "y"]


def build_page_range(
    from_page: Optional[int],
    to_page: Optional[int],
) -> Optional[Tuple[int, int]]:
    """Build a (start, end) 1-based inclusive page range from optional bounds.

    Returns None if neither parameter is provided (convert all pages).
    If only one bound is given, the other defaults to 1 (from) or
    sys.maxsize (to).
    """
    if from_page is None and to_page is None:
        return None
    start = from_page if from_page is not None else 1
    end = to_page if to_page is not None else sys.maxsize
    return (start, end)
