"""
MessageCrafter Skill
====================
Composes perfect WhatsApp messages in Hebrew.
Handles different message types: morning, midday, afternoon, evening.
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional
import logging
import json

from anthropic import Anthropic

from .base import BaseSkill
from ..config import config
from ..database import db, Message, Idea, Trend, Post

logger = logging.getLogger(__name__)


class MessageCrafter(BaseSkill):
    """
    Composes personalized WhatsApp messages in Hebrew.

    Message types:
    - morning (09:00): Motivating, main idea for the day
    - midday (13:00): Quick trend update
    - afternoon (17:00): Story/quick content reminder
    - evening (21:00): Reflective, planning for tomorrow
    """

    def __init__(self):
        super().__init__("MessageCrafter")
        self.client = Anthropic(api_key=config.ai.api_key) if config.ai.api_key else None

    async def execute(
        self,
        message_type: str = "morning",
        ideas: List[Dict] = None,
        trends: List[Dict] = None,
        performance_data: Dict = None
    ) -> Dict[str, Any]:
        """
        Craft a WhatsApp message.

        Args:
            message_type: Type of message ('morning', 'midday', 'afternoon', 'evening')
            ideas: Content ideas to include
            trends: Current trends to mention
            performance_data: Recent performance stats

        Returns:
            Dict with crafted message
        """
        self.log_start()

        if not self.client:
            return {"error": "Anthropic client not configured"}

        results = {
            "message_type": message_type,
            "message": "",
            "ideas_included": [],
            "trends_included": [],
        }

        try:
            # Get message specs based on type
            specs = self._get_message_specs(message_type)

            # Craft the message
            message = await self._craft_message(
                specs=specs,
                ideas=ideas or [],
                trends=trends or [],
                performance_data=performance_data or {}
            )

            results["message"] = message
            results["ideas_included"] = [i.get("id") for i in (ideas or []) if i.get("id")]
            results["trends_included"] = [t.get("id") for t in (trends or []) if t.get("id")]
            results["summary"] = f"Crafted {message_type} message ({len(message)} chars)"

            self.log_complete(results)

        except Exception as e:
            self.log_error(e)
            results["error"] = str(e)

        return results

    def _get_message_specs(self, message_type: str) -> Dict:
        """
        Get specifications for each message type.

        Args:
            message_type: Type of message

        Returns:
            Dict with message specifications
        """
        specs = {
            "morning": {
                "time": "09:00",
                "energy": "motivating, energizing",
                "emoji_start": "☀️",
                "max_lines": 12,
                "content_focus": [
                    "Main content idea for today (specific!)",
                    "One trending topic to consider",
                    "Reminder of best posting time",
                ],
                "must_include": "One specific, actionable idea with exact hook",
                "tone": "Like a friend who's excited to help you succeed",
            },
            "midday": {
                "time": "13:00",
                "energy": "quick, focused",
                "emoji_start": "🔥",
                "max_lines": 6,
                "content_focus": [
                    "Trend update (what's happening NOW)",
                    "Quick content opportunity if relevant",
                ],
                "skip_if": "Nothing relevant happening",
                "tone": "Brief, to the point, action-oriented",
            },
            "afternoon": {
                "time": "17:00",
                "energy": "friendly reminder",
                "emoji_start": "📱",
                "max_lines": 6,
                "content_focus": [
                    "Story/quick content reminder",
                    "Easy idea that takes 2 minutes",
                ],
                "tone": "Like a friend nudging you",
            },
            "evening": {
                "time": "21:00",
                "energy": "reflective, planning",
                "emoji_start": "🌙",
                "max_lines": 10,
                "content_focus": [
                    "Quick day summary (if posted)",
                    "Tomorrow's main idea",
                    "Any prep needed",
                ],
                "must_include": "Encouragement based on actual performance",
                "tone": "Supportive, looking forward to tomorrow",
            },
        }

        return specs.get(message_type, specs["morning"])

    async def _craft_message(
        self,
        specs: Dict,
        ideas: List[Dict],
        trends: List[Dict],
        performance_data: Dict
    ) -> str:
        """
        Use Claude to craft the perfect message.

        Args:
            specs: Message specifications
            ideas: Ideas to include
            trends: Trends to mention
            performance_data: Performance stats

        Returns:
            Crafted message string
        """
        creator_name = config.creator.name or "יוצר"
        girlfriend_name = config.creator.girlfriend_name or "בת הזוג"

        prompt = f"""You are the personal assistant of {creator_name}, an Israeli content creator.
Write a WhatsApp message in Hebrew for {specs.get('time', '')} ({specs.get('energy', '')}).

MESSAGE REQUIREMENTS:
- Start with: {specs.get('emoji_start', '')}
- Max lines: {specs.get('max_lines', 10)}
- Tone: {specs.get('tone', 'friendly')}
- Energy: {specs.get('energy', 'positive')}
- Must include: {specs.get('must_include', 'actionable content')}

CONTENT TO INCLUDE:
{json.dumps(specs.get('content_focus', []), ensure_ascii=False)}

TODAY'S IDEAS (include the best one with SPECIFIC details):
{json.dumps(ideas[:2] if ideas else [], indent=2, ensure_ascii=False)}

