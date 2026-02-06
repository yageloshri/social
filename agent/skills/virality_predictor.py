"""
ViralityPredictor Skill
=======================
Monitors new posts and alerts when performing above average.
Checks at 1h, 3h, and 6h after posting.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from anthropic import Anthropic

from .base import BaseSkill
from ..config import config
from ..database import db, Post, PostMetricHistory
from ..integrations.whatsapp import whatsapp

logger = logging.getLogger(__name__)


class ViralityPredictor(BaseSkill):
    """
    Early virality detection system.

    Monitors new posts at key intervals (1h, 3h, 6h) and compares
    to historical averages to predict viral potential.

    Typical decay curves:
    - Hour 1 = ~10% of final views
    - Hour 3 = ~30% of final views
    - Hour 6 = ~50% of final views
    - Hour 24 = ~80% of final views
    """

    def __init__(self):
        super().__init__("ViralityPredictor")
        self.client = Anthropic(api_key=config.ai.api_key) if config.ai.api_key else None

        # Prediction multipliers based on typical decay curves
        self.prediction_multipliers = {
            1: 10,    # Hour 1 -> multiply by 10 for final prediction
            3: 3.3,   # Hour 3 -> multiply by 3.3
            6: 2,     # Hour 6 -> multiply by 2
            24: 1.25  # Hour 24 -> multiply by 1.25
        }

        # Virality thresholds
        self.viral_multiplier = 2.0      # 2x average = viral
        self.super_viral_multiplier = 5.0  # 5x average = super viral

    async def execute(self) -> Dict[str, Any]:
        """
        Check all recent posts for virality signals.
        Run every hour by scheduler.
        """
        self.log_start()

        results = {
            "posts_checked": 0,
            "alerts_sent": 0,
            "viral_posts": [],
        }

        try:
            # Get posts from last 24 hours
            recent_posts = await self._get_recent_posts(hours=24)

            for post in recent_posts:
                hours_since = self._hours_since_posted(post)

                # Check at 1h, 3h, 6h marks
                if 1 <= hours_since < 2:
                    checked = await self._check_at_hour(post, hour=1)
                elif 3 <= hours_since < 4:
                    checked = await self._check_at_hour(post, hour=3)
                elif 6 <= hours_since < 7:
                    checked = await self._check_at_hour(post, hour=6)
                else:
                    checked = False

                if checked:
                    results["posts_checked"] += 1
                    if checked.get("is_viral"):
                        results["alerts_sent"] += 1
                        results["viral_posts"].append(checked)

            self.log_complete(results)

        except Exception as e:
            self.log_error(e)
            results["error"] = str(e)

        return results

    async def _get_recent_posts(self, hours: int = 24) -> List[Post]:
        """Get posts from the last N hours."""
        session = db.get_session()
        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            posts = session.query(Post).filter(
                Post.posted_at >= cutoff
            ).order_by(Post.posted_at.desc()).all()
            return posts
        finally:
            session.close()

    def _hours_since_posted(self, post: Post) -> float:
        """Calculate hours since post was published."""
        if not post.posted_at:
            return 0
        delta = datetime.utcnow() - post.posted_at
        return delta.total_seconds() / 3600

    async def _check_at_hour(self, post: Post, hour: int) -> Optional[Dict]:
        """
        Analyze post performance at specific hour mark.

        Returns dict with analysis if viral, None otherwise.
        """
        # Check if already analyzed at this hour
        if await self._already_checked(post, hour):
            return None

        # Get current metrics (refresh from scraper if possible)
        current_views = post.views or 0
        current_likes = post.likes or 0
        current_comments = post.comments or 0
        current_shares = post.shares or 0

        # Get my historical averages at this hour mark
        avg_views = await self._get_average_views_at_hour(hour, post.platform)
        avg_likes = await self._get_average_likes_at_hour(hour, post.platform)

        # Calculate multipliers
        view_multiplier = current_views / avg_views if avg_views > 0 else 1.0
        like_multiplier = current_likes / avg_likes if avg_likes > 0 else 1.0

        # Determine virality level
        is_viral = view_multiplier >= self.viral_multiplier or like_multiplier >= 2.5
        is_super_viral = view_multiplier >= self.super_viral_multiplier

        # Predict final views
        predicted_views = self._predict_final_views(current_views, hour)

        # Record metrics history
        await self._record_metrics(post, hour, current_views, current_likes, current_comments, current_shares)

        if is_viral:
            # Send alert
            await self._send_virality_alert(
                post=post,
                hour=hour,
                current_views=current_views,
                current_likes=current_likes,
                current_comments=current_comments,
                current_shares=current_shares,
                avg_views=avg_views,
                avg_likes=avg_likes,
                view_multiplier=view_multiplier,
                predicted_views=predicted_views,
                is_super_viral=is_super_viral
            )

            return {
                "is_viral": True,
                "is_super_viral": is_super_viral,
                "post_id": post.id,
                "multiplier": view_multiplier,
                "predicted_views": predicted_views,
            }

        return {"is_viral": False, "post_id": post.id}

    async def _already_checked(self, post: Post, hour: int) -> bool:
        """Check if we already recorded metrics at this hour mark."""
        session = db.get_session()
        try:
            existing = session.query(PostMetricHistory).filter(
                PostMetricHistory.post_id == post.id,
                PostMetricHistory.hours_since_post == hour
            ).first()
            return existing is not None
        finally:
            session.close()

    async def _get_average_views_at_hour(self, hour: int, platform: str) -> float:
        """Get historical average views at X hours after posting."""
        session = db.get_session()
        try:
            # Get historical metrics at this hour mark
            metrics = session.query(PostMetricHistory).join(Post).filter(
                PostMetricHistory.hours_since_post == hour,
                Post.platform == platform
            ).all()

            if not metrics:
                # Fallback to overall average
                posts = session.query(Post).filter(Post.platform == platform).all()
                if posts:
                    total_views = sum(p.views or 0 for p in posts)
                    # Estimate hour-mark views based on decay curve
                    multiplier = self.prediction_multipliers.get(hour, 1)
                    return (total_views / len(posts)) / multiplier
                return 1000  # Default fallback

            return sum(m.views or 0 for m in metrics) / len(metrics)
        finally:
            session.close()

    async def _get_average_likes_at_hour(self, hour: int, platform: str) -> float:
        """Get historical average likes at X hours after posting."""
        session = db.get_session()
        try:
            metrics = session.query(PostMetricHistory).join(Post).filter(
                PostMetricHistory.hours_since_post == hour,
                Post.platform == platform
            ).all()

            if not metrics:
                posts = session.query(Post).filter(Post.platform == platform).all()
                if posts:
                    total_likes = sum(p.likes or 0 for p in posts)
                    multiplier = self.prediction_multipliers.get(hour, 1)
                    return (total_likes / len(posts)) / multiplier
                return 100  # Default fallback

            return sum(m.likes or 0 for m in metrics) / len(metrics)
        finally:
            session.close()

    def _predict_final_views(self, current_views: int, hours_since_post: int) -> int:
        """Predict final views based on current performance."""
        multiplier = self.prediction_multipliers.get(hours_since_post, 1)
        return int(current_views * multiplier)

    async def _record_metrics(self, post: Post, hour: int, views: int, likes: int, comments: int, shares: int):
        """Record metrics at this hour mark."""
        session = db.get_session()
        try:
            metric = PostMetricHistory(
                post_id=post.id,
                hours_since_post=hour,
                views=views,
                likes=likes,
                comments=comments,
                shares=shares,
            )
            session.add(metric)
            session.commit()
        finally:
            session.close()

    async def _send_virality_alert(
        self,
        post: Post,
        hour: int,
        current_views: int,
        current_likes: int,
        current_comments: int,
        current_shares: int,
        avg_views: float,
        avg_likes: float,
        view_multiplier: float,
        predicted_views: int,
        is_super_viral: bool
    ):
        """Send WhatsApp alert about viral post."""

        if is_super_viral:
            emoji = "🚀🚀🚀"
            title = "הסרטון שלך מתפוצץ!"
        else:
            emoji = "🚀"
            title = "הסרטון החדש שלך עובד מעולה!"

        caption_preview = (post.caption or "")[:50]
        if len(post.caption or "") > 50:
            caption_preview += "..."

        message = f"""{emoji} *{title}*

