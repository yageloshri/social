"""
ProfileScanner Skill
====================
Scrapes and processes social media content from Instagram and TikTok.
Uses Instaloader for Instagram and Apify for TikTok.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging
import json

import instaloader
from apify_client import ApifyClient

from .base import BaseSkill
from ..config import config
from ..database import db, Post, PostMetricHistory

logger = logging.getLogger(__name__)


class ProfileScanner(BaseSkill):
    """
    Scrapes social media profiles for content and metrics.

    Capabilities:
    - Fetch posts from Instagram (via Instaloader)
    - Fetch videos from TikTok (via Apify)
    - Extract metrics: views, likes, comments, shares, saves
    - Calculate engagement rates
    - Track metric changes over time
    """

    def __init__(self):
        super().__init__("ProfileScanner")
        self.insta_loader = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
        )
        self.apify_client = ApifyClient(config.scraping.apify_token) if config.scraping.apify_token else None

    async def execute(
        self,
        platforms: List[str] = None,
        full_scan: bool = False,
        max_posts: int = 50
    ) -> Dict[str, Any]:
        """
        Execute profile scanning.

        Args:
            platforms: List of platforms to scan ('instagram', 'tiktok'). Defaults to both.
            full_scan: If True, fetch more historical posts
            max_posts: Maximum posts to fetch per platform

        Returns:
            Dict with scan results and statistics
        """
        self.log_start()

        if platforms is None:
            platforms = ["instagram", "tiktok"]

        results = {
            "instagram": None,
            "tiktok": None,
            "new_posts": 0,
            "updated_posts": 0,
            "errors": [],
        }

        try:
            if "instagram" in platforms and config.scraping.instagram_handle:
                results["instagram"] = await self._scan_instagram(
                    config.scraping.instagram_handle,
                    max_posts=max_posts if full_scan else 20
                )
                results["new_posts"] += results["instagram"].get("new_posts", 0)
                results["updated_posts"] += results["instagram"].get("updated_posts", 0)

            if "tiktok" in platforms and config.scraping.tiktok_handle:
                results["tiktok"] = await self._scan_tiktok(
                    config.scraping.tiktok_handle,
                    max_posts=max_posts if full_scan else 20
                )
                results["new_posts"] += results["tiktok"].get("new_posts", 0)
                results["updated_posts"] += results["tiktok"].get("updated_posts", 0)

            results["summary"] = f"Scanned {results['new_posts']} new, {results['updated_posts']} updated posts"
            self.log_complete(results)

        except Exception as e:
            self.log_error(e)
            results["errors"].append(str(e))

        return results

    async def _scan_instagram(self, handle: str, max_posts: int = 50) -> Dict[str, Any]:
        """
        Scan Instagram profile.

        Args:
            handle: Instagram username
            max_posts: Maximum posts to fetch

        Returns:
            Dict with scan results
        """
        result = {"new_posts": 0, "updated_posts": 0, "errors": []}

        try:
            # Run synchronous instaloader in executor
            loop = asyncio.get_event_loop()
            posts_data = await loop.run_in_executor(
                None, self._fetch_instagram_posts, handle, max_posts
            )

            session = db.get_session()
            try:
                for post_data in posts_data:
                    existing = session.query(Post).filter_by(post_id=post_data["post_id"]).first()

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

                session.commit()
            finally:
                session.close()

        except Exception as e:
            logger.error(f"Instagram scan error: {e}")
            result["errors"].append(str(e))

        return result

    def _fetch_instagram_posts(self, handle: str, max_posts: int) -> List[Dict]:
        """Fetch Instagram posts (synchronous, run in executor)."""
        posts_data = []

        try:
            profile = instaloader.Profile.from_username(self.insta_loader.context, handle)
            posts = profile.get_posts()

            for i, post in enumerate(posts):
                if i >= max_posts:
                    break

                posts_data.append({
                    "post_id": post.shortcode,
                    "url": f"https://www.instagram.com/p/{post.shortcode}/",
                    "caption": post.caption or "",
                    "hashtags": list(post.caption_hashtags) if post.caption_hashtags else [],
                    "mentions": list(post.caption_mentions) if post.caption_mentions else [],
                    "media_type": "video" if post.is_video else ("carousel" if post.typename == "GraphSidecar" else "image"),
                    "views": post.video_view_count if post.is_video else 0,
                    "likes": post.likes,
                    "comments": post.comments,
                    "posted_at": post.date_utc,
                })

        except Exception as e:
            logger.error(f"Error fetching Instagram posts: {e}")

        return posts_data

    async def _scan_tiktok(self, handle: str, max_posts: int = 50) -> Dict[str, Any]:
        """
        Scan TikTok profile using Apify.

        Args:
            handle: TikTok username
            max_posts: Maximum posts to fetch

        Returns:
            Dict with scan results
        """
        result = {"new_posts": 0, "updated_posts": 0, "errors": []}

        if not self.apify_client:
            result["errors"].append("Apify client not configured")
            return result

        try:
            # Run Apify TikTok scraper
            run_input = {
                "profiles": [handle],
                "resultsPerPage": max_posts,
                "shouldDownloadVideos": False,
                "shouldDownloadCovers": False,
                "shouldDownloadSubtitles": False,
                "shouldDownloadSlideshowImages": False,
            }

            # Use the official TikTok Scraper actor
            run = self.apify_client.actor("clockworks/tiktok-scraper").call(run_input=run_input)

            # Fetch results
            items = list(self.apify_client.dataset(run["defaultDatasetId"]).iterate_items())

            session = db.get_session()
            try:
                for item in items:
                    post_id = str(item.get("id", ""))
                    if not post_id:
                        continue

                    existing = session.query(Post).filter_by(post_id=post_id).first()

                    post_data = {
                        "post_id": post_id,
                        "url": item.get("webVideoUrl", ""),
                        "caption": item.get("text", ""),
                        "hashtags": [tag.get("name", "") for tag in item.get("hashtags", [])],
                        "mentions": [mention.get("userUniqueId", "") for mention in item.get("mentions", [])],
                        "media_type": "video",
                        "duration_seconds": item.get("videoMeta", {}).get("duration", 0),
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

                session.commit()
            finally:
                session.close()

        except Exception as e:
            logger.error(f"TikTok scan error: {e}")
            result["errors"].append(str(e))

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
