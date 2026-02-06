"""
MemoryCore Skill
================
Persistent memory and learning system.
Stores posts, ideas, patterns, and preferences.
Provides context for other skills.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging
import json

from .base import BaseSkill
from ..config import config
from ..database import db, Post, Idea, SuccessPattern, CreatorPreference, DailyReport, Trend

logger = logging.getLogger(__name__)


class MemoryCore(BaseSkill):
    """
    Central memory system for the agent.

    Memory Types:
    - posts_database: All scraped posts with metrics
    - ideas_log: Generated ideas with outcomes
    - success_patterns: Learned success patterns
    - creator_preferences: What the creator likes/dislikes
    """

    def __init__(self):
        super().__init__("MemoryCore")

    async def execute(
        self,
        operation: str = "get_context",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute memory operations.

        Args:
            operation: Operation type
                - 'get_context': Get full context for idea generation
                - 'get_stats': Get performance statistics
                - 'get_patterns': Get learned patterns
                - 'update_patterns': Update success patterns
                - 'get_preferences': Get creator preferences
                - 'daily_report': Generate daily summary

        Returns:
            Dict with operation results
        """
        self.log_start()

        results = {"operation": operation}

        try:
            if operation == "get_context":
                results = await self._get_full_context()
            elif operation == "get_stats":
                results = await self._get_performance_stats(**kwargs)
            elif operation == "get_patterns":
                results = await self._get_success_patterns(**kwargs)
            elif operation == "update_patterns":
                results = await self._update_patterns(**kwargs)
            elif operation == "get_preferences":
                results = await self._get_creator_preferences()
            elif operation == "daily_report":
                results = await self._generate_daily_report()
            else:
                results["error"] = f"Unknown operation: {operation}"

            self.log_complete(results)

        except Exception as e:
            self.log_error(e)
            results["error"] = str(e)

        return results

    async def _get_full_context(self) -> Dict[str, Any]:
        """
        Get comprehensive context for idea generation.

        Returns:
            Dict with all relevant context
        """
        session = db.get_session()
        try:
            # Performance baseline
            posts = session.query(Post).filter(
                Post.posted_at >= datetime.utcnow() - timedelta(days=90)
            ).all()

            if posts:
                avg_engagement = sum(p.engagement_rate or 0 for p in posts) / len(posts)
                avg_views = sum(p.views or 0 for p in posts) / len(posts)
            else:
                avg_engagement = 0
                avg_views = 0

            # Top performers
            top_posts = session.query(Post).order_by(
                Post.engagement_rate.desc()
            ).limit(5).all()

            # Success patterns
            patterns = session.query(SuccessPattern).order_by(
                SuccessPattern.engagement_multiplier.desc()
            ).limit(10).all()

            # Recent ideas and their outcomes
            recent_ideas = session.query(Idea).filter(
                Idea.created_at >= datetime.utcnow() - timedelta(days=7)
            ).all()

            ideas_used = sum(1 for i in recent_ideas if i.status == "used")
            ideas_total = len(recent_ideas)

            # Creator preferences
            preferences = session.query(CreatorPreference).all()

            # Active trends
            active_trends = session.query(Trend).filter(
                Trend.expires_at > datetime.utcnow(),
                Trend.status != "expired"
            ).order_by(Trend.relevance_score.desc()).limit(5).all()

            context = {
                "performance_baseline": {
                    "avg_engagement_rate": round(avg_engagement, 2),
                    "avg_views": int(avg_views),
                    "total_posts_90d": len(posts),
                },
                "top_performers": [
                    {
                        "caption_preview": p.caption[:100] if p.caption else "",
                        "engagement_rate": p.engagement_rate,
                        "views": p.views,
                        "category": p.category,
                    }
                    for p in top_posts
                ],
                "success_patterns": [
                    {
                        "type": p.pattern_type,
                        "value": p.pattern_value,
                        "multiplier": p.engagement_multiplier,
                        "confidence": p.confidence,
                    }
                    for p in patterns
                ],
                "idea_acceptance_rate": (ideas_used / ideas_total * 100) if ideas_total > 0 else 0,
                "creator_preferences": {
                    p.preference_type: {
                        "value": p.preference_value,
                        "confidence": p.confidence,
                    }
                    for p in preferences
                },
                "active_trends": [
                    {
                        "title": t.title,
                        "opportunity": t.content_opportunity,
                        "urgency": t.urgency,
                        "score": t.relevance_score,
                    }
                    for t in active_trends
                ],
                "summary": f"Context loaded: {len(posts)} posts, {len(patterns)} patterns, {len(active_trends)} trends"
            }

            return context

        finally:
            session.close()

    async def _get_performance_stats(
        self,
        days: int = 30,
        platform: str = None
    ) -> Dict[str, Any]:
        """
        Get performance statistics.

        Args:
            days: Number of days to analyze
            platform: Filter by platform

        Returns:
            Performance statistics
        """
        session = db.get_session()
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)

            query = session.query(Post).filter(Post.posted_at >= cutoff)
            if platform:
                query = query.filter(Post.platform == platform)

            posts = query.all()

            if not posts:
                return {"error": "No posts found in period"}

            # Calculate stats
            total_views = sum(p.views or 0 for p in posts)
            total_likes = sum(p.likes or 0 for p in posts)
            total_comments = sum(p.comments or 0 for p in posts)
            avg_engagement = sum(p.engagement_rate or 0 for p in posts) / len(posts)

            # By category
            by_category = {}
            for post in posts:
                cat = post.category or "uncategorized"
                if cat not in by_category:
                    by_category[cat] = {"count": 0, "total_engagement": 0, "total_views": 0}
                by_category[cat]["count"] += 1
                by_category[cat]["total_engagement"] += post.engagement_rate or 0
                by_category[cat]["total_views"] += post.views or 0

            for cat in by_category:
                count = by_category[cat]["count"]
                by_category[cat]["avg_engagement"] = by_category[cat]["total_engagement"] / count
                by_category[cat]["avg_views"] = by_category[cat]["total_views"] / count

            # Trend (compare first half vs second half)
            half_point = cutoff + timedelta(days=days/2)
            first_half = [p for p in posts if p.posted_at and p.posted_at < half_point]
            second_half = [p for p in posts if p.posted_at and p.posted_at >= half_point]

            if first_half and second_half:
                first_avg = sum(p.engagement_rate or 0 for p in first_half) / len(first_half)
                second_avg = sum(p.engagement_rate or 0 for p in second_half) / len(second_half)
                trend = "improving" if second_avg > first_avg * 1.05 else (
                    "declining" if second_avg < first_avg * 0.95 else "stable"
                )
                trend_change = ((second_avg - first_avg) / first_avg * 100) if first_avg > 0 else 0
            else:
                trend = "insufficient_data"
                trend_change = 0

            return {
                "period_days": days,
                "total_posts": len(posts),
                "total_views": total_views,
                "total_likes": total_likes,
                "total_comments": total_comments,
                "avg_engagement_rate": round(avg_engagement, 2),
                "by_category": by_category,
                "trend": trend,
                "trend_change_percent": round(trend_change, 1),
                "summary": f"{len(posts)} posts, {trend} trend ({trend_change:+.1f}%)"
            }

        finally:
            session.close()

    async def _get_success_patterns(
        self,
        min_confidence: float = 0.5,
        limit: int = 20
    ) -> Dict[str, Any]:
        """
        Get learned success patterns.

        Args:
            min_confidence: Minimum confidence threshold
            limit: Maximum patterns to return

        Returns:
            Success patterns
        """
        session = db.get_session()
        try:
            patterns = session.query(SuccessPattern).filter(
                SuccessPattern.confidence >= min_confidence
            ).order_by(
                SuccessPattern.engagement_multiplier.desc()
            ).limit(limit).all()

            # Group by type
            by_type = {}
            for p in patterns:
                if p.pattern_type not in by_type:
                    by_type[p.pattern_type] = []
                by_type[p.pattern_type].append({
                    "value": p.pattern_value,
                    "multiplier": p.engagement_multiplier,
                    "confidence": p.confidence,
                    "sample_size": p.sample_size,
                })

            return {
                "patterns": [
                    {
                        "type": p.pattern_type,
                        "value": p.pattern_value,
                        "multiplier": p.engagement_multiplier,
                        "confidence": p.confidence,
                    }
                    for p in patterns
                ],
                "by_type": by_type,
                "total_patterns": len(patterns),
                "summary": f"{len(patterns)} patterns found"
            }

        finally:
            session.close()

    async def _update_patterns(
        self,
        patterns: List[Dict]
    ) -> Dict[str, Any]:
        """
        Update success patterns.

        Args:
            patterns: List of pattern updates

        Returns:
            Update results
        """
        session = db.get_session()
        updated = 0
        created = 0

        try:
            for pattern_data in patterns:
                existing = session.query(SuccessPattern).filter_by(
                    pattern_type=pattern_data.get("type"),
                    pattern_value=pattern_data.get("value")
                ).first()

                if existing:
                    # Update existing
                    if "multiplier" in pattern_data:
                        existing.engagement_multiplier = pattern_data["multiplier"]
                    if "confidence" in pattern_data:
                        existing.confidence = pattern_data["confidence"]
                    existing.last_validated = datetime.utcnow()
                    updated += 1
                else:
                    # Create new
                    new_pattern = SuccessPattern(
                        pattern_type=pattern_data.get("type", "unknown"),
                        pattern_value=pattern_data.get("value", ""),
                        engagement_multiplier=pattern_data.get("multiplier", 1.0),
                        confidence=pattern_data.get("confidence", 0.5),
                    )
                    session.add(new_pattern)
                    created += 1

            session.commit()

            return {
                "updated": updated,
                "created": created,
                "summary": f"Updated {updated}, created {created} patterns"
            }

        finally:
            session.close()

    async def _get_creator_preferences(self) -> Dict[str, Any]:
        """
        Get learned creator preferences.

        Returns:
            Creator preferences
        """
        session = db.get_session()
        try:
            preferences = session.query(CreatorPreference).all()

            # Also calculate from idea history
            ideas = session.query(Idea).filter(
                Idea.status.in_(["used", "skipped"]),
                Idea.created_at >= datetime.utcnow() - timedelta(days=30)
            ).all()

            # Category preferences from used ideas
            category_usage = {}
            for idea in ideas:
                cat = idea.category or "unknown"
                if cat not in category_usage:
                    category_usage[cat] = {"used": 0, "skipped": 0}
                if idea.status == "used":
                    category_usage[cat]["used"] += 1
                else:
                    category_usage[cat]["skipped"] += 1

            return {
                "explicit_preferences": {
                    p.preference_type: {
                        "value": p.preference_value,
                        "confidence": p.confidence,
                    }
                    for p in preferences
                },
                "category_preferences": {
                    cat: {
                        "used": data["used"],
                        "skipped": data["skipped"],
                        "acceptance_rate": data["used"] / (data["used"] + data["skipped"]) * 100
                        if (data["used"] + data["skipped"]) > 0 else 0
                    }
                    for cat, data in category_usage.items()
                },
                "summary": f"{len(preferences)} preferences, {len(ideas)} idea history"
            }

        finally:
            session.close()

    async def _generate_daily_report(self) -> Dict[str, Any]:
        """
        Generate daily summary report.

        Returns:
            Daily report
        """
        session = db.get_session()
        try:
            today = datetime.utcnow().date()
            today_start = datetime.combine(today, datetime.min.time())

            # Today's activity
            posts_today = session.query(Post).filter(
                Post.posted_at >= today_start
            ).count()

            ideas_sent = session.query(Idea).filter(
                Idea.sent_at >= today_start
            ).count()

            ideas_used = session.query(Idea).filter(
                Idea.used_at >= today_start
            ).count()

            trends_discovered = session.query(Trend).filter(
                Trend.discovered_at >= today_start
            ).count()

            # Performance today
            today_posts = session.query(Post).filter(
                Post.posted_at >= today_start
            ).all()

            total_views = sum(p.views or 0 for p in today_posts)
            total_engagement = sum(
                (p.likes or 0) + (p.comments or 0) + (p.shares or 0)
                for p in today_posts
            )

            # Best performer
            best_post = max(today_posts, key=lambda p: p.engagement_rate or 0) if today_posts else None

            report = DailyReport(
                date=today_start,
                posts_created=posts_today,
                ideas_sent=ideas_sent,
                ideas_used=ideas_used,
                total_views=total_views,
                total_engagement=total_engagement,
                trends_discovered=trends_discovered,
                best_performing_post_id=best_post.id if best_post else None,
            )
            session.add(report)
            session.commit()

            return {
                "date": today.isoformat(),
                "posts_created": posts_today,
                "ideas_sent": ideas_sent,
                "ideas_used": ideas_used,
                "idea_acceptance_rate": (ideas_used / ideas_sent * 100) if ideas_sent > 0 else 0,
                "total_views": total_views,
                "total_engagement": total_engagement,
                "trends_discovered": trends_discovered,
                "best_post": {
                    "caption": best_post.caption[:100] if best_post else None,
                    "engagement_rate": best_post.engagement_rate if best_post else None,
                } if best_post else None,
                "summary": f"Day summary: {posts_today} posts, {ideas_used}/{ideas_sent} ideas used"
            }

        finally:
            session.close()

    async def remember_idea_outcome(
        self,
        idea_id: int,
        was_used: bool,
        post_id: int = None,
        feedback: str = None
    ):
        """
        Record the outcome of an idea for learning.

        Args:
            idea_id: ID of the idea
            was_used: Whether the idea was used
            post_id: ID of resulting post if used
            feedback: Creator feedback
        """
        session = db.get_session()
        try:
            idea = session.query(Idea).filter_by(id=idea_id).first()
            if idea:
                idea.status = "used" if was_used else "skipped"
                if was_used:
                    idea.used_at = datetime.utcnow()
                    idea.resulting_post_id = post_id
                if feedback:
                    idea.creator_feedback = feedback
                session.commit()
        finally:
            session.close()

    async def get_recent_activity(self, hours: int = 24) -> Dict[str, Any]:
        """
        Get recent activity summary.

        Args:
            hours: Hours to look back

        Returns:
            Recent activity summary
        """
        session = db.get_session()
        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)

            posts = session.query(Post).filter(Post.posted_at >= cutoff).count()
            ideas = session.query(Idea).filter(Idea.created_at >= cutoff).count()
            trends = session.query(Trend).filter(Trend.discovered_at >= cutoff).count()

            return {
                "hours": hours,
                "posts": posts,
                "ideas_generated": ideas,
                "trends_discovered": trends,
            }
        finally:
            session.close()
