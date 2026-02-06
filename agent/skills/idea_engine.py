"""
IdeaEngine Skill
================
AI-powered content idea generation using Claude.
Creates specific, actionable ideas based on patterns and trends.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging
import json
import random

from anthropic import Anthropic

from .base import BaseSkill
from ..config import config
from ..database import db, Idea, Post, SuccessPattern, Trend

logger = logging.getLogger(__name__)


class IdeaEngine(BaseSkill):
    """
    AI-powered content idea generation.

    CRITICAL: Ideas must ALWAYS be specific and actionable!
    Never generate vague ideas like "post something about relationships".
    """

    def __init__(self):
        super().__init__("IdeaEngine")
        self.client = Anthropic(api_key=config.ai.api_key) if config.ai.api_key else None

    async def execute(
        self,
        count: int = 3,
        category: str = None,
        use_trends: bool = True,
        urgency: str = None
    ) -> Dict[str, Any]:
        """
        Generate content ideas.

        Args:
            count: Number of ideas to generate
            category: Specific category to focus on (optional)
            use_trends: Whether to incorporate current trends
            urgency: 'immediate', 'today', 'this_week' - filters ideas by time sensitivity

        Returns:
            Dict with generated ideas
        """
        self.log_start()

        if not self.client:
            return {"error": "Anthropic client not configured"}

        results = {
            "ideas": [],
            "trends_incorporated": [],
            "patterns_used": [],
        }

        try:
            # Gather context
            context = await self._gather_context(use_trends)

            # Generate ideas
            ideas = await self._generate_ideas(
                count=count,
                category=category,
                context=context,
                urgency=urgency
            )

            # Validate and enrich ideas
            validated_ideas = []
            for idea in ideas:
                if self._validate_idea(idea):
                    enriched = await self._enrich_idea(idea, context)
                    validated_ideas.append(enriched)

            # Store ideas in database
            stored_ideas = await self._store_ideas(validated_ideas)

            results["ideas"] = stored_ideas
            results["trends_incorporated"] = context.get("active_trends", [])[:3]
            results["patterns_used"] = context.get("success_patterns", [])[:5]
            results["summary"] = f"Generated {len(stored_ideas)} specific, actionable ideas"

            self.log_complete(results)

        except Exception as e:
            self.log_error(e)
            results["error"] = str(e)

        return results

    async def _gather_context(self, use_trends: bool) -> Dict[str, Any]:
        """
        Gather context for idea generation.

        Args:
            use_trends: Whether to include trend data

        Returns:
            Context dictionary
        """
        context = {
            "success_patterns": [],
            "recent_posts": [],
            "active_trends": [],
            "creator_profile": {
                "name": config.creator.name,
                "girlfriend_name": config.creator.girlfriend_name,
                "top_categories": config.creator.top_categories,
                "brand_voice": config.creator.brand_voice,
            }
        }

        session = db.get_session()
        try:
            # Get success patterns
            patterns = session.query(SuccessPattern).order_by(
                SuccessPattern.engagement_multiplier.desc()
            ).limit(10).all()

            context["success_patterns"] = [
                {
                    "type": p.pattern_type,
                    "value": p.pattern_value,
                    "multiplier": p.engagement_multiplier,
                    "confidence": p.confidence,
                }
                for p in patterns
            ]

            # Get recent posts (to avoid repetition)
            recent = session.query(Post).order_by(
                Post.posted_at.desc()
            ).limit(10).all()

            context["recent_posts"] = [
                {"caption": p.caption[:200] if p.caption else "", "category": p.category}
                for p in recent
            ]

            # Get active trends
            if use_trends:
                trends = session.query(Trend).filter(
                    Trend.expires_at > datetime.utcnow(),
                    Trend.status.in_(["new", "notified"])
                ).order_by(Trend.relevance_score.desc()).limit(5).all()

                context["active_trends"] = [
                    {
                        "title": t.title,
                        "opportunity": t.content_opportunity,
                        "urgency": t.urgency,
                    }
                    for t in trends
                ]

        finally:
            session.close()

        return context

    async def _generate_ideas(
        self,
        count: int,
        category: str,
        context: Dict,
        urgency: str
    ) -> List[Dict]:
        """
        Generate ideas using Claude.

        Args:
            count: Number of ideas
            category: Category focus
            context: Context data
            urgency: Time sensitivity

        Returns:
            List of idea dictionaries
        """
        girlfriend_name = context["creator_profile"].get("girlfriend_name", "בת הזוג")

        # Build category weights based on performance
        category_info = """
CATEGORY PERFORMANCE (ranked by engagement):
1. COUPLE CONTENT (3x engagement) - תוכן עם {girlfriend_name}
   - ריאקשנים שלה, רגעים מתוקים, ריבים מטופשים, הפתעות, טיפים לזוגות
