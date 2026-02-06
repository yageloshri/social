"""
ProfileScanner Skill
====================
Scrapes and processes social media content from Instagram and TikTok.
Uses Apify for both platforms - handles proxies and rate limiting automatically.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging
import json

from apify_client import ApifyClient

from .base import BaseSkill
from ..config import config
from ..database import db, Post, PostMetricHistory, ScraperStatus

logger = logging.getLogger(__name__)


class ProfileScanner(BaseSkill):
    """
    Scrapes social media profiles for content and metrics.

    Capabilities:
    - Fetch posts from Instagram (via Apify)
    - Fetch videos from TikTok (via Apify)
    - Extract metrics: views, likes, comments, shares, saves
    - Calculate engagement rates
    - Track metric changes over time

    Uses Apify for both platforms because:
    - Handles proxies automatically (no blocks/rate limits)
    - More reliable than direct scraping
    - We already pay for it
    """

    def __init__(self):
        super().__init__("ProfileScanner")
        self.apify_client = ApifyClient(config.scraping.apify_token) if config.scraping.apify_token else None

    async def execute(
        self,
        platforms: List[str] = None,
        full_scan: bool = False
    ) -> Dict[str, Any]:
        """
        Execute profile scanning.

        OPTIMIZED: Only fetches last 10 posts per platform (configurable).
        - First scan: Analyzes 10 posts
        - Daily scans: Usually 0-2 new posts to analyze
        - Saves ~90% of API calls vs fetching entire profile

        Args:
            platforms: List of platforms to scan ('instagram', 'tiktok'). Defaults to both.
            full_scan: If True, fetch slightly more posts (for initial setup)

        Returns:
            Dict with scan results and statistics
        """
        self.log_start()

        if platforms is None:
            platforms = ["instagram", "tiktok"]

        # Use optimized post limit from config (default: 10)
        max_posts = config.scraping.posts_per_scan
        if full_scan:
            max_posts = config.scraping.active_posts_limit  # 30 for full scan

        results = {
            "instagram": None,
            "tiktok": None,
            "new_posts": 0,
            "updated_posts": 0,
            "new_post_analyses": [],  # Smart analysis for new posts
            "errors": [],
        }

        try:
            if "instagram" in platforms and config.scraping.instagram_handle:
                results["instagram"] = await self._scan_instagram(
                    config.scraping.instagram_handle,
                    max_posts=max_posts
                )
                results["new_posts"] += results["instagram"].get("new_posts", 0)
                results["updated_posts"] += results["instagram"].get("updated_posts", 0)
                results["new_post_analyses"].extend(results["instagram"].get("analyses", []))

            if "tiktok" in platforms and config.scraping.tiktok_handle:
                results["tiktok"] = await self._scan_tiktok(
                    config.scraping.tiktok_handle,
                    max_posts=max_posts
                )
                results["new_posts"] += results["tiktok"].get("new_posts", 0)
                results["updated_posts"] += results["tiktok"].get("updated_posts", 0)
                results["new_post_analyses"].extend(results["tiktok"].get("analyses", []))

            # Run periodic maintenance
            await self._archive_old_posts()

            results["summary"] = f"Scanned {results['new_posts']} new, {results['updated_posts']} updated posts"
            self.log_complete(results)

        except Exception as e:
            self.log_error(e)
            results["errors"].append(str(e))

        return results

    async def _scan_instagram(self, handle: str, max_posts: int = 10) -> Dict[str, Any]:
        """
        Scan Instagram profile using Apify (handles proxies and rate limits).

        Args:
            handle: Instagram username
            max_posts: Maximum posts to fetch (default: 10)

        Returns:
            Dict with scan results including smart analysis for new posts
        """
        result = {"new_posts": 0, "updated_posts": 0, "errors": [], "analyses": []}

        if not self.apify_client:
            result["errors"].append("Apify client not configured")
            return result

        try:
            # Run Apify Instagram scraper
            run_input = {
                "usernames": [handle],
                "resultsLimit": max_posts,
            }

            logger.info(f"Running Apify Instagram scraper for @{handle}...")

            # Use the Instagram Profile Scraper actor
            run = self.apify_client.actor("apify/instagram-profile-scraper").call(run_input=run_input)

            # Fetch results
            items = list(self.apify_client.dataset(run["defaultDatasetId"]).iterate_items())

            # The profile scraper returns profile data with posts in 'latestPosts' field
            posts_list = []
            for item in items:
                # Extract posts from the profile's latestPosts field
                latest_posts = item.get("latestPosts", [])
                posts_list.extend(latest_posts)

            logger.info(f"Apify returned {len(posts_list)} posts for Instagram")

            # Get historical averages for comparison
            historical = await self.get_historical_averages("instagram")

            session = db.get_session()
            try:
                new_posts_for_analysis = []
                import re

                for post in posts_list:
                    # Get post ID - use shortCode as the unique identifier
                    post_id = post.get("shortCode") or post.get("id") or post.get("code")
                    if not post_id:
                        continue

                    post_id = str(post_id)
                    existing = session.query(Post).filter_by(post_id=post_id).first()

                    # Get caption and extract hashtags/mentions
                    caption = post.get("caption", "") or ""

                    # Use provided hashtags or extract from caption
                    hashtags = post.get("hashtags", [])
                    if not hashtags and caption:
                        hashtags = re.findall(r'#(\w+)', caption)

                    # Use provided mentions or extract from caption
                    mentions = post.get("mentions", [])
                    if not mentions and caption:
                        mentions = re.findall(r'@(\w+)', caption)

                    # Determine media type
                    post_type = post.get("type", "").lower()
                    if post_type == "video" or post.get("isVideo"):
                        media_type = "video"
                    elif post_type == "sidecar" or post.get("childPosts"):
                        media_type = "carousel"
                    else:
                        media_type = "image"

                    # Parse timestamp
                    posted_at = None
                    timestamp = post.get("timestamp") or post.get("takenAt")
                    if timestamp:
                        if isinstance(timestamp, str):
                            try:
                                posted_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                            except:
                                pass
                        elif isinstance(timestamp, (int, float)):
                            posted_at = datetime.fromtimestamp(timestamp)

                    post_data = {
                        "post_id": post_id,
                        "url": post.get("url") or f"https://www.instagram.com/p/{post_id}/",
                        "caption": caption,
                        "hashtags": hashtags,
                        "mentions": mentions,
                        "media_type": media_type,
                        "views": post.get("videoViewCount", 0) or post.get("videoPlayCount", 0) or post.get("playCount", 0) or 0,
                        "likes": post.get("likesCount", 0) or post.get("likeCount", 0) or 0,
                        "comments": post.get("commentsCount", 0) or post.get("commentCount", 0) or 0,
                        "posted_at": posted_at,
                    }

                    if existing:
                        # Update existing post metrics
                        self._update_post_metrics(session, existing, post_data)
                        result["updated_posts"] += 1
                    else:
                        # Create new post
                        new_post = Post(
                            platform="instagram",
                            post_id=post_data["post_id"],
                            url=post_data["url"],
                            caption=post_data.get("caption"),
                            hashtags=post_data.get("hashtags", []),
                            mentions=post_data.get("mentions", []),
                            media_type=post_data.get("media_type"),
                            views=post_data.get("views", 0),
                            likes=post_data.get("likes", 0),
                            comments=post_data.get("comments", 0),
                            posted_at=post_data.get("posted_at"),
                        )
                        session.add(new_post)
                        result["new_posts"] += 1
                        new_posts_for_analysis.append(post_data)

                # Update scraper status
                self._update_scraper_status(
                    session, "instagram",
                    success=True,
                    posts_fetched=len(posts_list)
                )

                session.commit()

                # Generate smart analysis for new posts only
                for post_data in new_posts_for_analysis:
                    analysis = self._analyze_post_vs_historical(post_data, historical, "instagram")
                    if analysis:
                        result["analyses"].append(analysis)

            finally:
                session.close()

        except Exception as e:
            logger.error(f"Instagram scan error: {e}")
            result["errors"].append(str(e))
            # Update scraper status with error
            session = db.get_session()
            try:
                self._update_scraper_status(session, "instagram", success=False, error=str(e))
                session.commit()
            finally:
                session.close()

        return result

    async def _scan_tiktok(self, handle: str, max_posts: int = 10) -> Dict[str, Any]:
        """
        Scan TikTok profile using Apify (OPTIMIZED - only last N posts).

        Args:
            handle: TikTok username
            max_posts: Maximum posts to fetch (default: 10)

        Returns:
            Dict with scan results including smart analysis for new posts
        """
        result = {"new_posts": 0, "updated_posts": 0, "errors": [], "analyses": []}

        if not self.apify_client:
            result["errors"].append("Apify client not configured")
            return result

        try:
            # Run Apify TikTok scraper (OPTIMIZED: only fetch last N posts)
            run_input = {
                "profiles": [handle],
                "resultsPerPage": max_posts,  # Only last 10 posts
                "shouldDownloadVideos": False,
                "shouldDownloadCovers": False,
                "shouldDownloadSubtitles": False,
                "shouldDownloadSlideshowImages": False,
            }

            # Use the official TikTok Scraper actor
            run = self.apify_client.actor("clockworks/tiktok-scraper").call(run_input=run_input)

            # Fetch results
            items = list(self.apify_client.dataset(run["defaultDatasetId"]).iterate_items())

            # Get historical averages for comparison
            historical = await self.get_historical_averages("tiktok")

            session = db.get_session()
            try:
                new_posts_for_analysis = []

                for item in items:
                    post_id = str(item.get("id", ""))
                    if not post_id:
                        continue

                    existing = session.query(Post).filter_by(post_id=post_id).first()

                    # Extract hashtags - they come as list of dicts with 'name' key
                    hashtags_raw = item.get("hashtags", [])
                    hashtags = []
                    for tag in hashtags_raw:
                        if isinstance(tag, dict):
                            name = tag.get("name", "")
                            if name:
                                hashtags.append(name)
                        elif isinstance(tag, str):
                            hashtags.append(tag)

                    # Extract mentions - they come as list of strings like '@username'
                    mentions_raw = item.get("mentions", [])
                    mentions = []
                    for mention in mentions_raw:
                        if isinstance(mention, dict):
                            user_id = mention.get("userUniqueId", "") or mention.get("uniqueId", "")
                            if user_id:
                                mentions.append(user_id)
                        elif isinstance(mention, str):
                            # Remove @ prefix if present
                            mentions.append(mention.lstrip("@"))

                    # Extract video metadata safely
                    video_meta = item.get("videoMeta", {}) or {}
                    duration = video_meta.get("duration", 0) if isinstance(video_meta, dict) else 0

                    post_data = {
                        "post_id": post_id,
                        "url": item.get("webVideoUrl", ""),
                        "caption": item.get("text", ""),
                        "hashtags": hashtags,
                        "mentions": mentions,
                        "media_type": "video",
                        "duration_seconds": duration,
                        "views": item.get("playCount", 0),
                        "likes": item.get("diggCount", 0),
                        "comments": item.get("commentCount", 0),
                        "shares": item.get("shareCount", 0),
                        "posted_at": datetime.fromtimestamp(item.get("createTime", 0)) if item.get("createTime") else None,
                    }

                    if existing:
                        self._update_post_metrics(session, existing, post_data)
                        result["updated_posts"] += 1
                    else:
                        new_post = Post(
                            platform="tiktok",
                            **post_data
                        )
                        session.add(new_post)
                        result["new_posts"] += 1
                        new_posts_for_analysis.append(post_data)

                # Update scraper status
                self._update_scraper_status(
                    session, "tiktok",
                    success=True,
                    posts_fetched=len(items)
                )

                session.commit()

                # Generate smart analysis for new posts only
                for post_data in new_posts_for_analysis:
                    analysis = self._analyze_post_vs_historical(post_data, historical, "tiktok")
                    if analysis:
                        result["analyses"].append(analysis)

            finally:
                session.close()

        except Exception as e:
            logger.error(f"TikTok scan error: {e}")
            result["errors"].append(str(e))
            # Update scraper status with error
            session = db.get_session()
            try:
                self._update_scraper_status(session, "tiktok", success=False, error=str(e))
                session.commit()
            finally:
                session.close()

        return result

    def _update_post_metrics(self, session, post: Post, new_data: Dict):
        """
        Update post metrics and record history.

        Args:
            session: Database session
            post: Existing post to update
            new_data: New metric data
        """
        # Record current metrics to history before updating
        history = PostMetricHistory(
            post_id=post.id,
            views=post.views,
            likes=post.likes,
            comments=post.comments,
            shares=post.shares,
            saves=post.saves,
        )
        session.add(history)

        # Update metrics
        post.views = new_data.get("views", post.views)
        post.likes = new_data.get("likes", post.likes)
        post.comments = new_data.get("comments", post.comments)
        post.shares = new_data.get("shares", post.shares)
        post.saves = new_data.get("saves", post.saves)
        post.last_updated = datetime.utcnow()

        # Calculate engagement rate
        total_engagement = post.likes + post.comments + (post.shares or 0) + (post.saves or 0)
        if post.views and post.views > 0:
            post.engagement_rate = (total_engagement / post.views) * 100

    async def get_recent_posts(
        self,
        platform: str = None,
        days: int = 30,
        limit: int = 50
    ) -> List[Post]:
        """
        Get recent posts from database.

        Args:
            platform: Filter by platform (optional)
            days: Number of days to look back
            limit: Maximum posts to return

        Returns:
            List of Post objects
        """
        session = db.get_session()
        try:
            query = session.query(Post)

            if platform:
                query = query.filter(Post.platform == platform)

            cutoff = datetime.utcnow() - timedelta(days=days)
            query = query.filter(Post.posted_at >= cutoff)

            return query.order_by(Post.posted_at.desc()).limit(limit).all()
        finally:
            session.close()

    async def get_top_performing(
        self,
        platform: str = None,
        days: int = 90,
        limit: int = 10
    ) -> List[Post]:
        """
        Get top performing posts by engagement rate.

        Args:
            platform: Filter by platform (optional)
            days: Number of days to look back
            limit: Maximum posts to return

        Returns:
            List of Post objects sorted by engagement
        """
        session = db.get_session()
        try:
            query = session.query(Post)

            if platform:
                query = query.filter(Post.platform == platform)

            cutoff = datetime.utcnow() - timedelta(days=days)
            query = query.filter(Post.posted_at >= cutoff)

            return query.order_by(Post.engagement_rate.desc()).limit(limit).all()
        finally:
            session.close()

    def _update_scraper_status(
        self,
        session,
        platform: str,
        success: bool,
        posts_fetched: int = 0,
        error: str = None
    ):
        """Update scraper status in database."""
        status = session.query(ScraperStatus).filter_by(platform=platform).first()

        if not status:
            status = ScraperStatus(platform=platform)
            session.add(status)

        status.last_scan_at = datetime.utcnow()
        if success:
            status.last_success_at = datetime.utcnow()
            status.status = "working"
            status.posts_fetched = posts_fetched
            status.last_error = None
        else:
            status.status = "failed"
            status.last_error = error

    async def get_scraper_status(self) -> Dict[str, Any]:
        """
        Get scraper status for all platforms.

        Returns:
            Dict with status for each platform
        """
        session = db.get_session()
        try:
            result = {
                "instagram": {
                    "status": "unknown",
                    "last_scan": None,
                    "last_success": None,
                    "error": None,
                },
                "tiktok": {
                    "status": "unknown",
                    "last_scan": None,
                    "last_success": None,
                    "error": None,
                },
            }

            for platform in ["instagram", "tiktok"]:
                status = session.query(ScraperStatus).filter_by(platform=platform).first()
                if status:
                    result[platform] = {
                        "status": status.status,
                        "last_scan": status.last_scan_at,
                        "last_success": status.last_success_at,
                        "posts_fetched": status.posts_fetched,
                        "error": status.last_error,
                    }

            # Get total posts count
            total_posts = session.query(Post).count()
            result["total_posts"] = total_posts

            # Get average engagement
            from sqlalchemy import func
            avg_engagement = session.query(func.avg(Post.engagement_rate)).scalar()
            result["avg_engagement"] = avg_engagement or 0

            return result
        finally:
            session.close()

    async def get_latest_posts_summary(self, limit: int = 3) -> Dict[str, List[Dict]]:
        """
        Get latest posts summary for each platform.

        Args:
            limit: Number of posts per platform

        Returns:
            Dict with latest posts for each platform
        """
        session = db.get_session()
        try:
            result = {"instagram": [], "tiktok": []}

            for platform in ["instagram", "tiktok"]:
                posts = session.query(Post).filter(
                    Post.platform == platform
                ).order_by(Post.posted_at.desc()).limit(limit).all()

                for post in posts:
                    result[platform].append({
                        "caption": (post.caption or "")[:50] + "..." if post.caption and len(post.caption) > 50 else (post.caption or ""),
                        "posted_at": post.posted_at,
                        "views": post.views or 0,
                        "likes": post.likes or 0,
                        "comments": post.comments or 0,
                        "shares": post.shares or 0,
                        "engagement_rate": post.engagement_rate or 0,
                    })

            return result
        finally:
            session.close()

    async def get_days_since_last_post(self) -> Dict[str, int]:
        """
        Get days since last post for each platform.

        Returns:
            Dict with days since last post per platform
        """
        session = db.get_session()
        try:
            result = {"instagram": None, "tiktok": None}

            for platform in ["instagram", "tiktok"]:
                latest = session.query(Post).filter(
                    Post.platform == platform
                ).order_by(Post.posted_at.desc()).first()

                if latest and latest.posted_at:
                    days = (datetime.utcnow() - latest.posted_at).days
                    result[platform] = days

            return result
        finally:
            session.close()

    async def get_historical_averages(self, platform: str = None) -> Dict[str, Any]:
        """
        Calculate historical averages from all stored posts.

        Used for smart comparison when analyzing new posts.

        Args:
            platform: Filter by platform (optional)

        Returns:
            Dict with averages for views, likes, comments, engagement, etc.
        """
        from sqlalchemy import func

        session = db.get_session()
        try:
            query = session.query(
                func.avg(Post.views).label("avg_views"),
                func.avg(Post.likes).label("avg_likes"),
                func.avg(Post.comments).label("avg_comments"),
                func.avg(Post.shares).label("avg_shares"),
                func.avg(Post.engagement_rate).label("avg_engagement"),
                func.count(Post.id).label("total_posts"),
                func.max(Post.views).label("max_views"),
                func.max(Post.likes).label("max_likes"),
            )

            if platform:
                query = query.filter(Post.platform == platform)

            result = query.first()

            # Also get recent 10 posts averages (for comparison context)
            recent_query = session.query(
                func.avg(Post.views).label("avg_views"),
                func.avg(Post.likes).label("avg_likes"),
                func.avg(Post.comments).label("avg_comments"),
            )
            if platform:
                recent_query = recent_query.filter(Post.platform == platform)
            recent_query = recent_query.order_by(Post.posted_at.desc()).limit(10)

            # Get last 10 posts for recent averages
            recent_posts = session.query(Post)
            if platform:
                recent_posts = recent_posts.filter(Post.platform == platform)
            recent_posts = recent_posts.order_by(Post.posted_at.desc()).limit(10).all()

            recent_avg_views = sum(p.views or 0 for p in recent_posts) / len(recent_posts) if recent_posts else 0
            recent_avg_likes = sum(p.likes or 0 for p in recent_posts) / len(recent_posts) if recent_posts else 0
            recent_avg_comments = sum(p.comments or 0 for p in recent_posts) / len(recent_posts) if recent_posts else 0

            # Get top performing categories
            category_stats = session.query(
                Post.category,
                func.avg(Post.engagement_rate).label("avg_eng"),
                func.count(Post.id).label("count")
            ).filter(Post.category.isnot(None))
            if platform:
                category_stats = category_stats.filter(Post.platform == platform)
            category_stats = category_stats.group_by(Post.category).order_by(
                func.avg(Post.engagement_rate).desc()
            ).limit(5).all()

            return {
                "all_time": {
                    "avg_views": float(result.avg_views or 0),
                    "avg_likes": float(result.avg_likes or 0),
                    "avg_comments": float(result.avg_comments or 0),
                    "avg_shares": float(result.avg_shares or 0),
                    "avg_engagement": float(result.avg_engagement or 0),
                    "total_posts": result.total_posts or 0,
                    "max_views": result.max_views or 0,
                    "max_likes": result.max_likes or 0,
                },
                "recent_10": {
                    "avg_views": recent_avg_views,
                    "avg_likes": recent_avg_likes,
                    "avg_comments": recent_avg_comments,
                },
                "top_categories": [
                    {"category": c.category, "avg_engagement": float(c.avg_eng or 0), "count": c.count}
                    for c in category_stats
                ],
            }
        finally:
            session.close()

    def _analyze_post_vs_historical(
        self,
        post_data: Dict,
        historical: Dict,
        platform: str
    ) -> Optional[Dict]:
        """
        Analyze a new post compared to historical averages.

        Generates insights like:
        "הסרטון החדש שלך עשה 50K צפיות - זה פי 2 מהממוצע של 10 הסרטונים האחרונים שלך (25K)"

        Args:
            post_data: New post data
            historical: Historical averages from get_historical_averages()
            platform: Platform name

        Returns:
            Analysis dict or None if insufficient data
        """
        recent = historical.get("recent_10", {})
        all_time = historical.get("all_time", {})

        if all_time.get("total_posts", 0) < 3:
            return None  # Not enough data for comparison

        views = post_data.get("views", 0)
        likes = post_data.get("likes", 0)
        comments = post_data.get("comments", 0)

        recent_avg_views = recent.get("avg_views", 1)
        recent_avg_likes = recent.get("avg_likes", 1)
        all_time_avg_views = all_time.get("avg_views", 1)

        # Calculate multipliers
        views_vs_recent = views / recent_avg_views if recent_avg_views > 0 else 0
        views_vs_all_time = views / all_time_avg_views if all_time_avg_views > 0 else 0

        # Determine performance level
        if views_vs_recent >= 2:
            performance = "exceptional"
            emoji = "🚀"
        elif views_vs_recent >= 1.5:
            performance = "above_average"
            emoji = "📈"
        elif views_vs_recent >= 0.8:
            performance = "average"
            emoji = "➡️"
        else:
            performance = "below_average"
            emoji = "📉"

        # Generate Hebrew analysis text
        caption_preview = (post_data.get("caption", "") or "")[:30]
        if len(post_data.get("caption", "") or "") > 30:
            caption_preview += "..."

        if platform == "tiktok":
            analysis_text = f"{emoji} הסרטון '{caption_preview}' עשה {self._format_number(views)} צפיות"
            if views_vs_recent >= 1.5:
                analysis_text += f" - זה פי {views_vs_recent:.1f} מהממוצע של 10 הסרטונים האחרונים שלך ({self._format_number(int(recent_avg_views))})"
            elif views_vs_recent < 0.8:
                analysis_text += f" - זה מתחת לממוצע שלך ({self._format_number(int(recent_avg_views))})"
        else:
            analysis_text = f"{emoji} הפוסט '{caption_preview}' קיבל {self._format_number(likes)} לייקים"
            if views_vs_recent >= 1.5:
                analysis_text += f" - ביצועים מעולים!"

        return {
            "platform": platform,
            "post_id": post_data.get("post_id"),
            "caption_preview": caption_preview,
            "views": views,
            "likes": likes,
            "comments": comments,
            "performance": performance,
            "views_vs_recent": views_vs_recent,
            "views_vs_all_time": views_vs_all_time,
            "analysis_text": analysis_text,
        }

    def _format_number(self, num: int) -> str:
        """Format large numbers for display."""
        if num >= 1_000_000:
            return f"{num / 1_000_000:.1f}M"
        elif num >= 1_000:
            return f"{num / 1_000:.1f}K"
        return str(num)

    async def _archive_old_posts(self):
        """
        Archive old posts to save database space.

        Strategy:
        - Keep last 30 posts in full detail (active analysis)
        - Archive posts older than 90 days (keep stats, delete captions)

        This maintains:
        - Average views/likes/comments
        - Best performing topics
        - Historical engagement rate
        """
        session = db.get_session()
        try:
            # Get posts older than archive threshold
            cutoff = datetime.utcnow() - timedelta(days=config.scraping.archive_after_days)

            old_posts = session.query(Post).filter(
                Post.posted_at < cutoff,
                Post.caption.isnot(None),  # Only process non-archived posts
                Post.caption != "[ARCHIVED]"
            ).all()

            archived_count = 0
            for post in old_posts:
                # Keep stats, archive content
                post.caption = "[ARCHIVED]"
                post.ai_analysis = None  # Clear detailed analysis
                archived_count += 1

            if archived_count > 0:
                session.commit()
                logger.info(f"Archived {archived_count} old posts")

        except Exception as e:
            logger.error(f"Error archiving posts: {e}")
        finally:
            session.close()

    async def get_performance_summary(self, platform: str = None) -> Dict[str, Any]:
        """
        Get comprehensive performance summary for reporting.

        Args:
            platform: Filter by platform (optional)

        Returns:
            Dict with performance metrics and insights
        """
        historical = await self.get_historical_averages(platform)
        days_since = await self.get_days_since_last_post()

        return {
            "historical_averages": historical,
            "days_since_last_post": days_since,
            "recommendations": self._generate_posting_recommendations(historical, days_since),
        }

    def _generate_posting_recommendations(
        self,
        historical: Dict,
        days_since: Dict
    ) -> List[str]:
        """Generate posting recommendations based on data."""
        recommendations = []

        # Check posting frequency
        for platform, days in days_since.items():
            if days is not None and days >= 4:
                recommendations.append(f"⚠️ עברו {days} ימים מהפוסט האחרון ב-{platform.title()}")

        # Suggest top performing categories
        top_cats = historical.get("top_categories", [])
        if top_cats:
            best = top_cats[0]
            recommendations.append(
                f"💡 תוכן מסוג '{best['category']}' מביא לך הכי הרבה engagement ({best['avg_engagement']:.1f}%)"
            )

        return recommendations
