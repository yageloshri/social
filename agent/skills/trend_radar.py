"""
TrendRadar Skill
================
Monitors Israeli news and entertainment RSS feeds for relevant trends.
Filters and ranks trends by relevance to the creator.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging
import re

import feedparser
from anthropic import Anthropic

from .base import BaseSkill
from ..config import config
from ..database import db, Trend

logger = logging.getLogger(__name__)


class TrendRadar(BaseSkill):
    """
    Monitors RSS feeds for relevant trends and news.

    Capabilities:
    - Parse Israeli news and entertainment RSS feeds
    - Filter by relevance keywords
    - Score trends by content opportunity potential
    - Generate quick content suggestions for timely topics
    """

    def __init__(self):
        super().__init__("TrendRadar")
        self.client = Anthropic(api_key=config.ai.api_key) if config.ai.api_key else None

    async def execute(
        self,
        check_all_feeds: bool = True,
        max_trends: int = 20,
        priority_only: bool = False
    ) -> Dict[str, Any]:
        """
        Execute trend monitoring.

        Args:
            check_all_feeds: If True, check all configured feeds
            max_trends: Maximum number of trends to return
            priority_only: If True, only check breaking and entertainment feeds

        Returns:
            Dict with discovered trends
        """
        self.log_start()

        results = {
            "trends_found": 0,
            "relevant_trends": [],
            "content_opportunities": [],
            "errors": [],
            "feeds_checked": [],
        }

        try:
            all_entries = []

            # Build feed list based on priority
            if priority_only:
                # Quick scan - only breaking news and entertainment
                feeds_to_check = [
                    ("breaking", config.rss.breaking_feeds),
                    ("entertainment", config.rss.entertainment_feeds),
                ]
            else:
                # Full scan - all feeds by priority
                feeds_to_check = [
                    ("breaking", config.rss.breaking_feeds),
                    ("entertainment", config.rss.entertainment_feeds),
                    ("lifestyle", config.rss.lifestyle_feeds),
                    ("music", config.rss.music_feeds),
                ]

            for feed_category, feed_urls in feeds_to_check:
                results["feeds_checked"].append(feed_category)
                for feed_url in feed_urls:
                    try:
                        entries = await self._fetch_feed(feed_url, feed_category)
                        all_entries.extend(entries)
                    except Exception as e:
                        logger.warning(f"Error fetching feed {feed_url}: {e}")
                        results["errors"].append(f"Feed error: {feed_url}")

            # Filter and score entries
            relevant_entries = self._filter_entries(all_entries)
            results["trends_found"] = len(all_entries)

            # Score and rank relevant entries
            scored_entries = await self._score_entries(relevant_entries)

            # Sort by relevance score
            scored_entries.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

            # Take top trends
            top_trends = scored_entries[:max_trends]

            # Generate content opportunities for top trends
            for trend in top_trends[:5]:  # AI analysis for top 5 only
                opportunity = await self._generate_opportunity(trend)
                if opportunity:
                    trend["content_opportunity"] = opportunity
                    results["content_opportunities"].append({
                        "trend": trend["title"],
                        "opportunity": opportunity,
                        "urgency": trend.get("urgency", "today")
                    })

            # Store in database
            await self._store_trends(top_trends)

            results["relevant_trends"] = top_trends
            results["summary"] = f"Found {len(top_trends)} relevant trends, {len(results['content_opportunities'])} opportunities"
            self.log_complete(results)

        except Exception as e:
            self.log_error(e)
            results["errors"].append(str(e))

        return results

    async def _fetch_feed(self, feed_url: str, category: str = "general") -> List[Dict]:
        """
        Fetch and parse an RSS feed.

        Args:
            feed_url: URL of the RSS feed
            category: Feed category (breaking, entertainment, lifestyle, music)

        Returns:
            List of feed entries
        """
        loop = asyncio.get_event_loop()
        feed = await loop.run_in_executor(None, feedparser.parse, feed_url)

        entries = []
        for entry in feed.entries[:30]:  # Limit to recent entries
            # Parse publication date
            published = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                published = datetime(*entry.published_parsed[:6])

            # Skip old entries (more than 3 days)
            if published and (datetime.utcnow() - published) > timedelta(days=3):
                continue

            entries.append({
                "title": entry.get("title", ""),
                "summary": entry.get("summary", entry.get("description", "")),
                "link": entry.get("link", ""),
                "source": feed.feed.get("title", feed_url),
                "source_url": feed_url,
                "published": published,
                "feed_category": category,
            })

        return entries

    def _filter_entries(self, entries: List[Dict]) -> List[Dict]:
        """
        Filter entries by relevance keywords.

        Args:
            entries: List of feed entries

        Returns:
            Filtered list of relevant entries
        """
        relevant = []

        for entry in entries:
            text = f"{entry['title']} {entry['summary']}".lower()

            # Check for excluded keywords first
            has_excluded = any(kw in text for kw in config.rss.exclude_keywords)
            if has_excluded:
                continue

            # Check for high priority keywords
            high_matches = [kw for kw in config.rss.high_priority_keywords if kw in text]

            # Check for medium priority keywords
            medium_matches = [kw for kw in config.rss.medium_priority_keywords if kw in text]

            if high_matches or medium_matches:
                entry["matched_keywords"] = {
                    "high": high_matches,
                    "medium": medium_matches,
                }
                entry["priority"] = "high" if high_matches else "medium"
                relevant.append(entry)

        return relevant

    async def _score_entries(self, entries: List[Dict]) -> List[Dict]:
        """
        Score entries by relevance and opportunity.

        Args:
            entries: Filtered entries

        Returns:
            Entries with relevance scores
        """
        for entry in entries:
            score = 0

            # Base score from keyword matches
            high_matches = len(entry.get("matched_keywords", {}).get("high", []))
            medium_matches = len(entry.get("matched_keywords", {}).get("medium", []))
            score += high_matches * 20
            score += medium_matches * 10

            # Feed category bonus (entertainment & lifestyle more relevant)
            category_bonuses = {
                "entertainment": 25,  # Most relevant for content creator
                "lifestyle": 20,      # Relationship/lifestyle content
                "music": 15,          # Relevant for musician
                "breaking": 10,       # Timely but less directly relevant
            }
            category = entry.get("feed_category", "general")
            score += category_bonuses.get(category, 5)

            # Recency bonus
            published = entry.get("published")
            if published:
                hours_ago = (datetime.utcnow() - published).total_seconds() / 3600
                if hours_ago < 6:
                    score += 30
                    entry["urgency"] = "immediate"
                elif hours_ago < 24:
                    score += 20
                    entry["urgency"] = "today"
                else:
                    score += 5
                    entry["urgency"] = "this_week"
            else:
                entry["urgency"] = "today"

            # Entertainment/celebrity bonus (more relevant for content)
            entertainment_keywords = ["סלבס", "כוכב", "סדרה", "תוכנית", "ריאליטי", "שיר", "זמר", "קליפ"]
            if any(kw in entry["title"].lower() for kw in entertainment_keywords):
                score += 15

            # Relationship/couple content bonus (creator's strongest format)
            couple_keywords = ["זוגיות", "זוג", "מערכת יחסים", "התחתנו", "נפרדו", "גרים ביחד"]
            if any(kw in entry["title"].lower() for kw in couple_keywords):
                score += 25

            entry["relevance_score"] = min(score, 100)  # Cap at 100

        return entries

    async def _generate_opportunity(self, trend: Dict) -> Optional[str]:
        """
        Generate content opportunity suggestion for a trend.

        Args:
            trend: Trend data

        Returns:
            Content opportunity suggestion
        """
        if not self.client:
            return None

        prompt = f"""You're advising an Israeli content creator (musician, creates couple content and storytimes).

