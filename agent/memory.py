"""
MemorySystem
============
Long-term memory that learns and remembers everything about the user.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from collections import Counter
import json

from .database import db, UserPreference, Conversation, Post, Message

logger = logging.getLogger(__name__)


class MemorySystem:
    """
    Long-term memory that learns and remembers.

    Categories:
    - facts: Things we know about the user
    - patterns: Behavioral patterns we've learned
    - preferences: What they like/dislike
    - actions: History of agent actions
    """

    def __init__(self):
        self.facts = {}
        self.patterns = {}
        self.preferences = {}
        self.actions = []

        # Load from database
        self._load_from_database()

    def _load_from_database(self):
        """Load existing memories from database."""
        session = db.get_session()
        try:
            # Load preferences
            prefs = session.query(UserPreference).all()
            for pref in prefs:
                self.preferences[pref.value] = {
                    "type": pref.preference_type,
                    "strength": pref.strength,
                    "mention_count": pref.mention_count,
                    "last_mentioned": pref.last_mentioned,
                }

            # Analyze conversations for patterns
            self._analyze_conversation_patterns(session)

            # Analyze posting patterns
            self._analyze_posting_patterns(session)

        except Exception as e:
            logger.error(f"Error loading memories: {e}")
        finally:
            session.close()

    def _analyze_conversation_patterns(self, session):
        """Analyze conversation history for patterns."""
        try:
            # Get recent conversations
            convos = session.query(Conversation).filter(
                Conversation.created_at >= datetime.utcnow() - timedelta(days=30)
            ).all()

            if not convos:
                return

            # Analyze response times
            incoming = [c for c in convos if c.direction == "incoming"]
            response_hours = [c.created_at.hour for c in incoming]

            if response_hours:
                # Most common response hour
                common_hour = Counter(response_hours).most_common(1)[0][0]
                self.remember("behavior", "most_active_hour", common_hour)

            # Analyze message lengths
            msg_lengths = [len(c.content) for c in incoming if c.content]
            if msg_lengths:
                avg_length = sum(msg_lengths) / len(msg_lengths)
                prefers_short = avg_length < 50
                self.remember("communication", "prefers_short_messages", prefers_short)

        except Exception as e:
            logger.error(f"Error analyzing conversations: {e}")

    def _analyze_posting_patterns(self, session):
        """Analyze posting patterns."""
        try:
            posts = session.query(Post).filter(
                Post.posted_at >= datetime.utcnow() - timedelta(days=60)
            ).all()

            if not posts:
                return

            # Posting hours
            posting_hours = [p.posted_at.hour for p in posts if p.posted_at]
            if posting_hours:
                common_hour = Counter(posting_hours).most_common(1)[0][0]
                self.remember("behavior", "preferred_posting_hour", common_hour)

            # Posting days
            posting_days = [p.posted_at.strftime("%A") for p in posts if p.posted_at]
            if posting_days:
                common_day = Counter(posting_days).most_common(1)[0][0]
                self.remember("behavior", "preferred_posting_day", common_day)

            # Average views
            views = [p.views for p in posts if p.views]
            if views:
                avg_views = sum(views) / len(views)
                self.remember("performance", "avg_views", avg_views)

            # Best performing content type
            by_category = {}
            for post in posts:
                cat = post.category or "other"
                if cat not in by_category:
                    by_category[cat] = []
                by_category[cat].append(post.views or 0)

            if by_category:
                best_category = max(
                    by_category.keys(),
                    key=lambda k: sum(by_category[k]) / len(by_category[k]) if by_category[k] else 0
                )
                self.remember("performance", "best_content_type", best_category)

        except Exception as e:
            logger.error(f"Error analyzing posting patterns: {e}")

    def remember(self, category: str, key: str, value: Any, confidence: float = 0.8):
        """Store a memory."""
        if category not in self.facts:
            self.facts[category] = {}

        self.facts[category][key] = {
            "value": value,
            "timestamp": datetime.utcnow(),
            "confidence": confidence,
        }

        logger.debug(f"Remembered: {category}.{key} = {value}")

    def recall(self, category: str, key: str = None) -> Any:
        """Retrieve a memory."""
        if key:
            cat_data = self.facts.get(category, {})
            memory = cat_data.get(key)
            return memory.get("value") if memory else None
        else:
            return self.facts.get(category, {})

    def learn_pattern(self, pattern_type: str, data: Dict):
        """Learn a behavioral pattern."""
        if pattern_type not in self.patterns:
            self.patterns[pattern_type] = []

        self.patterns[pattern_type].append({
            **data,
            "timestamp": datetime.utcnow(),
        })

        # Analyze pattern if we have enough data
        if len(self.patterns[pattern_type]) >= 5:
            self._analyze_pattern(pattern_type)

    def _analyze_pattern(self, pattern_type: str):
        """Analyze and extract insights from pattern data."""
        data = self.patterns[pattern_type]

        if pattern_type == "response_time":
            # Average response time
            times = [d.get("response_minutes", 0) for d in data]
            avg_time = sum(times) / len(times) if times else 0
            self.remember("behavior", "avg_response_time_minutes", avg_time)

        elif pattern_type == "posting_time":
            # Preferred posting hour
            hours = [d.get("hour", 0) for d in data]
            common_hour = Counter(hours).most_common(1)[0][0] if hours else 18
            self.remember("behavior", "preferred_posting_hour", common_hour)

    def record_action(self, action: str, hour: int, day: str, context_type: str):
        """Record an agent action for learning."""
        self.actions.append({
            "action": action,
            "hour": hour,
            "day": day,
            "context_type": context_type,
            "timestamp": datetime.utcnow(),
        })

        # Keep only last 100 actions
        if len(self.actions) > 100:
            self.actions = self.actions[-100:]

    def get_estimated_mood(self) -> str:
        """Estimate user's likely mood based on patterns."""
        # Check last interaction
        session = db.get_session()
        try:
            last_convo = session.query(Conversation).filter(
                Conversation.direction == "incoming"
            ).order_by(Conversation.created_at.desc()).first()

            if not last_convo:
                return "unknown"

            # Analyze last message sentiment (simple version)
            content = last_convo.content.lower() if last_convo.content else ""

            positive_words = ["תודה", "אחלה", "מעולה", "טוב", "אהבתי", "יפה", "כיף"]
            negative_words = ["לא", "גרוע", "בעיה", "קשה", "מתסכל"]

            positive_count = sum(1 for word in positive_words if word in content)
            negative_count = sum(1 for word in negative_words if word in content)

            if positive_count > negative_count:
                return "positive"
            elif negative_count > positive_count:
                return "frustrated"
            else:
                return "neutral"

        except Exception as e:
            logger.error(f"Error estimating mood: {e}")
            return "unknown"
        finally:
            session.close()

    def get_response_rate(self) -> float:
        """Calculate user's response rate to agent messages."""
        session = db.get_session()
        try:
            # Count outgoing messages
            outgoing = session.query(Message).filter(
                Message.sent_at >= datetime.utcnow() - timedelta(days=7)
            ).count()

            # Count incoming responses
            incoming = session.query(Conversation).filter(
                Conversation.direction == "incoming",
                Conversation.created_at >= datetime.utcnow() - timedelta(days=7)
            ).count()

            if outgoing == 0:
                return 0.5  # Default

            return min(1.0, incoming / outgoing)

        except Exception as e:
            logger.error(f"Error calculating response rate: {e}")
            return 0.5
        finally:
            session.close()

    def get_user_profile(self) -> str:
        """Generate summary of everything known about user."""
        behavior = self.recall("behavior") or {}
        performance = self.recall("performance") or {}
        communication = self.recall("communication") or {}

        # Get preferences
        likes = [k for k, v in self.preferences.items() if v.get("type") == "positive"]
        dislikes = [k for k, v in self.preferences.items() if v.get("type") == "negative"]

        profile = f"""## מה אני יודע על יגל:

**תוכן:**
- נושאים מועדפים: {', '.join(likes[:5]) if likes else 'עדיין לא ידוע'}
- נושאים להימנע: {', '.join(dislikes[:5]) if dislikes else 'אין'}
- סוג תוכן מצליח: {performance.get('best_content_type', {}).get('value', 'לא ידוע')}

**התנהגות:**
- שעה מועדפת להעלאה: {behavior.get('preferred_posting_hour', {}).get('value', 'לא ידוע')}
- יום מועדף: {behavior.get('preferred_posting_day', {}).get('value', 'לא ידוע')}
- שעה הכי פעיל: {behavior.get('most_active_hour', {}).get('value', 'לא ידוע')}

**ביצועים:**
- ממוצע צפיות: {performance.get('avg_views', {}).get('value', 'לא ידוע')}

**תקשורת:**
- מעדיף הודעות קצרות: {communication.get('prefers_short_messages', {}).get('value', 'לא ידוע')}
"""
        return profile

    def get_best_contact_time(self) -> int:
        """Get the best hour to contact the user."""
        hour = self.recall("behavior", "most_active_hour")
        return hour if hour else 19  # Default to 7 PM

    def should_simplify_messages(self) -> bool:
        """Check if user prefers shorter messages."""
        return self.recall("communication", "prefers_short_messages") or False

    def update_preference(self, pref_type: str, value: str, strength_delta: float = 0.1):
        """Update or create a preference."""
        if value in self.preferences:
            self.preferences[value]["strength"] = min(
                1.0,
                self.preferences[value]["strength"] + strength_delta
            )
            self.preferences[value]["mention_count"] += 1
            self.preferences[value]["last_mentioned"] = datetime.utcnow()
        else:
            self.preferences[value] = {
                "type": pref_type,
                "strength": 0.5,
                "mention_count": 1,
                "last_mentioned": datetime.utcnow(),
            }

        # Save to database
        self._save_preference(pref_type, value)

    def _save_preference(self, pref_type: str, value: str):
        """Save preference to database."""
        session = db.get_session()
        try:
            existing = session.query(UserPreference).filter_by(
                preference_type=pref_type,
                value=value
            ).first()

            pref_data = self.preferences.get(value, {})

            if existing:
                existing.strength = pref_data.get("strength", 0.5)
                existing.mention_count = pref_data.get("mention_count", 1)
                existing.last_mentioned = datetime.utcnow()
            else:
                pref = UserPreference(
                    preference_type=pref_type,
                    value=value,
                    strength=pref_data.get("strength", 0.5),
                    mention_count=1,
                )
                session.add(pref)

            session.commit()

        except Exception as e:
            logger.error(f"Error saving preference: {e}")
        finally:
            session.close()

    def get_strong_preferences(self) -> Dict[str, List[str]]:
        """Get preferences with high confidence."""
        likes = []
        dislikes = []

        for value, data in self.preferences.items():
            if data.get("strength", 0) >= 0.6:
                if data.get("type") == "positive":
                    likes.append(value)
                else:
                    dislikes.append(value)

        return {"likes": likes, "dislikes": dislikes}
