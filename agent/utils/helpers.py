"""
Helper utilities for the Content Master Agent.
"""

import re
from typing import Optional


def format_number(num: int) -> str:
    """
    Format large numbers with K/M suffix.

    Args:
        num: Number to format

    Returns:
        Formatted string (e.g., "1.5K", "2.3M")
    """
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    elif num >= 1_000:
        return f"{num / 1_000:.1f}K"
    return str(num)


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    Truncate text to max length.

    Args:
        text: Text to truncate
        max_length: Maximum length
        suffix: Suffix to add when truncated

    Returns:
        Truncated text
    """
    if not text or len(text) <= max_length:
        return text or ""

    return text[:max_length - len(suffix)] + suffix


def clean_text(text: str) -> str:
    """
    Clean text by removing extra whitespace and newlines.

    Args:
        text: Text to clean

    Returns:
        Cleaned text
    """
    if not text:
        return ""

    # Replace multiple whitespace with single space
    text = re.sub(r'\s+', ' ', text)

    # Strip leading/trailing whitespace
    return text.strip()


def extract_hashtags(text: str) -> list:
    """
    Extract hashtags from text.

    Args:
        text: Text containing hashtags

    Returns:
        List of hashtags (without #)
    """
    if not text:
        return []

    return re.findall(r'#(\w+)', text)


def extract_mentions(text: str) -> list:
    """
    Extract @mentions from text.

    Args:
        text: Text containing mentions

    Returns:
        List of mentions (without @)
    """
    if not text:
        return []

    return re.findall(r'@(\w+)', text)


def is_hebrew(text: str) -> bool:
    """
    Check if text contains Hebrew characters.

    Args:
        text: Text to check

    Returns:
        True if contains Hebrew
    """
    if not text:
        return False

    # Hebrew Unicode range
    hebrew_pattern = re.compile(r'[\u0590-\u05FF]')
    return bool(hebrew_pattern.search(text))


def calculate_engagement_rate(
    views: int,
    likes: int,
    comments: int,
    shares: int = 0,
    saves: int = 0
) -> float:
    """
    Calculate engagement rate.

    Args:
        views: View count
        likes: Like count
        comments: Comment count
        shares: Share count
        saves: Save count

    Returns:
        Engagement rate as percentage
    """
    if not views or views <= 0:
        return 0.0

    total_engagement = likes + comments + shares + saves
    return (total_engagement / views) * 100
