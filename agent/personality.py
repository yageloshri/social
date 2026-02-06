"""
PersonalityEngine
=================
Gives the agent a consistent personality and communication style.
"""

import random
from datetime import datetime
from typing import Any, Dict, Optional
import pytz

ISRAEL_TZ = pytz.timezone("Asia/Jerusalem")


class PersonalityEngine:
    """
    Gives the agent a consistent personality.

    The agent is:
    - Friendly but professional
    - Supportive but honest
    - Helpful but not pushy
    - Uses Hebrew naturally
    """

    # Personality traits
    PERSONALITY = {
        "name": "הסוכן שלך",
        "tone": "חברי, תומך, מקצועי",
        "emoji_style": "moderate",  # Not too many
        "humor": "light",  # Occasional humor
        "directness": "high",  # Get to the point
    }

    # Mood-based message openers
    MOOD_OPENERS = {
        "excited": [
            "🔥 יש לי משהו מטורף בשבילך!",
            "🚀 תכין את עצמך...",
            "✨ יש הזדמנות מעולה!",
        ],
        "supportive": [
            "💪 אני פה איתך!",
            "👋 היי!",
            "🤝 ",
        ],
        "analytical": [
            "📊 בוא נסתכל על הנתונים...",
            "📈 יש לי כמה תובנות...",
            "🔍 הנה מה שמצאתי:",
        ],
        "gentle_push": [
            "היי, רק רציתי להזכיר...",
            "💭 חשבתי עליך...",
            "⏰ תזכורת קטנה:",
        ],
        "celebration": [
            "🎉 איזה כיף!!!",
            "🎊 מזל טוב!",
            "🏆 וואו!",
        ],
        "casual": [
            "היי!",
            "מה קורה?",
            "👋",
        ],
    }

    # Time-based greetings
    TIME_GREETINGS = {
        "morning": ["בוקר טוב! ☀️", "בוקר אור!", "שיהיה יום טוב!"],
        "afternoon": ["צהריים טובים!", "מה שלומך?", ""],
        "evening": ["ערב טוב! 🌙", "איך היה היום?", ""],
        "night": ["לילה טוב 🌃", "עדיין ער?", ""],
    }

    # Motivation messages
    MOTIVATION_MESSAGES = [
        "💪 אתה יוצר תוכן מדהים, תמשיך ככה!",
        "🌟 הקהל שלך מחכה לך!",
        "🚀 היום יכול להיות היום של הפוסט הוויראלי הבא!",
        "✨ כל פוסט מקרב אותך להצלחה",
        "💡 יש לך סגנון ייחודי - תראה אותו לעולם!",
        "🎯 עקביות היא המפתח - אתה בדרך הנכונה!",
    ]

    # Reminder messages
    REMINDER_MESSAGES = [
        "⏰ היי, לא שכחת להעלות היום?",
        "📱 הקהל שלך מתגעגע!",
        "💭 חשבת על מה להעלות?",
        "🎬 יש לי כמה רעיונות אם אתה צריך...",
        "✨ זמן מושלם לתוכן חדש!",
    ]

    # Closing lines
    CLOSINGS = {
        "idea": ["רוצה עוד רעיון? שלח 'עוד' 🔄", "אהבת? שלח 'אהבתי' 👍"],
        "trend": ["מעוניין? שלח 'רעיון'", "רוצה לדעת יותר?"],
        "status": ["רוצה רעיון? שלח 'רעיון' 💡", "שאלות? אני כאן!"],
        "default": ["אני כאן אם תצטרך משהו!", "בהצלחה! 🤞"],
    }

    def __init__(self):
        self.current_mood = "supportive"

    def set_mood(self, context: Dict) -> str:
        """Decide current mood based on context."""
        if context.get("celebration"):
            self.current_mood = "celebration"
        elif context.get("opportunity"):
            self.current_mood = "excited"
        elif context.get("needs_push"):
            self.current_mood = "gentle_push"
        elif context.get("data_heavy"):
            self.current_mood = "analytical"
        else:
            self.current_mood = "supportive"

        return self.current_mood

    def get_opener(self, mood: str = None) -> str:
        """Get an appropriate opener for the mood."""
        mood = mood or self.current_mood
        openers = self.MOOD_OPENERS.get(mood, self.MOOD_OPENERS["supportive"])
        return random.choice(openers)

    def get_time_greeting(self) -> str:
        """Get appropriate greeting for time of day."""
        now = datetime.now(ISRAEL_TZ)
        hour = now.hour

        if 5 <= hour < 12:
            period = "morning"
        elif 12 <= hour < 17:
            period = "afternoon"
        elif 17 <= hour < 22:
            period = "evening"
        else:
            period = "night"

        greetings = self.TIME_GREETINGS[period]
        return random.choice(greetings)

    def get_motivation_message(self) -> str:
        """Get a random motivation message."""
        return random.choice(self.MOTIVATION_MESSAGES)

    def get_reminder_message(self) -> str:
        """Get a random reminder message."""
        return random.choice(self.REMINDER_MESSAGES)

    def get_closing(self, message_type: str = "default") -> str:
        """Get an appropriate closing line."""
        closings = self.CLOSINGS.get(message_type, self.CLOSINGS["default"])
        return random.choice(closings)

    def style_message(self, content: str, mood: str = None, add_greeting: bool = False) -> str:
        """Add personality styling to a message."""
        mood = mood or self.current_mood
        parts = []

        # Add greeting if requested
        if add_greeting:
            greeting = self.get_time_greeting()
            if greeting:
                parts.append(greeting)

        # Add opener based on mood (not always)
        if mood in ["excited", "celebration", "gentle_push"]:
            opener = self.get_opener(mood)
            if opener:
                parts.append(opener)

        # Add main content
        parts.append(content)

        # Combine
        message = "\n\n".join(parts)

        # Apply emoji moderation
        message = self._moderate_emojis(message)

        return message

    def _moderate_emojis(self, text: str) -> str:
        """Ensure emoji usage is moderate (not too many)."""
        # Count emojis (simplified - just count common patterns)
        emoji_count = sum(1 for char in text if ord(char) > 127462)

        # If too many emojis, this is a simplified check
        # In production, you'd want proper emoji detection
        if emoji_count > 6:
            # Could implement emoji reduction here
            pass

        return text

    def format_number(self, num: int) -> str:
        """Format numbers in a friendly way."""
        if num >= 1_000_000:
            return f"{num / 1_000_000:.1f}M"
        elif num >= 1_000:
            return f"{num / 1_000:.1f}K"
        return str(num)

    def format_time_ago(self, hours: float) -> str:
        """Format time ago in Hebrew."""
        if hours < 1:
            minutes = int(hours * 60)
            return f"לפני {minutes} דקות"
        elif hours < 24:
            return f"לפני {int(hours)} שעות"
        else:
            days = int(hours / 24)
            if days == 1:
                return "אתמול"
            elif days < 7:
                return f"לפני {days} ימים"
            else:
                weeks = days // 7
                return f"לפני {weeks} שבועות"

    def get_encouragement_for_streak(self, days: int) -> str:
        """Get encouragement for posting streak."""
        if days >= 7:
            return f"🔥 שבוע שלם של עקביות! {days} ימים ברצף!"
        elif days >= 3:
            return f"💪 {days} ימים ברצף! ממשיכים!"
        elif days >= 1:
            return "👍 יום טוב! בוא נשמור על הקצב"
        else:
            return "🚀 בוא נתחיל סטריק חדש!"

    def get_performance_reaction(self, multiplier: float) -> str:
        """Get reaction to performance relative to average."""
        if multiplier >= 3.0:
            return "🤯 משוגע!!! פי 3 מהממוצע!"
        elif multiplier >= 2.0:
            return "🔥 וואו! פי 2 מהממוצע!"
        elif multiplier >= 1.5:
            return "📈 מעל הממוצע! יפה!"
        elif multiplier >= 1.0:
            return "👍 ממש בסדר"
        elif multiplier >= 0.7:
            return "📊 קצת מתחת לממוצע"
        else:
            return "🤔 צריך לנתח למה"

    def personalize_idea(self, idea: Dict, user_prefs: Dict) -> str:
        """Personalize an idea based on user preferences."""
        likes = user_prefs.get("likes", [])
        dislikes = user_prefs.get("dislikes", [])

        # Check if idea matches preferences
        idea_text = idea.get("description", "").lower()
        idea_topics = idea.get("topics", [])

        for like in likes:
            if like.lower() in idea_text or like in idea_topics:
                return f"💡 זה בדיוק הסגנון שאתה אוהב!"

        return ""

    def get_daily_tip(self) -> str:
        """Get a daily content tip."""
        tips = [
            "💡 טיפ: ה-3 שניות הראשונות קריטיות - תפתח חזק!",
            "💡 טיפ: תשאיר את הצופים עד הסוף עם cliffhanger",
            "💡 טיפ: תוכן אותנטי תמיד מנצח",
            "💡 טיפ: תענה לתגובות - זה מגביר אנגייג'מנט",
            "💡 טיפ: השעות 18:00-21:00 הכי טובות להעלאה",
            "💡 טיפ: תגובה ויראלית יכולה להיות פוסט בפני עצמו",
            "💡 טיפ: סדרות מחזיקות קהל - תחשוב על המשכים",
            "💡 טיפ: טרנדים חמים = הזדמנות להגיע לקהל חדש",
        ]
        return random.choice(tips)
