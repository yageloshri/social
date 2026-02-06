"""
Configuration management for the Content Master Agent.
Loads settings from environment variables with sensible defaults.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


@dataclass
class AIConfig:
    """Claude AI configuration."""
    api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096
    temperature: float = 0.7


@dataclass
class TwilioConfig:
    """Twilio WhatsApp configuration."""
    account_sid: str = field(default_factory=lambda: os.getenv("TWILIO_ACCOUNT_SID", ""))
    auth_token: str = field(default_factory=lambda: os.getenv("TWILIO_AUTH_TOKEN", ""))
    whatsapp_number: str = field(default_factory=lambda: os.getenv("TWILIO_WHATSAPP_NUMBER", ""))
    my_number: str = field(default_factory=lambda: os.getenv("MY_WHATSAPP_NUMBER", ""))


@dataclass
class ScrapingConfig:
    """Social media scraping configuration."""
    apify_token: str = field(default_factory=lambda: os.getenv("APIFY_TOKEN", ""))
    instagram_handle: str = field(default_factory=lambda: os.getenv("INSTAGRAM_HANDLE", ""))
    tiktok_handle: str = field(default_factory=lambda: os.getenv("TIKTOK_HANDLE", ""))


@dataclass
class CreatorProfile:
    """Creator personalization settings."""
    name: str = field(default_factory=lambda: os.getenv("CREATOR_NAME", ""))
    girlfriend_name: str = field(default_factory=lambda: os.getenv("GIRLFRIEND_NAME", ""))
    language: str = "he"  # Hebrew
    timezone: str = "Asia/Jerusalem"

    # Content categories ranked by historical performance
    top_categories: List[str] = field(default_factory=lambda: [
        "couple_content",      # 3x engagement
        "story_times",         # 2x engagement
        "trending_reactions",  # 1.5x engagement
        "music_content",       # 1.2x engagement
    ])

    # Brand voice characteristics
    brand_voice: List[str] = field(default_factory=lambda: [
        "authentic",
        "natural",
        "relatable",
        "friendly",
        "genuine"
    ])

    # Content style rules
    never_do: List[str] = field(default_factory=lambda: [
        "pretentious",
        "salesy",
        "fake enthusiasm",
        "clickbait that doesn't deliver"
    ])


@dataclass
class ScheduleConfig:
    """Message scheduling configuration."""
    morning_time: str = "09:00"
    midday_time: str = "13:00"
    afternoon_time: str = "17:00"
    evening_time: str = "21:00"

    # Best posting times based on data
    optimal_posting_start: str = "18:00"
    optimal_posting_end: str = "20:00"

    # Scraping schedule
    full_scan_time: str = "06:00"
    quick_update_interval_hours: int = 6


@dataclass
class RSSConfig:
    """RSS feed configuration for trend monitoring."""

    # Israeli news sources
    news_feeds: List[str] = field(default_factory=lambda: [
        "https://www.ynet.co.il/Integration/StoryRss2.xml",
        "https://rss.walla.co.il/feed/1",
        "https://www.mako.co.il/rss/31750a2610f26110VgnVCM1000004801000aRCRD.xml",
    ])

    # Entertainment feeds
    entertainment_feeds: List[str] = field(default_factory=lambda: [
        "https://www.mako.co.il/rss/5b0bce5191f7f110VgnVCM2000002a0c10acRCRD.xml",  # Celebs
        "https://rss.walla.co.il/feed/22",  # Culture
    ])

    # High priority keywords (Hebrew)
    high_priority_keywords: List[str] = field(default_factory=lambda: [
        "זוגיות", "מערכת יחסים", "גרים ביחד", "ויראלי",
        "טיקטוק", "אינסטגרם", "מוזיקאי", "שיר", "להיט"
    ])

    # Medium priority keywords
    medium_priority_keywords: List[str] = field(default_factory=lambda: [
        "צעירים", "טרנד", "ריאליטי", "הישרדות", "האח הגדול",
        "כוכב נולד", "פופולרי"
    ])

    # Keywords to exclude
    exclude_keywords: List[str] = field(default_factory=lambda: [
        "פוליטיקה", "מלחמה", "טרור", "אסון", "תאונה", "מוות",
        "פיגוע", "צבא", "ממשלה", "כנסת"
    ])


@dataclass
class DatabaseConfig:
    """Database configuration."""
    path: str = field(default_factory=lambda: os.getenv("DATABASE_PATH", "data/agent.db"))


@dataclass
class Config:
    """Main configuration container."""
    ai: AIConfig = field(default_factory=AIConfig)
    twilio: TwilioConfig = field(default_factory=TwilioConfig)
    scraping: ScrapingConfig = field(default_factory=ScrapingConfig)
    creator: CreatorProfile = field(default_factory=CreatorProfile)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    rss: RSSConfig = field(default_factory=RSSConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)

    # General settings
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    debug: bool = field(default_factory=lambda: os.getenv("DEBUG", "false").lower() == "true")

    def validate(self) -> List[str]:
        """Validate configuration and return list of errors."""
        errors = []

        if not self.ai.api_key:
            errors.append("ANTHROPIC_API_KEY is required")
        if not self.twilio.account_sid:
            errors.append("TWILIO_ACCOUNT_SID is required")
        if not self.twilio.auth_token:
            errors.append("TWILIO_AUTH_TOKEN is required")
        if not self.twilio.whatsapp_number:
            errors.append("TWILIO_WHATSAPP_NUMBER is required")
        if not self.twilio.my_number:
            errors.append("MY_WHATSAPP_NUMBER is required")
        if not self.scraping.apify_token:
            errors.append("APIFY_TOKEN is required")
        if not self.scraping.instagram_handle:
            errors.append("INSTAGRAM_HANDLE is required")
        if not self.scraping.tiktok_handle:
            errors.append("TIKTOK_HANDLE is required")

        return errors


# Global config instance
config = Config()
