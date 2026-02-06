"""
AutonomousAgent
===============
Main autonomous agent class that ties everything together.
The agent that thinks, decides, and acts on its own.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
import pytz

from .brain import AgentBrain
from .goals import GoalTracker
from .memory import MemorySystem
from .personality import PersonalityEngine
from .proactive import ProactiveAgent
from .adaptive import AdaptiveCommunication

logger = logging.getLogger(__name__)

ISRAEL_TZ = pytz.timezone("Asia/Jerusalem")


class AutonomousAgent:
    """
    Main autonomous agent that manages all components.

    This agent:
    - OBSERVES: Constantly monitors everything
    - THINKS: Analyzes and makes decisions
    - ACTS: Takes actions without being asked
    - LEARNS: Improves from every interaction

    Components:
    - Brain: Central decision maker
    - Goals: Track and pursue goals
    - Memory: Remember everything
    - Personality: Consistent character
    - Proactive: Take automatic actions
    - Adaptive: Learn communication preferences
    """

    _instance = None

    def __new__(cls):
        """Singleton pattern - only one agent instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        logger.info("Initializing Autonomous Agent...")

        # Initialize components
        self.memory = MemorySystem()
        self.goals = GoalTracker()
        self.personality = PersonalityEngine()

        # Brain needs other components
        self.brain = AgentBrain(self.memory, self.goals, self.personality)

        # Proactive agent for scheduled actions
        self.proactive = ProactiveAgent(self.brain, self.memory, self.goals, self.personality)

        # Adaptive communication
        self.adaptive = AdaptiveCommunication(self.memory)

        # State tracking
        self.is_running = False
        self.last_think_time = None
        self.think_interval_minutes = 30

        self._initialized = True
        logger.info("Autonomous Agent initialized")

    async def start(self):
        """Start the autonomous agent."""
        logger.info("Starting Autonomous Agent...")
        self.is_running = True

        # Initial think cycle
        await self.brain.think()
        self.last_think_time = datetime.now(ISRAEL_TZ)

        logger.info("Autonomous Agent started - thinking every 30 minutes")

    async def stop(self):
        """Stop the autonomous agent."""
        logger.info("Stopping Autonomous Agent...")
        self.is_running = False

    async def think_cycle(self):
        """
        Run a thinking cycle.
        Called by the scheduler every 30 minutes.
        """
        if not self.is_running:
            logger.warning("Think cycle called but agent not running")
            return

        logger.info("Running think cycle...")
        result = await self.brain.think()
        self.last_think_time = datetime.now(ISRAEL_TZ)

        return result

    async def morning_routine(self):
        """
        Morning routine - called at 8:00 AM.
        """
        logger.info("Running morning routine...")
        return await self.proactive.morning_routine()

    async def opportunity_scan(self):
        """
        Opportunity scan - called every 30 minutes.
        """
        logger.info("Running opportunity scan...")
        return await self.proactive.opportunity_scanner()

    async def evening_reflection(self):
        """
        Evening reflection - called at 22:00.
        """
        logger.info("Running evening reflection...")
        return await self.proactive.end_of_day_reflection()

    async def weekly_strategy(self):
        """
        Weekly strategy - called Sunday at 10:00.
        """
        logger.info("Running weekly strategy...")
        return await self.proactive.weekly_strategy_session()

    async def learn_patterns(self):
        """
        Learn from communication patterns - called daily at 3:00 AM.
        """
        logger.info("Learning communication patterns...")
        await self.adaptive.analyze_user_response_pattern()

    def on_user_message(self, message: str):
        """
        Called when user sends a message.
        Updates agent state and learns from interaction.
        """
        # Reset unanswered counter
        self.brain.on_user_response()

        # Track response for learning
        asyncio.create_task(self.adaptive.track_user_response())

        # Learn from message content
        self._learn_from_message(message)

    def _learn_from_message(self, message: str):
        """Learn from user message content."""
        message_lower = message.lower()

        # Detect mood indicators
        positive_words = ["תודה", "אחלה", "מעולה", "טוב", "אהבתי", "יפה"]
        negative_words = ["לא", "גרוע", "מתסכל", "בעיה"]

        positive_count = sum(1 for w in positive_words if w in message_lower)
        negative_count = sum(1 for w in negative_words if w in message_lower)

        if positive_count > negative_count:
            self.memory.learn_pattern("user_mood", {"mood": "positive", "hour": datetime.now().hour})
        elif negative_count > positive_count:
            self.memory.learn_pattern("user_mood", {"mood": "negative", "hour": datetime.now().hour})

    def reset_daily(self):
        """
        Reset daily counters - called at midnight.
        """
        logger.info("Resetting daily counters...")
        self.brain.reset_daily_counters()

    def reset_weekly(self):
        """
        Reset weekly counters - called Sunday midnight.
        """
        logger.info("Resetting weekly counters...")
        self.goals.reset_weekly()

    def get_status(self) -> Dict[str, Any]:
        """Get current agent status."""
        return {
            "is_running": self.is_running,
            "last_think_time": self.last_think_time.isoformat() if self.last_think_time else None,
            "messages_sent_today": self.brain.messages_sent_today,
            "unanswered_messages": self.brain.unanswered_messages,
            "goals": self.goals.evaluate_progress(),
            "communication_insights": self.adaptive.get_communication_insights(),
        }

    def get_user_profile(self) -> str:
        """Get the learned user profile."""
        return self.memory.get_user_profile()

    def get_communication_suggestions(self) -> list:
        """Get suggestions for improving communication."""
        return self.adaptive.suggest_message_improvements()

    async def force_action(self, action: str, content: str = None) -> bool:
        """
        Force a specific action (for testing or manual override).

        Args:
            action: Action to take (SEND_IDEA, SEND_TREND_ALERT, etc.)
            content: Optional content for the action

        Returns:
            True if action was executed
        """
        decision = {
            "action": action,
            "content": content,
            "urgency": "high",
            "reason": "manual_override",
        }

        return await self.brain._execute_action(decision)


# Global autonomous agent instance
autonomous_agent = AutonomousAgent()