📊 *ביצועים אחרי {hour} שעות:*
- צפיות: {current_views:,} (הממוצע שלך: {int(avg_views):,})
- לייקים: {current_likes:,} (הממוצע שלך: {int(avg_likes):,})
- תגובות: {current_comments:,}
- שיתופים: {current_shares:,}

📈 *זה פי {view_multiplier:.1f} מהממוצע שלך!*

🔮 *חיזוי:* {predicted_views:,} צפיות עד מחר

💡 *מה לעשות עכשיו:*
1. תעלה סטורי שמפנה לסרטון הזה
2. תגיב ל-5-10 תגובות (מגביר אלגוריתם!)
3. אל תעלה סרטון חדש היום - תן לזה לרוץ
4. שתף בסטורי באינסטגרם אם זה מטיקטוק

🎬 הסרטון: '{caption_preview}'"""

        sid = whatsapp.send_message(message)
        logger.info(f"Virality alert sent for post {post.id}: {view_multiplier:.1f}x average")
        return sid is not None

    async def get_performance_summary(self, limit: int = 3) -> Dict[str, Any]:
        """
        Get performance summary for recent posts.
        Used for "ביצועים" command.
        """
        session = db.get_session()
        try:
            # Get recent posts
            posts = session.query(Post).order_by(
                Post.posted_at.desc()
            ).limit(limit).all()

            # Get overall averages
            all_posts = session.query(Post).all()
            avg_views = sum(p.views or 0 for p in all_posts) / len(all_posts) if all_posts else 1

            summaries = []
            for post in posts:
                hours_since = self._hours_since_posted(post)
                views = post.views or 0
                likes = post.likes or 0
                comments = post.comments or 0

                multiplier = views / avg_views if avg_views > 0 else 1.0

                # Determine status
                if hours_since < 24:
                    # Still running - predict final
                    predicted = self._predict_final_views(views, min(int(hours_since), 6))
                    status = "running"
                else:
                    predicted = views
                    status = "finished"

                # Performance level
                if multiplier >= 2:
                    performance = "viral"
                    emoji = "🔥"
                elif multiplier >= 1:
                    performance = "above_average"
                    emoji = "✅"
                else:
                    performance = "below_average"
                    emoji = "😐"

                summaries.append({
                    "post_id": post.id,
                    "caption": (post.caption or "")[:40],
                    "platform": post.platform,
                    "hours_since": hours_since,
                    "views": views,
                    "likes": likes,
                    "comments": comments,
                    "multiplier": multiplier,
                    "predicted_views": predicted,
                    "status": status,
                    "performance": performance,
                    "emoji": emoji,
                })

            return {
                "posts": summaries,
                "avg_views": avg_views,
            }

        finally:
            session.close()

    async def learn_from_predictions(self):
        """
        After 24 hours, compare predictions to actual.
        Run weekly to improve prediction accuracy.
        """
        session = db.get_session()
        try:
            # Get posts from 24-48 hours ago (finished running)
            cutoff_start = datetime.utcnow() - timedelta(hours=48)
            cutoff_end = datetime.utcnow() - timedelta(hours=24)

            posts = session.query(Post).filter(
                Post.posted_at >= cutoff_start,
                Post.posted_at <= cutoff_end
            ).all()

            accuracies = []
            for post in posts:
                # Get hour 6 metrics (our prediction point)
                hour_6_metric = session.query(PostMetricHistory).filter(
                    PostMetricHistory.post_id == post.id,
                    PostMetricHistory.hours_since_post == 6
                ).first()

                if hour_6_metric:
                    predicted = self._predict_final_views(hour_6_metric.views, 6)
                    actual = post.views or 0

                    if predicted > 0:
                        accuracy = min(actual / predicted, predicted / actual)
                        accuracies.append(accuracy)

            avg_accuracy = sum(accuracies) / len(accuracies) if accuracies else 0
            logger.info(f"Prediction accuracy: {avg_accuracy:.2%}")

            return {
                "samples": len(accuracies),
                "avg_accuracy": avg_accuracy,
            }

        finally:
            session.close()
