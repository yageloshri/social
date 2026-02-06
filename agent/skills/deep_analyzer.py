"""
DeepAnalyzer Skill
==================
AI-powered content analysis using Claude.
Understands WHY content succeeds or fails.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging
import json

from anthropic import Anthropic

from .base import BaseSkill
from ..config import config
from ..database import db, Post, SuccessPattern

logger = logging.getLogger(__name__)


class DeepAnalyzer(BaseSkill):
    """
    Deep content analysis powered by Claude.

    Capabilities:
    - Compare top performers vs underperformers
    - Identify success patterns
    - Analyze hooks, topics, formats
    - Generate actionable insights
    - Predict potential of new ideas
    """

    def __init__(self):
        super().__init__("DeepAnalyzer")
        self.client = Anthropic(api_key=config.ai.api_key) if config.ai.api_key else None

    async def execute(
        self,
        posts: List[Post] = None,
        analysis_type: str = "comprehensive"
    ) -> Dict[str, Any]:
        """
        Execute deep analysis on posts.

        Args:
            posts: Posts to analyze. If None, fetches from database.
            analysis_type: Type of analysis ('comprehensive', 'quick', 'pattern_discovery')

        Returns:
            Dict with analysis results
        """
        self.log_start()

        if not self.client:
            return {"error": "Anthropic client not configured"}

        results = {
            "analysis_type": analysis_type,
            "insights": [],
            "patterns": [],
            "recommendations": [],
        }

        try:
            # Fetch posts if not provided
            if posts is None:
                session = db.get_session()
                try:
                    posts = session.query(Post).order_by(Post.posted_at.desc()).limit(100).all()
                finally:
                    session.close()

            if not posts:
                return {"error": "No posts to analyze"}

            if analysis_type == "comprehensive":
                results = await self._comprehensive_analysis(posts)
            elif analysis_type == "quick":
                results = await self._quick_analysis(posts[:20])
            elif analysis_type == "pattern_discovery":
                results = await self._discover_patterns(posts)

            self.log_complete(results)

        except Exception as e:
            self.log_error(e)
            results["error"] = str(e)

        return results

    async def _comprehensive_analysis(self, posts: List[Post]) -> Dict[str, Any]:
        """
        Perform comprehensive analysis of all posts.

        Args:
            posts: List of posts to analyze

        Returns:
            Dict with comprehensive insights
        """
        # Prepare posts data for analysis
        posts_data = self._prepare_posts_data(posts)

        # Get top and bottom performers
        sorted_posts = sorted(posts_data, key=lambda x: x.get("engagement_rate", 0), reverse=True)
        top_performers = sorted_posts[:10]
        bottom_performers = sorted_posts[-10:] if len(sorted_posts) > 10 else []

        # Calculate averages
        avg_engagement = sum(p.get("engagement_rate", 0) for p in posts_data) / len(posts_data) if posts_data else 0
        avg_views = sum(p.get("views", 0) for p in posts_data) / len(posts_data) if posts_data else 0

        prompt = f"""You are an expert content analyst for an Israeli musician/content creator.
Analyze this social media data and provide actionable insights.

CREATOR CONTEXT:
- Israeli musician, creates content in Hebrew
- Main topics: Couple content (living with girlfriend), Story times, Trending reactions, Music
- Brand voice: Authentic, natural, relatable - never pretentious
- Target audience: Young Israelis aged 16-30

PERFORMANCE DATA:
Average engagement rate: {avg_engagement:.2f}%
Average views: {avg_views:.0f}

TOP 10 PERFORMING POSTS:
{json.dumps(top_performers, indent=2, ensure_ascii=False)}

BOTTOM 10 PERFORMING POSTS:
{json.dumps(bottom_performers, indent=2, ensure_ascii=False)}

ALL POSTS SUMMARY ({len(posts_data)} posts):
- By category distribution: {self._get_category_distribution(posts_data)}
- By media type: {self._get_media_type_distribution(posts_data)}

PROVIDE:
1. KEY SUCCESS PATTERNS: What specifically makes top posts succeed? Be very specific about hooks, topics, formats.
2. FAILURE PATTERNS: What causes posts to underperform?
3. CATEGORY INSIGHTS: Which categories work best and why?
4. TIMING INSIGHTS: Any patterns in posting time vs performance?
5. SPECIFIC RECOMMENDATIONS: 5 actionable, specific things to do more of (with examples)
6. THINGS TO AVOID: 3 specific things to stop doing