TREND:
Title: {trend['title']}
Summary: {trend['summary'][:500]}
Urgency: {trend.get('urgency', 'today')}

Generate a brief, specific content opportunity. How can the creator make relevant content about this?
Consider:
- Can it be combined with couple content? (their strongest format, 3x engagement)
- Is it good for a reaction/opinion video?
- Can it be turned into a storytime?

Response format (in Hebrew, be specific):
"[Brief specific content idea - max 2 sentences]"

If this trend is NOT suitable for their audience/style, respond with: "לא רלוונטי"
"""

        try:
            response = self.client.messages.create(
                model=config.ai.model,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}]
            )

            opportunity = response.content[0].text.strip()

            if "לא רלוונטי" in opportunity:
                return None

            return opportunity

        except Exception as e:
            logger.error(f"Error generating opportunity: {e}")
            return None

    async def _store_trends(self, trends: List[Dict]):
        """Store trends in database."""
        session = db.get_session()
        try:
            for trend in trends:
                # Check if already exists (by title and source)
                existing = session.query(Trend).filter_by(
                    title=trend["title"],
                    source=trend["source"]
                ).first()

                if existing:
                    # Update relevance score
                    existing.relevance_score = trend.get("relevance_score", 0)
                    existing.content_opportunity = trend.get("content_opportunity")
                    continue

                new_trend = Trend(
                    source=trend["source"],
                    source_url=trend.get("link"),
                    title=trend["title"],
                    summary=trend.get("summary"),
                    relevance_score=trend.get("relevance_score", 0),
                    matched_keywords=trend.get("matched_keywords"),
                    urgency=trend.get("urgency", "today"),
                    content_opportunity=trend.get("content_opportunity"),
                    published_at=trend.get("published"),
                    expires_at=datetime.utcnow() + timedelta(days=3),
                )
                session.add(new_trend)

            session.commit()
        finally:
            session.close()

    async def get_active_trends(
        self,
        min_score: float = 30,
        limit: int = 10
    ) -> List[Trend]:
        """
        Get currently active and relevant trends.

        Args:
            min_score: Minimum relevance score
            limit: Maximum trends to return

        Returns:
            List of active trends
        """
        session = db.get_session()
        try:
            trends = session.query(Trend).filter(
                Trend.relevance_score >= min_score,
                Trend.expires_at > datetime.utcnow(),
                Trend.status.in_(["new", "notified"])
            ).order_by(Trend.relevance_score.desc()).limit(limit).all()

            return trends
        finally:
            session.close()

    async def mark_trend_used(self, trend_id: int, idea_id: int):
        """Mark a trend as used in an idea."""
        session = db.get_session()
        try:
            trend = session.query(Trend).filter_by(id=trend_id).first()
            if trend:
                trend.status = "used"
                trend.used_in_idea_id = idea_id
                session.commit()
        finally:
            session.close()

    async def check_breaking_trends(self) -> List[Dict]:
        """
        Quick check for breaking/immediate trends.
        Called more frequently than full scan.

        Returns:
            List of immediate opportunity trends
        """
        results = await self.execute(max_trends=5, priority_only=True)

        immediate = [
            t for t in results.get("relevant_trends", [])
            if t.get("urgency") == "immediate"
        ]

        return immediate

    async def get_rss_headlines(self, category: str = "all", limit: int = 10) -> Dict[str, Any]:
        """
        Get latest RSS headlines for display - without AI analysis.
        Fast method for conversation handler.

        Args:
            category: "all", "entertainment", "breaking", "lifestyle", or "music"
            limit: Maximum headlines to return

        Returns:
            Dict with headlines by category
        """
        results = {
            "headlines": [],
            "by_category": {},
            "total": 0,
            "errors": [],
        }

        # Determine which feeds to check
        feeds_map = {
            "breaking": config.rss.breaking_feeds,
            "entertainment": config.rss.entertainment_feeds,
            "lifestyle": config.rss.lifestyle_feeds,
            "music": config.rss.music_feeds,
        }

        if category == "all":
            feeds_to_check = [
                ("entertainment", feeds_map["entertainment"]),  # Most relevant first
                ("breaking", feeds_map["breaking"]),
                ("lifestyle", feeds_map["lifestyle"]),
                ("music", feeds_map["music"]),
            ]
        elif category in feeds_map:
            feeds_to_check = [(category, feeds_map[category])]
        else:
            results["errors"].append(f"Unknown category: {category}")
            return results

        all_entries = []

        for cat_name, feed_urls in feeds_to_check:
            category_entries = []
            for feed_url in feed_urls:
                try:
                    entries = await self._fetch_feed(feed_url, cat_name)
                    category_entries.extend(entries)
                except Exception as e:
                    logger.warning(f"Error fetching feed {feed_url}: {e}")
                    results["errors"].append(f"Feed error: {feed_url}")

            # Filter out excluded keywords
            filtered = []
            for entry in category_entries:
                text = f"{entry['title']} {entry['summary']}".lower()
                has_excluded = any(kw in text for kw in config.rss.exclude_keywords)
                if not has_excluded:
                    filtered.append(entry)

            results["by_category"][cat_name] = filtered[:5]  # Top 5 per category
            all_entries.extend(filtered)

        # Sort all by recency
        all_entries.sort(
            key=lambda x: x.get("published") or datetime.min,
            reverse=True
        )

        results["headlines"] = all_entries[:limit]
        results["total"] = len(all_entries)

        return results
