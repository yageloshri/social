"""
GoalTracker
===========
Track and pursue content goals automatically.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .database import db, Post, Idea
from .config import config

logger = logging.getLogger(__name__)


class GoalTracker:
    """
    Track and pursue content goals.

    Goals:
    - Weekly post counts for each platform
    - Engagement rate targets
    - Consistency metrics
    """

    def __init__(self):
        # Default weekly goals
        self.goals = {
            "weekly_posts_tiktok": {
                "name": "פוסטים בטיקטוק",
                "target": 5,
                "current": 0,
                "unit": "פוסטים",
            },
            "weekly_posts_instagram": {
                "name": "פוסטים באינסטגרם",
                "target": 3,
                "current": 0,
                "unit": "פוסטים",
            },
            "weekly_engagement_rate": {
                "name": "שיעור אנגייג'מנט",
                "target": 4.0,
                "current": 0,
                "unit": "%",
            },
            "posting_consistency": {
                "name": "עקביות (ימים עם פוסט)",
                "target": 5,
                "current": 0,
                "unit": "ימים",
            },
        }

        # Load current progress
        self._refresh_progress()

    def _refresh_progress(self):
        """Refresh goal progress from database."""
        session = db.get_session()
        try:
            # Get start of current week (Sunday)
            today = datetime.utcnow()
            start_of_week = today - timedelta(days=(today.weekday() + 1) % 7)
            start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)

            # Count posts this week
            tiktok_posts = session.query(Post).filter(
                Post.platform == "tiktok",
                Post.posted_at >= start_of_week
            ).count()

            instagram_posts = session.query(Post).filter(
                Post.platform == "instagram",
                Post.posted_at >= start_of_week
            ).count()

            # Calculate engagement rate
            week_posts = session.query(Post).filter(
                Post.posted_at >= start_of_week
            ).all()

            if week_posts:
                total_engagement = sum(
                    (p.likes or 0) + (p.comments or 0) + (p.shares or 0)
                    for p in week_posts
                )
                total_views = sum(p.views or 0 for p in week_posts)
                engagement_rate = (total_engagement / total_views * 100) if total_views > 0 else 0
            else:
                engagement_rate = 0

            # Count unique posting days
            posting_days = set()
            for post in week_posts:
                if post.posted_at:
                    posting_days.add(post.posted_at.date())

            # Update goals
            self.goals["weekly_posts_tiktok"]["current"] = tiktok_posts
            self.goals["weekly_posts_instagram"]["current"] = instagram_posts
            self.goals["weekly_engagement_rate"]["current"] = engagement_rate
            self.goals["posting_consistency"]["current"] = len(posting_days)

        except Exception as e:
            logger.error(f"Error refreshing goal progress: {e}")
        finally:
            session.close()

    def evaluate_progress(self) -> Dict[str, Dict]:
        """Check how we're doing on goals."""
        self._refresh_progress()

        status = {}
        today = datetime.utcnow()
        day_of_week = (today.weekday() + 1) % 7  # 0=Sunday, 6=Saturday

        for goal_name, goal in self.goals.items():
            target = goal["target"]
            current = goal["current"]

            # Calculate progress percentage
            progress = (current / target * 100) if target > 0 else 0

            # Calculate expected progress based on day of week
            # On Sunday (0), expect 0%. On Saturday (6), expect 85%+
            expected_progress = (day_of_week / 6 * 100) if day_of_week > 0 else 0

            status[goal_name] = {
                "name": goal["name"],
                "target": target,
                "current": current,
                "unit": goal["unit"],
                "progress": progress,
                "expected": expected_progress,
                "on_track": progress >= expected_progress - 15,
                "behind": progress < expected_progress - 25,
                "ahead": progress > expected_progress + 15,
            }

        return status

    def get_priority_goal(self) -> Optional[Dict]:
        """Which goal needs most attention?"""
        status = self.evaluate_progress()

        # Find most behind goal
        most_behind = None
        biggest_gap = 0

        for goal_name, data in status.items():
            gap = data["expected"] - data["progress"]
            if gap > biggest_gap:
                biggest_gap = gap
                most_behind = {
                    "name": goal_name,
                    "display_name": data["name"],
                    "gap": gap,
                    "behind": data["behind"],
                    "current": data["current"],
                    "target": data["target"],
                }

        return most_behind

    def get_weekly_goal(self) -> str:
        """Get the main weekly goal description."""
        return f"להעלות {self.goals['weekly_posts_tiktok']['target']} טיקטוקים ו-{self.goals['weekly_posts_instagram']['target']} פוסטים באינסטגרם"

    def get_progress_summary(self) -> Dict:
        """Get a summary of overall progress."""
        status = self.evaluate_progress()

        total_progress = sum(s["progress"] for s in status.values()) / len(status)
        goals_on_track = sum(1 for s in status.values() if s["on_track"])
        goals_behind = sum(1 for s in status.values() if s["behind"])

        return {
            "percentage": total_progress,
            "on_track": goals_on_track,
            "behind": goals_behind,
            "total_goals": len(status),
            "close_to_goal": total_progress >= 80,
        }

    def format_progress_message(self) -> str:
        """Format progress as a message."""
        status = self.evaluate_progress()
        lines = []

        for goal_name, data in status.items():
            emoji = "✅" if data["on_track"] else ("⚠️" if data["behind"] else "📊")
            lines.append(
                f"{emoji} {data['name']}: {data['current']}/{data['target']} {data['unit']} "
                f"({data['progress']:.0f}%)"
            )

        return "\n".join(lines)

    def suggest_action_for_goal(self, goal_name: str) -> str:
        """What should we do to achieve this goal?"""
        suggestions = {
            "weekly_posts_tiktok": "צריך להעלות לטיקטוק! יש רעיון מוכן?",
            "weekly_posts_instagram": "האינסטגרם שקט... בוא נעלה משהו!",
            "weekly_engagement_rate": "בוא ננסה תוכן שמעורר יותר תגובות",
            "posting_consistency": "חשוב להעלות כל יום, גם משהו קטן",
        }

        return suggestions.get(goal_name, "בוא נעבוד על היעד הזה!")

    def set_custom_goal(self, goal_name: str, target: Any):
        """Set a custom goal target."""
        if goal_name in self.goals:
            self.goals[goal_name]["target"] = target
            logger.info(f"Goal {goal_name} target set to {target}")

    def get_days_until_week_end(self) -> int:
        """Get days until end of week (Saturday)."""
        today = datetime.utcnow()
        day_of_week = (today.weekday() + 1) % 7  # 0=Sunday
        return 6 - day_of_week

    def get_needed_posts_per_day(self) -> Dict[str, float]:
        """Calculate needed posts per day to hit goals."""
        days_left = self.get_days_until_week_end()
        if days_left == 0:
            days_left = 1

        tiktok_needed = self.goals["weekly_posts_tiktok"]["target"] - self.goals["weekly_posts_tiktok"]["current"]
        instagram_needed = self.goals["weekly_posts_instagram"]["target"] - self.goals["weekly_posts_instagram"]["current"]

        return {
            "tiktok_per_day": max(0, tiktok_needed / days_left),
            "instagram_per_day": max(0, instagram_needed / days_left),
            "days_left": days_left,
        }

    def record_post(self, platform: str):
        """Record a new post (for manual tracking if needed)."""
        if platform == "tiktok":
            self.goals["weekly_posts_tiktok"]["current"] += 1
        elif platform == "instagram":
            self.goals["weekly_posts_instagram"]["current"] += 1

    def reset_weekly(self):
        """Reset goals for new week (call on Sunday midnight)."""
        for goal in self.goals.values():
            goal["current"] = 0
        logger.info("Weekly goals reset")