CURRENT TRENDS (mention if relevant):
{json.dumps(trends[:2] if trends else [], indent=2, ensure_ascii=False)}

PERFORMANCE DATA:
{json.dumps(performance_data, indent=2, ensure_ascii=False)}

CREATOR CONTEXT:
- Girlfriend's name: {girlfriend_name}
- Best posting time: {config.schedule.optimal_posting_start}-{config.schedule.optimal_posting_end}
- Top content: Couple content (3x), Storytimes (2x)

WRITING RULES:
1. Hebrew only, natural conversational tone
2. Use emojis appropriately (not too many)
3. Be SPECIFIC - never vague
4. When sharing an idea, include the EXACT hook to use
5. Sound like a supportive friend, not a corporate bot
6. Keep it concise - respect their time
7. End with motivation/encouragement

BAD EXAMPLE (too vague):
"בוקר טוב! אל תשכח להעלות תוכן היום 😊"

GOOD EXAMPLE (specific):
"☀️ בוקר טוב!

💡 הרעיון להיום: צלם את {girlfriend_name} כשהיא מגלה [משהו ספציפי].

פתיחה: 'הבעת הפנים של {girlfriend_name} כש...'

🔥 כולם מדברים על [טרנד ספציפי] - יש פה הזדמנות!

⏰ הזמן הטוב להעלות: 18:00-20:00

יאללה, יום מעולה! 🎬"

Write the message now (Hebrew only):"""

        response = self.client.messages.create(
            model=config.ai.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )

        return response.content[0].text.strip()

    async def craft_morning_message(
        self,
        ideas: List[Dict],
        trends: List[Dict] = None
    ) -> str:
        """
        Craft the morning motivation message.

        Args:
            ideas: Today's content ideas
            trends: Current trends

        Returns:
            Crafted message
        """
        result = await self.execute(
            message_type="morning",
            ideas=ideas,
            trends=trends
        )
        return result.get("message", "")

    async def craft_midday_message(
        self,
        trends: List[Dict]
    ) -> Optional[str]:
        """
        Craft midday trend update.
        Returns None if no relevant trends.

        Args:
            trends: Current hot trends

        Returns:
            Crafted message or None
        """
        if not trends:
            return None

        # Check if any trends are urgent
        urgent_trends = [t for t in trends if t.get("urgency") == "immediate"]
        if not urgent_trends:
            return None

        result = await self.execute(
            message_type="midday",
            trends=urgent_trends
        )
        return result.get("message", "")

    async def craft_afternoon_message(
        self,
        quick_ideas: List[Dict] = None
    ) -> str:
        """
        Craft afternoon reminder message.

        Args:
            quick_ideas: Quick/easy content ideas

        Returns:
            Crafted message
        """
        # Generate quick story ideas if none provided
        if not quick_ideas:
            quick_ideas = [{
                "title": "סטורי מהיר",
                "hook": "שאלה לעוקבים או עדכון קצר מהיום",
                "description": "תוכן קל שלוקח 2 דקות"
            }]

        result = await self.execute(
            message_type="afternoon",
            ideas=quick_ideas
        )
        return result.get("message", "")

    async def craft_evening_message(
        self,
        performance_data: Dict,
        tomorrow_ideas: List[Dict] = None
    ) -> str:
        """
        Craft evening summary and planning message.

        Args:
            performance_data: Today's performance stats
            tomorrow_ideas: Ideas for tomorrow

        Returns:
            Crafted message
        """
        result = await self.execute(
            message_type="evening",
            ideas=tomorrow_ideas,
            performance_data=performance_data
        )
        return result.get("message", "")

    async def craft_trend_alert(self, trend: Dict) -> str:
        """
        Craft an urgent trend alert message.
        For breaking/viral trends that need immediate action.

        Args:
            trend: Trend data

        Returns:
            Urgent alert message
        """
        prompt = f"""Write an URGENT WhatsApp alert in Hebrew for a content creator.

BREAKING TREND:
{json.dumps(trend, indent=2, ensure_ascii=False)}

Requirements:
- Start with 🚨
- Be very brief (4-5 lines max)
- Include specific content angle
- Emphasize urgency
- Hebrew only

Example format:
🚨 טרנד חם עכשיו!

[נושא הטרנד] - כולם מדברים על זה.

רעיון מהיר: [רעיון ספציפי]

⏰ חלון ההזדמנות: השעות הקרובות

Write the alert:"""

        response = self.client.messages.create(
            model=config.ai.model,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )

        return response.content[0].text.strip()

    async def store_message(
        self,
        message: str,
        message_type: str,
        idea_ids: List[int] = None,
        trend_ids: List[int] = None,
        twilio_sid: str = None
    ) -> int:
        """
        Store sent message in database.

        Args:
            message: Message content
            message_type: Type of message
            idea_ids: IDs of ideas included
            trend_ids: IDs of trends mentioned
            twilio_sid: Twilio message SID

        Returns:
            Message ID
        """
        session = db.get_session()
        try:
            msg = Message(
                message_type=message_type,
                content=message,
                idea_ids=idea_ids,
                trend_ids=trend_ids,
                twilio_sid=twilio_sid,
                status="sent",
            )
            session.add(msg)
            session.commit()
            return msg.id
        finally:
            session.close()