2. STORY TIMES (2x engagement) - סיפורים אישיים
   - מקרים מביכים, חוויות מטורפות, "לא תאמינו מה קרה לי"
3. TRENDING REACTIONS (1.5x engagement) - תגובות לאקטואליה
   - תוכניות טלויזיה, ויראלים, אירועים תרבותיים
4. MUSIC CONTENT (1.2x engagement) - תוכן מוזיקלי
   - מאחורי הקלעים, יצירת שירים, ריאקשנים למוזיקה
"""

        trending_section = ""
        if context["active_trends"]:
            trending_section = f"""

CURRENT TRENDS (consider incorporating):
{json.dumps(context['active_trends'], indent=2, ensure_ascii=False)}
"""

        avoid_section = ""
        if context["recent_posts"]:
            avoid_section = f"""

RECENTLY POSTED (avoid similar content):
{json.dumps([p['caption'][:100] for p in context['recent_posts']], ensure_ascii=False)}
"""

        prompt = f"""Generate {count} SPECIFIC content ideas for an Israeli content creator.

CREATOR PROFILE:
- Israeli musician and content creator
- Platform: TikTok/Instagram
- Language: Hebrew
- Lives with girlfriend ({girlfriend_name})
- Has home studio for music content
- Brand: Authentic, natural, relatable - NEVER pretentious

{category_info.format(girlfriend_name=girlfriend_name)}

SUCCESS PATTERNS LEARNED:
{json.dumps(context['success_patterns'], indent=2, ensure_ascii=False)}
{trending_section}
{avoid_section}

{"Focus on category: " + category if category else "Mix categories based on performance weights."}
{"Urgency: " + urgency + " - ideas must be time-sensitive" if urgency else ""}

CRITICAL REQUIREMENTS FOR EACH IDEA:
1. SPECIFIC hook/opening line (exact words to say)
2. Step-by-step execution guide
3. Exact duration recommendation
4. Specific hashtags
5. Best posting time
6. Clear reasoning why it will work (data-backed)

NEVER GENERATE VAGUE IDEAS LIKE:
❌ "תעלה משהו על זוגיות"
❌ "תעשה סטורי"
❌ "תגיב לטרנד"

ALWAYS BE SPECIFIC LIKE:
✅ Exact hook text to use
✅ Specific scenario description
✅ Step-by-step what to do