Respond in JSON format:
{{
    "success_patterns": [
        {{"pattern": "description", "evidence": "specific examples", "impact": "multiplier vs average"}}
    ],
    "failure_patterns": [
        {{"pattern": "description", "evidence": "specific examples"}}
    ],
    "category_insights": {{
        "category_name": {{"avg_engagement": X, "recommendation": "what to do"}}
    }},
    "timing_insights": {{"best_times": [], "worst_times": [], "reasoning": ""}},
    "recommendations": [
        {{"action": "specific action", "example": "concrete example", "expected_impact": "high/medium/low"}}
    ],
    "avoid": [
        {{"behavior": "what to avoid", "reason": "why"}}
    ]
}}"""

        response = self.client.messages.create(
            model=config.ai.model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )

        try:
            analysis = json.loads(response.content[0].text)
        except json.JSONDecodeError:
            analysis = {"raw_response": response.content[0].text}

        # Store discovered patterns
        await self._store_patterns(analysis.get("success_patterns", []))

        return {
            "analysis_type": "comprehensive",
            "total_posts_analyzed": len(posts),
            "avg_engagement_rate": avg_engagement,
            "avg_views": avg_views,
            **analysis,
            "summary": f"Analyzed {len(posts)} posts, found {len(analysis.get('success_patterns', []))} success patterns"
        }

    async def _quick_analysis(self, posts: List[Post]) -> Dict[str, Any]:
        """Quick analysis of recent posts."""
        posts_data = self._prepare_posts_data(posts)

        prompt = f"""Quickly analyze these {len(posts_data)} recent social media posts for an Israeli content creator.

POSTS:
{json.dumps(posts_data, indent=2, ensure_ascii=False)}

Provide a brief JSON response:
{{
    "top_performer": {{"post_summary": "", "why_it_worked": ""}},
    "quick_wins": ["3 quick things to try based on recent performance"],
    "trending_topic_opportunity": "any current topic worth jumping on",
    "overall_trend": "improving/stable/declining"
}}"""

        response = self.client.messages.create(
            model=config.ai.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )

        try:
            analysis = json.loads(response.content[0].text)
        except json.JSONDecodeError:
            analysis = {"raw_response": response.content[0].text}

        return {
            "analysis_type": "quick",
            "posts_analyzed": len(posts),
            **analysis,
            "summary": "Quick analysis complete"
        }

    async def _discover_patterns(self, posts: List[Post]) -> Dict[str, Any]:
        """Discover new success patterns from posts."""
        posts_data = self._prepare_posts_data(posts)

        # Group by performance tiers
        sorted_posts = sorted(posts_data, key=lambda x: x.get("engagement_rate", 0), reverse=True)
        top_third = sorted_posts[:len(sorted_posts)//3]
        bottom_third = sorted_posts[-len(sorted_posts)//3:]

        prompt = f"""Discover content patterns by comparing top performing vs low performing posts.

CREATOR: Israeli musician, creates content in Hebrew about couple life, storytimes, reactions, music.

TOP PERFORMERS ({len(top_third)} posts):
{json.dumps(top_third, indent=2, ensure_ascii=False)}

LOW PERFORMERS ({len(bottom_third)} posts):
{json.dumps(bottom_third, indent=2, ensure_ascii=False)}

Find patterns that distinguish success from failure. Look at:
- Caption hooks (opening lines)
- Topics and themes
- Content format and length
- Hashtag strategies
- Emotional triggers

Respond in JSON:
{{
    "discovered_patterns": [
        {{
            "pattern_type": "hook_style|topic|format|emotional_trigger|hashtag",
            "pattern_value": "specific description",
            "found_in_top": "count or percentage",
            "found_in_bottom": "count or percentage",
            "engagement_multiplier": "Xx vs average",
            "confidence": "high/medium/low",
            "examples": ["specific examples from data"]
        }}
    ],
    "anti_patterns": [
        {{
            "pattern": "what NOT to do",
            "evidence": "why this fails"
        }}
    ]
}}"""

        response = self.client.messages.create(
            model=config.ai.model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}]
        )

        try:
            patterns = json.loads(response.content[0].text)
        except json.JSONDecodeError:
            patterns = {"raw_response": response.content[0].text}

        # Store discovered patterns
        await self._store_patterns(patterns.get("discovered_patterns", []))

        return {
            "analysis_type": "pattern_discovery",
            "posts_analyzed": len(posts),
            **patterns,
            "summary": f"Discovered {len(patterns.get('discovered_patterns', []))} patterns"
        }

    async def analyze_single_post(self, post: Post) -> Dict[str, Any]:
        """
        Deep analysis of a single post.

        Args:
            post: Post to analyze

        Returns:
            Dict with detailed analysis
        """
        post_data = {
            "platform": post.platform,
            "caption": post.caption,
            "hashtags": post.hashtags,
            "media_type": post.media_type,
            "views": post.views,
            "likes": post.likes,
            "comments": post.comments,
            "shares": post.shares,
            "engagement_rate": post.engagement_rate,
        }

        prompt = f"""Analyze this single social media post for an Israeli content creator.

POST DATA:
{json.dumps(post_data, indent=2, ensure_ascii=False)}

