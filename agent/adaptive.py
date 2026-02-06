"""
AdaptiveCommunication
=====================
Adapts how the agent communicates based on user behavior and preferences.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from collections import Counter

from .database import db, Message, Conversation

logger = logging.getLogger(__name__)


class AdaptiveCommunication:
    """
    Adapts communication style based on user behavior.

    Learns:
    - When user is most responsive
    - What message types get responses
    - Preferred message length
    - Response patterns
    """

    def __init__(self, memory):
        self.memory = memory

        # Response tracking
        self.message_responses = {}  # message_type -> {sent: int, responded: int}

    async def analyze_user_response_pattern(self):
        """
        Learn how user responds to different message types.
        Run daily at 3:00 AM.
        """
        logger.info("Analyzing user response patterns...")

        session = db.get_session()
        try:
            # Get sent messages from last 30 days
            cutoff = datetime.utcnow() - timedelta(days=30)

            messages = session.query(Message).filter(
                Message.sent_at >= cutoff
            ).all()

            # Get incoming responses
            responses = session.query(Conversation).filter(
                Conversation.direction == "incoming",
                Conversation.created_at >= cutoff
            ).all()

            # Analyze by message type
            type_stats = {}
            for msg in messages:
                msg_type = msg.message_type
                if msg_type not in type_stats:
                    type_stats[msg_type] = {"sent": 0, "responded": 0}

                type_stats[msg_type]["sent"] += 1

                # Check if there was a response within 2 hours
                response_window = msg.sent_at + timedelta(hours=2)
                had_response = any(
                    r for r in responses
                    if msg.sent_at <= r.created_at <= response_window
                )
                if had_response:
                    type_stats[msg_type]["responded"] += 1

            # Calculate and store response rates
            for msg_type, stats in type_stats.items():
                rate = stats["responded"] / stats["sent"] if stats["sent"] > 0 else 0
                self.memory.remember(
                    "communication",
                    f"{msg_type}_response_rate",
                    rate,
                    confidence=min(0.9, stats["sent"] / 10)  # Higher confidence with more data
                )

            # Analyze by hour
            response_by_hour = Counter()
            for resp in responses:
                response_by_hour[resp.created_at.hour] += 1

            if response_by_hour:
                best_hour = response_by_hour.most_common(1)[0][0]
                self.memory.remember("communication", "best_response_hour", best_hour)

            # Analyze message length preference
            await self._analyze_length_preference(session, messages, responses)

            logger.info(f"Response pattern analysis complete: {len(type_stats)} message types analyzed")

        except Exception as e:
            logger.error(f"Response pattern analysis error: {e}")
        finally:
            session.close()

    async def _analyze_length_preference(self, session, messages: List, responses: List):
        """Analyze if user prefers shorter or longer messages."""
        short_messages = []  # < 200 chars
        long_messages = []   # >= 200 chars

        for msg in messages:
            if not msg.content:
                continue

            # Check if got response within 2 hours
            response_window = msg.sent_at + timedelta(hours=2)
            had_response = any(
                r for r in responses
                if msg.sent_at <= r.created_at <= response_window
            )

            if len(msg.content) < 200:
                short_messages.append(had_response)
            else:
                long_messages.append(had_response)

        # Calculate rates
        short_rate = sum(short_messages) / len(short_messages) if short_messages else 0
        long_rate = sum(long_messages) / len(long_messages) if long_messages else 0

        self.memory.remember("communication", "short_message_response_rate", short_rate)
        self.memory.remember("communication", "long_message_response_rate", long_rate)

        # Determine preference
        prefers_short = short_rate > long_rate * 1.3  # 30% better
        self.memory.remember("communication", "prefers_short_messages", prefers_short)

    def get_best_message_time(self) -> int:
        """Get the best hour to send messages."""
        best_hour = self.memory.recall("communication", "best_response_hour")
        return best_hour if best_hour is not None else 19  # Default 7 PM

    def should_simplify_message(self) -> bool:
        """Check if user prefers shorter messages."""
        return self.memory.recall("communication", "prefers_short_messages") or False

    def get_message_type_effectiveness(self) -> Dict[str, float]:
        """Get effectiveness (response rate) of each message type."""
        effectiveness = {}

        message_types = ["morning", "midday", "afternoon", "evening", "trend_alert", "idea", "reminder"]

        for msg_type in message_types:
            rate = self.memory.recall("communication", f"{msg_type}_response_rate")
            if rate is not None:
                effectiveness[msg_type] = rate

        return effectiveness

    def get_best_message_types(self) -> List[str]:
        """Get message types that get best responses."""
        effectiveness = self.get_message_type_effectiveness()

        if not effectiveness:
            return []

        # Sort by effectiveness and return top performers
        sorted_types = sorted(effectiveness.items(), key=lambda x: x[1], reverse=True)
        return [t[0] for t in sorted_types if t[1] > 0.3]  # At least 30% response rate

    def should_send_now(self) -> bool:
        """Check if now is a good time to send a message."""
        current_hour = datetime.now().hour
        best_hour = self.get_best_message_time()

        # Within 2 hours of best time is good
        return abs(current_hour - best_hour) <= 2

    def adapt_message_length(self, message: str) -> str:
        """Adapt message length based on user preference."""
        if not self.should_simplify_message():
            return message

        # If user prefers short, truncate if too long
        if len(message) > 300:
            # Try to find a good break point
            lines = message.split("\n")
            shortened = []
            length = 0

            for line in lines:
                if length + len(line) > 250:
                    break
                shortened.append(line)
                length += len(line)

            if shortened:
                return "\n".join(shortened) + "\n\n..."

        return message

    def get_communication_insights(self) -> Dict[str, Any]:
        """Get insights about communication patterns."""
        return {
            "best_time": self.get_best_message_time(),
            "prefers_short": self.should_simplify_message(),
            "effective_types": self.get_best_message_types(),
            "response_rate": self.memory.get_response_rate(),
        }

    def suggest_message_improvements(self) -> List[str]:
        """Suggest improvements based on analysis."""
        suggestions = []

        effectiveness = self.get_message_type_effectiveness()

        # Find underperforming message types
        for msg_type, rate in effectiveness.items():
            if rate < 0.2:
                if msg_type == "morning":
                    suggestions.append("הודעות בוקר לא מקבלות תגובה - נסה שעה מאוחרת יותר")
                elif msg_type == "reminder":
                    suggestions.append("תזכורות לא עובדות טוב - נסה להיות פחות ישיר")
                elif msg_type == "evening":
                    suggestions.append("הודעות ערב לא עובדות - אולי שעה מוקדמת יותר?")

        if self.should_simplify_message():
            suggestions.append("המשתמש מעדיף הודעות קצרות - תקצר!")

        best_hour = self.get_best_message_time()
        suggestions.append(f"הזמן הכי טוב לשלוח הודעות: {best_hour}:00")

        return suggestions

    async def track_message_sent(self, message_type: str, message_length: int):
        """Track when a message is sent."""
        if message_type not in self.message_responses:
            self.message_responses[message_type] = {"sent": 0, "responded": 0, "lengths": []}

        self.message_responses[message_type]["sent"] += 1
        self.message_responses[message_type]["lengths"].append(message_length)

    async def track_user_response(self, hours_since_message: float = None):
        """Track when user responds."""
        # Find most recent message type sent
        session = db.get_session()
        try:
            recent_msg = session.query(Message).order_by(
                Message.sent_at.desc()
            ).first()

            if recent_msg and recent_msg.message_type in self.message_responses:
                self.message_responses[recent_msg.message_type]["responded"] += 1

        except Exception as e:
            logger.error(f"Error tracking response: {e}")
        finally:
            session.close()