Return as JSON array:
[
  {{
    "title": "שם הרעיון בעברית",
    "hook": "המשפט הפותח המדויק - מה לומר בתחילת הסרטון",
    "description": "תיאור מפורט של מה לעשות",
    "steps": [
      "שלב 1: ...",
      "שלב 2: ...",
      "שלב 3: ..."
    ],
    "duration": "30-60 שניות",
    "category": "couple_content|story_times|trending_reactions|music_content",
    "hashtags": ["#hashtag1", "#hashtag2"],
    "best_time": "18:00-20:00",
    "predicted_performance": "high|medium",
    "based_on_pattern": "which success pattern this uses",
    "based_on_trend": "if inspired by current trend, which one",
    "why_it_works": "הסבר מפורט למה זה יעבוד, מבוסס על הדאטה"
  }}
]
"""

        response = self.client.messages.create(
            model=config.ai.model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )

        try:
            # Extract JSON from response
            response_text = response.content[0].text
            # Find JSON array in response
            start = response_text.find('[')
            end = response_text.rfind(']') + 1
            if start >= 0 and end > start:
                ideas = json.loads(response_text[start:end])
                return ideas
            return []
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse ideas JSON: {e}")
            return []

    def _validate_idea(self, idea: Dict) -> bool:
        """
        Validate that an idea meets quality standards.

        Args:
            idea: Idea to validate

        Returns:
            True if idea is valid and specific enough
        """
        # Must have essential fields
        required_fields = ["title", "hook", "description", "steps"]
        if not all(idea.get(f) for f in required_fields):
            logger.warning(f"Idea missing required fields: {idea.get('title', 'Unknown')}")
            return False

        # Hook must be specific (at least 10 characters)
        if len(idea.get("hook", "")) < 10:
            logger.warning(f"Idea hook too vague: {idea.get('title', 'Unknown')}")
            return False

        # Must have at least 2 steps
        if len(idea.get("steps", [])) < 2:
            logger.warning(f"Idea has too few steps: {idea.get('title', 'Unknown')}")
            return False

        # Description must be detailed (at least 50 characters)
        if len(idea.get("description", "")) < 50:
            logger.warning(f"Idea description too short: {idea.get('title', 'Unknown')}")
            return False

        return True

    async def _enrich_idea(self, idea: Dict, context: Dict) -> Dict:
        """
        Enrich idea with additional details.

        Args:
            idea: Validated idea
            context: Context data

        Returns:
            Enriched idea
        """
        # Set defaults if missing
        idea.setdefault("duration", "30-60 שניות")
        idea.setdefault("hashtags", ["#ישראל", "#תוכןישראלי", "#טיקטוק"])
        idea.setdefault("best_time", "18:00-20:00")
        idea.setdefault("predicted_performance", "medium")

        # Calculate confidence score based on pattern matching
        confidence = 0.5  # Base confidence
        if idea.get("based_on_pattern"):
            confidence += 0.2
        if idea.get("based_on_trend"):
            confidence += 0.1
        if idea.get("category") == "couple_content":
            confidence += 0.15
        elif idea.get("category") == "story_times":
            confidence += 0.1

        idea["confidence_score"] = min(confidence, 0.95)

        # Add predicted engagement based on category
        category_multipliers = {
            "couple_content": 3.0,
            "story_times": 2.0,
            "trending_reactions": 1.5,
            "music_content": 1.2,
        }
        multiplier = category_multipliers.get(idea.get("category"), 1.0)
        idea["predicted_engagement_multiplier"] = multiplier

        return idea

    async def _store_ideas(self, ideas: List[Dict]) -> List[Dict]:
        """
        Store ideas in database.

        Args:
            ideas: List of validated and enriched ideas

        Returns:
            Ideas with database IDs
        """
        session = db.get_session()
        stored = []

        try:
            for idea in ideas:
                new_idea = Idea(
                    title=idea["title"],
                    hook=idea.get("hook"),
                    description=idea["description"],
                    steps=idea.get("steps"),
                    duration_recommendation=idea.get("duration"),
                    hashtags=idea.get("hashtags"),
                    best_time=idea.get("best_time"),
                    category=idea.get("category"),
                    based_on_trend=idea.get("based_on_trend"),
                    based_on_pattern=idea.get("based_on_pattern"),
                    predicted_performance=idea.get("predicted_performance"),
                    predicted_engagement=idea.get("predicted_engagement_multiplier"),
                    confidence_score=idea.get("confidence_score"),
                    reasoning=idea.get("why_it_works"),
                    status="generated",
                )
                session.add(new_idea)
                session.flush()  # Get the ID

                idea["id"] = new_idea.id
                stored.append(idea)

            session.commit()
        finally:
            session.close()

        return stored

    async def get_todays_ideas(self, count: int = 3) -> List[Dict]:
        """
        Get or generate ideas for today.

        Args:
            count: Number of ideas to return

        Returns:
            List of ideas for today
        """
        session = db.get_session()
        try:
            # Check if we have unused ideas from today
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

            existing = session.query(Idea).filter(
                Idea.created_at >= today_start,
                Idea.status.in_(["generated", "sent"])
            ).order_by(Idea.confidence_score.desc()).limit(count).all()

            if len(existing) >= count:
                return [
                    {
                        "id": i.id,
                        "title": i.title,
                        "hook": i.hook,
                        "description": i.description,
                        "steps": i.steps,
                        "category": i.category,
                        "predicted_performance": i.predicted_performance,
                    }
                    for i in existing
                ]

        finally:
            session.close()

        # Generate new ideas if needed
        result = await self.execute(count=count)
        return result.get("ideas", [])

    async def mark_idea_sent(self, idea_id: int):
        """Mark an idea as sent to creator."""
        session = db.get_session()
        try:
            idea = session.query(Idea).filter_by(id=idea_id).first()
            if idea:
                idea.status = "sent"
                idea.sent_at = datetime.utcnow()
                session.commit()
        finally:
            session.close()

    async def mark_idea_used(self, idea_id: int, post_id: int = None):
        """Mark an idea as used by creator."""
        session = db.get_session()
        try:
            idea = session.query(Idea).filter_by(id=idea_id).first()
            if idea:
                idea.status = "used"
                idea.used_at = datetime.utcnow()
                if post_id:
                    idea.resulting_post_id = post_id
                session.commit()
        finally:
            session.close()

    async def record_feedback(self, idea_id: int, rating: int = None, feedback: str = None):
        """
        Record creator feedback on an idea.

        Args:
            idea_id: ID of the idea
            rating: 1-5 rating
            feedback: Text feedback
        """
        session = db.get_session()
        try:
            idea = session.query(Idea).filter_by(id=idea_id).first()
            if idea:
                if rating:
                    idea.creator_rating = rating
                if feedback:
                    idea.creator_feedback = feedback
                session.commit()
        finally:
            session.close()

    async def generate_quick_idea(self, context: str = None) -> Dict:
        """
        Generate a single quick idea for immediate use.
        For example, when a breaking trend is detected.

        Args:
            context: Optional context (e.g., trend description)

        Returns:
            Single idea dictionary
        """
        result = await self.execute(count=1, urgency="immediate")
        ideas = result.get("ideas", [])
        return ideas[0] if ideas else {}