Provide detailed analysis:
{{
    "hook_analysis": {{"hook_text": "", "effectiveness": "high/medium/low", "improvement": ""}},
    "topic_analysis": {{"detected_topics": [], "relevance_to_audience": ""}},
    "emotional_triggers": ["list of emotional triggers used"],
    "hashtag_effectiveness": {{"good": [], "unnecessary": [], "missing": []}},
    "success_score": 0-100,
    "what_worked": ["specific things that worked"],
    "what_could_improve": ["specific improvements"],
    "replication_guide": "how to create similar successful content"
}}"""

        response = self.client.messages.create(
            model=config.ai.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )

        try:
            analysis = json.loads(response.content[0].text)
        except json.JSONDecodeError:
            analysis = {"raw_response": response.content[0].text}

        # Update post with analysis
        session = db.get_session()
        try:
            db_post = session.query(Post).filter_by(id=post.id).first()
            if db_post:
                db_post.ai_analysis = json.dumps(analysis, ensure_ascii=False)
                db_post.success_score = analysis.get("success_score", 0)
                db_post.topics = analysis.get("topic_analysis", {}).get("detected_topics", [])
                session.commit()
        finally:
            session.close()

        return analysis

    async def predict_performance(self, idea: Dict[str, Any]) -> Dict[str, Any]:
        """
        Predict how a content idea might perform.

        Args:
            idea: Content idea to evaluate

        Returns:
            Dict with prediction and reasoning
        """
        # Get recent patterns for context
        session = db.get_session()
        try:
            patterns = session.query(SuccessPattern).order_by(
                SuccessPattern.engagement_multiplier.desc()
            ).limit(10).all()
            patterns_data = [
                {"type": p.pattern_type, "value": p.pattern_value, "multiplier": p.engagement_multiplier}
                for p in patterns
            ]
        finally:
            session.close()

        prompt = f"""Predict the performance of this content idea for an Israeli content creator.

CONTENT IDEA:
{json.dumps(idea, indent=2, ensure_ascii=False)}

KNOWN SUCCESS PATTERNS:
{json.dumps(patterns_data, indent=2, ensure_ascii=False)}

CREATOR CONTEXT:
- Israeli musician
- Best content: Couple content (3x), Story times (2x), Trending (1.5x), Music (1.2x)
- Audience: Young Israelis 16-30

Predict performance:
{{
    "predicted_performance": "high/medium/low",
    "predicted_engagement_rate": X.X,
    "confidence": "high/medium/low",
    "matching_success_patterns": ["which patterns this idea matches"],
    "potential_risks": ["what could make it fail"],
    "optimization_suggestions": ["how to improve the idea"],
    "reasoning": "detailed explanation of prediction"
}}"""

        response = self.client.messages.create(
            model=config.ai.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )

        try:
            return json.loads(response.content[0].text)
        except json.JSONDecodeError:
            return {"raw_response": response.content[0].text}

    def _prepare_posts_data(self, posts: List[Post]) -> List[Dict]:
        """Prepare posts data for AI analysis."""
        return [
            {
                "platform": p.platform,
                "caption": p.caption[:500] if p.caption else "",  # Truncate long captions
                "hashtags": p.hashtags or [],
                "media_type": p.media_type,
                "duration_seconds": p.duration_seconds,
                "views": p.views,
                "likes": p.likes,
                "comments": p.comments,
                "shares": p.shares,
                "engagement_rate": round(p.engagement_rate or 0, 2),
                "category": p.category,
                "posted_at": p.posted_at.isoformat() if p.posted_at else None,
            }
            for p in posts
        ]

    def _get_category_distribution(self, posts_data: List[Dict]) -> Dict[str, int]:
        """Get distribution of posts by category."""
        distribution = {}
        for p in posts_data:
            cat = p.get("category", "uncategorized")
            distribution[cat] = distribution.get(cat, 0) + 1
        return distribution

    def _get_media_type_distribution(self, posts_data: List[Dict]) -> Dict[str, int]:
        """Get distribution of posts by media type."""
        distribution = {}
        for p in posts_data:
            mt = p.get("media_type", "unknown")
            distribution[mt] = distribution.get(mt, 0) + 1
        return distribution

    async def _store_patterns(self, patterns: List[Dict]):
        """Store discovered patterns in database."""
        session = db.get_session()
        try:
            for pattern in patterns:
                pattern_type = pattern.get("pattern_type", "unknown")
                pattern_value = pattern.get("pattern_value", pattern.get("pattern", ""))

                existing = session.query(SuccessPattern).filter_by(
                    pattern_type=pattern_type,
                    pattern_value=pattern_value
                ).first()

                if existing:
                    # Update existing pattern
                    existing.engagement_multiplier = pattern.get(
                        "engagement_multiplier",
                        existing.engagement_multiplier
                    )
                    existing.confidence = {"high": 0.9, "medium": 0.6, "low": 0.3}.get(
                        pattern.get("confidence", "medium"), 0.6
                    )
                    existing.last_validated = datetime.utcnow()
                else:
                    # Create new pattern
                    new_pattern = SuccessPattern(
                        pattern_type=pattern_type,
                        pattern_value=pattern_value,
                        engagement_multiplier=pattern.get("engagement_multiplier", 1.0),
                        confidence={"high": 0.9, "medium": 0.6, "low": 0.3}.get(
                            pattern.get("confidence", "medium"), 0.6
                        ),
                    )
                    session.add(new_pattern)

            session.commit()
        finally:
            session.close()
