"""
CoreAgent - Content Master Agent
================================
Central orchestrator that coordinates all skills.
The brain of the operation.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .config import config
from .database import db, Post, Idea, Trend
from .skills import (
    ProfileScanner,
    DeepAnalyzer,
    TrendRadar,
    IdeaEngine,
    MessageCrafter,
    MemoryCore,
    FeedbackLearner,
)
from .integrations.whatsapp import whatsapp

logger = logging.getLogger(__name__)


class ContentMasterAgent:
    """
    The Content Master Agent - central orchestrator.

    Responsibilities:
    - Coordinate all skills
    - Generate daily action plans
    - Route tasks to appropriate skills
    - Synthesize insights from all sources
    - Track goals and progress
    """

    def __init__(self):
        # Initialize skills
        self.profile_scanner = ProfileScanner()
        self.deep_analyzer = DeepAnalyzer()
        self.trend_radar = TrendRadar()
        self.idea_engine = IdeaEngine()
        self.message_crafter = MessageCrafter()
        self.memory_core = MemoryCore()
        self.feedback_learner = FeedbackLearner()

        # State
        self.last_scan_time: Optional[datetime] = None
        self.last_analysis_time: Optional[datetime] = None
        self.daily_ideas: List[Dict] = []

        logger.info("Content Master Agent initialized")

    async def initialize(self):
        """Initialize the agent and database."""
        logger.info("Initializing agent...")

        # Create database tables
        db.create_tables()
        logger.info("Database initialized")

        # Load context
        context = await self.memory_core.execute(operation="get_context")
        logger.info(f"Context loaded: {context.get('summary', 'OK')}")

        return True

    # ========================
    # Daily Routines
    # ========================

    async def morning_routine(self):
        """
        Morning routine (run at 6:00 AM).
        - Full profile scan
        - Deep analysis
        - Generate today's ideas
        """
        logger.info("Starting morning routine...")

        # 1. Full profile scan
        scan_result = await self.profile_scanner.execute(full_scan=True)
        logger.info(f"Scan complete: {scan_result.get('summary', '')}")

        # 2. Deep analysis if we have enough new data
        if scan_result.get("new_posts", 0) > 0 or scan_result.get("updated_posts", 0) > 5:
            analysis_result = await self.deep_analyzer.execute(analysis_type="comprehensive")
            logger.info(f"Analysis complete: {analysis_result.get('summary', '')}")

        # 3. Check trends
        trend_result = await self.trend_radar.execute()
        logger.info(f"Trends: {trend_result.get('summary', '')}")

        # 4. Generate today's ideas
        ideas_result = await self.idea_engine.execute(count=5)
        self.daily_ideas = ideas_result.get("ideas", [])
        logger.info(f"Ideas: {ideas_result.get('summary', '')}")

        # 5. Learning cycle
        learn_result = await self.feedback_learner.execute(operation="learn_from_recent")
        logger.info(f"Learning: {learn_result.get('summary', '')}")

        self.last_scan_time = datetime.utcnow()
        self.last_analysis_time = datetime.utcnow()

        return {
            "scan": scan_result,
            "analysis": analysis_result if scan_result.get("new_posts", 0) > 0 else None,
            "trends": trend_result,
            "ideas": ideas_result,
            "learning": learn_result,
        }

    async def send_morning_message(self):
        """
        Send morning motivation message (9:00 AM).
        """
        logger.info("Preparing morning message...")

        # Get today's ideas
        if not self.daily_ideas:
            ideas_result = await self.idea_engine.get_todays_ideas(count=3)
            self.daily_ideas = ideas_result

        # Get active trends
        trends = await self.trend_radar.get_active_trends(limit=3)
        trend_data = [{"title": t.title, "opportunity": t.content_opportunity} for t in trends]

        # Craft message
        message_result = await self.message_crafter.execute(
            message_type="morning",
            ideas=self.daily_ideas[:2],
            trends=trend_data
        )

        message = message_result.get("message", "")

        if message:
            # Send via WhatsApp
            sid = whatsapp.send_message(message)

            # Store message
            await self.message_crafter.store_message(
                message=message,
                message_type="morning",
                idea_ids=[i.get("id") for i in self.daily_ideas[:2] if i.get("id")],
                twilio_sid=sid
            )

            # Mark ideas as sent
            for idea in self.daily_ideas[:2]:
                if idea.get("id"):
                    await self.idea_engine.mark_idea_sent(idea["id"])

            logger.info("Morning message sent")

        return {"message": message, "sent": bool(message)}

    async def send_midday_message(self):
        """
        Send midday trend update (1:00 PM).
        Only sends if there are urgent trends.
        """
        logger.info("Checking for midday message...")

        # Check for urgent trends
        urgent_trends = await self.trend_radar.check_breaking_trends()

        if not urgent_trends:
            logger.info("No urgent trends, skipping midday message")
            return {"sent": False, "reason": "No urgent trends"}

        trend_data = [
            {"title": t.get("title"), "opportunity": t.get("content_opportunity"), "urgency": t.get("urgency")}
            for t in urgent_trends
        ]

        # Craft message
        message = await self.message_crafter.craft_midday_message(trend_data)

        if message:
            sid = whatsapp.send_message(message)

            await self.message_crafter.store_message(
                message=message,
                message_type="midday",
                twilio_sid=sid
            )

            logger.info("Midday message sent")

        return {"message": message, "sent": bool(message)}

    async def send_afternoon_message(self):
        """
        Send afternoon reminder (5:00 PM).
        """
        logger.info("Preparing afternoon message...")

        # Get quick/easy ideas
        quick_ideas = [
            i for i in self.daily_ideas
            if i.get("category") in ["story_times", "couple_content"]
        ][:1]

        if not quick_ideas:
            quick_ideas = [{"title": "סטורי מהיר", "hook": "עדכון קצר או שאלה לעוקבים"}]

        message = await self.message_crafter.craft_afternoon_message(quick_ideas)

        if message:
            sid = whatsapp.send_message(message)

            await self.message_crafter.store_message(
                message=message,
                message_type="afternoon",
                twilio_sid=sid
            )

            logger.info("Afternoon message sent")

        return {"message": message, "sent": bool(message)}

    async def send_evening_message(self):
        """
        Send evening summary (9:00 PM).
        """
        logger.info("Preparing evening message...")

        # Get today's performance
        stats = await self.memory_core.execute(operation="get_stats", days=1)
        performance_data = {
            "posts_today": stats.get("total_posts", 0),
            "views_today": stats.get("total_views", 0),
            "engagement_trend": stats.get("trend", "stable"),
        }

        # Generate tomorrow's main idea
        tomorrow_ideas = await self.idea_engine.execute(count=2)

        message = await self.message_crafter.craft_evening_message(
            performance_data=performance_data,
            tomorrow_ideas=tomorrow_ideas.get("ideas", [])
        )

        if message:
            sid = whatsapp.send_message(message)

            await self.message_crafter.store_message(
                message=message,
                message_type="evening",
                twilio_sid=sid
            )

            # Generate daily report
            await self.memory_core.execute(operation="daily_report")

            logger.info("Evening message sent")

        return {"message": message, "sent": bool(message)}

    # ========================
    # Quick Updates
    # ========================

    async def quick_update(self):
        """
        Quick update routine (every 6 hours).
        - Quick profile scan
        - Check for breaking trends
        """
        logger.info("Running quick update...")

        # Quick scan
        scan_result = await self.profile_scanner.execute(
            full_scan=False,
            max_posts=20
        )

        # Check trends
        trend_result = await self.trend_radar.execute(max_trends=10)

        # Alert if breaking trend found
        breaking_trends = [
            t for t in trend_result.get("relevant_trends", [])
            if t.get("urgency") == "immediate"
        ]

        if breaking_trends:
            logger.info(f"Breaking trend detected: {breaking_trends[0].get('title')}")
            alert = await self.message_crafter.craft_trend_alert(breaking_trends[0])
            whatsapp.send_message(alert)

        return {
            "scan": scan_result,
            "trends": trend_result,
            "breaking_alert_sent": bool(breaking_trends)
        }

    # ========================
    # On-Demand Operations
    # ========================

    async def generate_ideas(self, count: int = 3, category: str = None) -> List[Dict]:
        """
        Generate content ideas on demand.

        Args:
            count: Number of ideas
            category: Optional category focus

        Returns:
            List of ideas
        """
        result = await self.idea_engine.execute(count=count, category=category)
        return result.get("ideas", [])

    async def analyze_performance(self, days: int = 30) -> Dict:
        """
        Analyze content performance.

        Args:
            days: Number of days to analyze

        Returns:
            Performance analysis
        """
        stats = await self.memory_core.execute(operation="get_stats", days=days)
        patterns = await self.memory_core.execute(operation="get_patterns")

        return {
            "stats": stats,
            "patterns": patterns,
        }

    async def get_current_trends(self) -> List[Dict]:
        """
        Get current relevant trends.

        Returns:
            List of trends
        """
        trends = await self.trend_radar.get_active_trends(limit=10)
        return [
            {
                "title": t.title,
                "opportunity": t.content_opportunity,
                "urgency": t.urgency,
                "score": t.relevance_score,
            }
            for t in trends
        ]

    async def record_feedback(
        self,
        idea_id: int,
        rating: int = None,
        feedback: str = None,
        was_helpful: bool = None
    ):
        """
        Record feedback on an idea.

        Args:
            idea_id: ID of the idea
            rating: 1-5 rating
            feedback: Text feedback
            was_helpful: Whether it was helpful
        """
        await self.feedback_learner.process_explicit_feedback(
            idea_id=idea_id,
            rating=rating,
            feedback=feedback,
            was_helpful=was_helpful
        )

    async def get_learning_summary(self) -> Dict:
        """Get summary of what the agent has learned."""
        return await self.feedback_learner.get_learning_summary()

    async def send_custom_message(self, message: str):
        """
        Send a custom WhatsApp message.

        Args:
            message: Message to send
        """
        return whatsapp.send_message(message)

    # ========================
    # Status & Health
    # ========================

    async def get_status(self) -> Dict:
        """Get agent status and health."""
        recent_activity = await self.memory_core.get_recent_activity(hours=24)

        return {
            "status": "running",
            "last_scan": self.last_scan_time.isoformat() if self.last_scan_time else None,
            "last_analysis": self.last_analysis_time.isoformat() if self.last_analysis_time else None,
            "daily_ideas_count": len(self.daily_ideas),
            "recent_activity": recent_activity,
            "whatsapp_configured": whatsapp.is_configured(),
            "skills_status": {
                "profile_scanner": self.profile_scanner.get_stats(),
                "deep_analyzer": self.deep_analyzer.get_stats(),
                "trend_radar": self.trend_radar.get_stats(),
                "idea_engine": self.idea_engine.get_stats(),
                "message_crafter": self.message_crafter.get_stats(),
            }
        }


# Global agent instance
agent = ContentMasterAgent()
