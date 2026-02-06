"""
ConversationHandler
===================
Handles two-way WhatsApp conversations.
Understands commands, learns from feedback, and chats naturally in Hebrew.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from anthropic import Anthropic

from .config import config
from .database import db, Idea, Trend, Post, Conversation, UserPreference
from .skills import IdeaEngine, TrendRadar, MemoryCore, FeedbackLearner, ProfileScanner, GoldenMomentDetector

logger = logging.getLogger(__name__)


class ConversationHandler:
    """
    Handles natural conversations via WhatsApp.

    Commands:
    - רעיון / idea - Get a new content idea
    - טרנדים / trends - What's trending now
    - אהבתי / liked - Mark last idea as liked
    - לא אהבתי / disliked - Mark last idea as disliked
    - סטטוס / status - Weekly performance summary
    - Free text - Natural conversation
    """

    def __init__(self):
        self.client = Anthropic(api_key=config.ai.api_key) if config.ai.api_key else None
        self.idea_engine = IdeaEngine()
        self.trend_radar = TrendRadar()
        self.memory_core = MemoryCore()
        self.feedback_learner = FeedbackLearner()
        self.profile_scanner = ProfileScanner()
        self.golden_moment_detector = GoldenMomentDetector()

        # Track last sent idea for feedback
        self.last_idea_id: Optional[int] = None

        # Command patterns (Hebrew and English)
        self.commands = {
            "idea": ["רעיון", "idea", "תן רעיון", "רעיון חדש", "תן לי רעיון", "מה לעשות"],
            "trends": ["טרנדים", "trends", "טרנד", "מה חם", "מה קורה"],
            "rss": ["חדשות", "rss", "כותרות", "news", "עדכונים"],
            "scraper": ["סקרייפר", "scraper", "סריקה", "בדיקת סריקה"],
            "full_status": ["סטטוס מלא", "full status", "הכל", "כל הסטטוס"],
            "liked": ["אהבתי", "liked", "טוב", "מעולה", "👍", "❤️", "🔥", "אחלה"],
            "disliked": ["לא אהבתי", "disliked", "לא טוב", "👎", "לא מתאים", "לא בשבילי"],
            "status": ["סטטוס", "status", "איך אני", "סיכום", "ביצועים", "נתונים"],
            "help": ["עזרה", "help", "פקודות", "מה אפשר"],
        }

    async def process_message(self, message: str, from_number: str) -> str:
        """
        Process an incoming message and return a response.

        Args:
            message: The incoming message text
            from_number: Sender's phone number

        Returns:
            Response text
        """
        # Store the conversation
        await self._store_conversation(message, from_number, "incoming")

        # Clean and normalize message
        message_lower = message.lower().strip()

        # Check for golden moment responses first (בוצע, עוד, לא מעוניין, אחר כך)
        golden_response = await self.golden_moment_detector.handle_response(message)
        if golden_response:
            response = golden_response
        else:
            # Check for commands
            command = self._detect_command(message_lower)

            if command:
                response = await self._handle_command(command, message)
            else:
                # Check for preference statements
                preference = self._detect_preference(message)
                if preference:
                    response = await self._handle_preference(preference, message)
                else:
                    # Natural conversation
                    response = await self._handle_conversation(message)

        # Store the response
        await self._store_conversation(response, from_number, "outgoing")

        return response

    def _detect_command(self, message: str) -> Optional[str]:
        """Detect if message is a command."""
        for command, patterns in self.commands.items():
            for pattern in patterns:
                if pattern in message or message == pattern:
                    return command
        return None

    def _detect_preference(self, message: str) -> Optional[Dict]:
        """
        Detect if message contains a preference statement.

        Examples:
        - "אני לא אוהב תוכן על פוליטיקה"
        - "אני אוהב כשיש הומור"
        - "בבקשה יותר רעיונות עם זוהר"
        - "פחות סטורי טיימס"
        """
        message_lower = message.lower()

        # Negative preferences
        negative_patterns = [
            r"אני לא אוהב (.+)",
            r"לא אוהב (.+)",
            r"בלי (.+)",
            r"פחות (.+)",
            r"תפסיק עם (.+)",
            r"לא רוצה (.+)",
            r"נמאס לי מ(.+)",
        ]

        for pattern in negative_patterns:
            match = re.search(pattern, message_lower)
            if match:
                return {"type": "negative", "value": match.group(1).strip()}

        # Positive preferences
        positive_patterns = [
            r"אני אוהב (.+)",
            r"אוהב (.+)",
            r"יותר (.+)",
            r"בבקשה (.+)",
            r"תן לי עוד (.+)",
            r"רוצה (.+)",
            r"אני רוצה (.+)",
        ]

        for pattern in positive_patterns:
            match = re.search(pattern, message_lower)
            if match:
                return {"type": "positive", "value": match.group(1).strip()}

        return None

    async def _handle_command(self, command: str, original_message: str) -> str:
        """Handle a detected command."""

        if command == "idea":
            return await self._cmd_idea()
        elif command == "trends":
            return await self._cmd_trends()
        elif command == "rss":
            return await self._cmd_rss()
        elif command == "scraper":
            return await self._cmd_scraper()
        elif command == "full_status":
            return await self._cmd_full_status()
        elif command == "liked":
            return await self._cmd_liked()
        elif command == "disliked":
            return await self._cmd_disliked()
        elif command == "status":
            return await self._cmd_status()
        elif command == "help":
            return await self._cmd_help()
        else:
            return "לא הבנתי, נסה שוב 🤔"

    async def _cmd_idea(self) -> str:
        """Generate a new content idea."""
        try:
            # Get user preferences to consider
            preferences = await self._get_user_preferences()

            # Generate idea
            result = await self.idea_engine.execute(count=1)
            ideas = result.get("ideas", [])

            if not ideas:
                return "לא הצלחתי לייצר רעיון כרגע, נסה שוב בעוד רגע 🙏"

            idea = ideas[0]
            self.last_idea_id = idea.get("id")

            # Format response
            response = f"""💡 *רעיון חדש!*

*{idea.get('title', 'רעיון')}*

🎬 *פתיחה:*
"{idea.get('hook', '')}"

📝 *מה לעשות:*
{self._format_steps(idea.get('steps', []))}

⏱️ אורך: {idea.get('duration', '30-60 שניות')}
⏰ זמן מומלץ: {idea.get('best_time', '18:00-20:00')}
📊 צפי: {self._translate_performance(idea.get('predicted_performance', 'medium'))}

{self._format_hashtags(idea.get('hashtags', []))}

---
אהבת? שלח "אהבתי" 👍
לא מתאים? שלח "לא אהבתי" 👎"""

            return response

        except Exception as e:
            logger.error(f"Error generating idea: {e}")
            return "אופס, משהו השתבש. נסה שוב 🙏"

    async def _cmd_trends(self) -> str:
        """Get current trending topics (with AI analysis)."""
        try:
            result = await self.trend_radar.execute(max_trends=5)
            trends = result.get("relevant_trends", [])

            if not trends:
                return "אין טרנדים רלוונטיים כרגע 🤷‍♂️\nאנסה לבדוק שוב מאוחר יותר!"

            response = "🔥 *מה חם עכשיו:*\n\n"

            for i, trend in enumerate(trends[:5], 1):
                urgency_emoji = "🚨" if trend.get("urgency") == "immediate" else "📌"
                response += f"{urgency_emoji} *{trend.get('title', '')}*\n"
                if trend.get("content_opportunity"):
                    response += f"   💡 {trend.get('content_opportunity')}\n"
                response += "\n"

            response += "---\nרוצה רעיון על אחד מהם? שלח 'רעיון'!"

            return response

        except Exception as e:
            logger.error(f"Error getting trends: {e}")
            return "לא הצלחתי לבדוק טרנדים כרגע 🙏"

    async def _cmd_rss(self) -> str:
        """Get latest RSS headlines (fast, no AI analysis)."""
        try:
            result = await self.trend_radar.get_rss_headlines(limit=10)
            headlines = result.get("headlines", [])
            by_category = result.get("by_category", {})

            if not headlines:
                return "לא הצלחתי למשוך כותרות כרגע 🤷‍♂️\nנסה שוב בעוד רגע!"

            response = "📰 *כותרות אחרונות:*\n\n"

            # Show by category for better organization
            category_emoji = {
                "entertainment": "🎬",
                "breaking": "🔴",
                "lifestyle": "💫",
                "music": "🎵",
            }
            category_name = {
                "entertainment": "בידור",
                "breaking": "חדשות",
                "lifestyle": "סגנון חיים",
                "music": "מוזיקה",
            }

            for cat, entries in by_category.items():
                if entries:
                    emoji = category_emoji.get(cat, "📌")
                    name = category_name.get(cat, cat)
                    response += f"{emoji} *{name}:*\n"
                    for entry in entries[:3]:  # Top 3 per category
                        title = entry.get("title", "")[:60]
                        if len(entry.get("title", "")) > 60:
                            title += "..."
                        response += f"• {title}\n"
                    response += "\n"

            response += "---\n💡 שלח 'טרנדים' לניתוח AI מה רלוונטי לך!"

            return response

        except Exception as e:
            logger.error(f"Error getting RSS headlines: {e}")
            return "לא הצלחתי למשוך כותרות כרגע 🙏"

    async def _cmd_scraper(self) -> str:
        """Get scraper verification status."""
        try:
            # Get scraper status
            scraper_status = await self.profile_scanner.get_scraper_status()

            # Get latest posts
            latest_posts = await self.profile_scanner.get_latest_posts_summary(limit=3)

            response = "📊 *סטטוס סקרייפר:*\n\n"

            # Last scan times
            response += "🕐 *סריקה אחרונה:*\n"
            for platform in ["instagram", "tiktok"]:
                status_data = scraper_status.get(platform, {})
                last_scan = status_data.get("last_scan")
                status = status_data.get("status", "unknown")

                status_emoji = "✅" if status == "working" else ("❌" if status == "failed" else "❓")

                if last_scan:
                    hours_ago = (datetime.utcnow() - last_scan).total_seconds() / 3600
                    if hours_ago < 1:
                        time_str = f"לפני {int(hours_ago * 60)} דקות"
                    elif hours_ago < 24:
                        time_str = f"לפני {int(hours_ago)} שעות"
                    else:
                        time_str = f"לפני {int(hours_ago / 24)} ימים"
                    response += f"• {platform.title()}: {time_str} {status_emoji}\n"
                else:
                    response += f"• {platform.title()}: לא נסרק עדיין {status_emoji}\n"

            response += "\n"

            # Instagram posts
            if latest_posts.get("instagram"):
                response += "📱 *Instagram (אחרונים):*\n"
                for i, post in enumerate(latest_posts["instagram"], 1):
                    posted = post.get("posted_at")
                    if posted:
                        days_ago = (datetime.utcnow() - posted).days
                        time_str = "אתמול" if days_ago == 1 else (f"לפני {days_ago} ימים" if days_ago > 0 else "היום")
                    else:
                        time_str = "?"
                    caption = post.get("caption", "")[:30]
                    likes = self._format_number(post.get("likes", 0))
                    comments = post.get("comments", 0)
                    response += f"{i}. [{time_str}] '{caption}' - ❤️ {likes} 💬 {comments}\n"
                response += "\n"

            # TikTok posts
            if latest_posts.get("tiktok"):
                response += "📱 *TikTok (אחרונים):*\n"
                for i, post in enumerate(latest_posts["tiktok"], 1):
                    posted = post.get("posted_at")
                    if posted:
                        days_ago = (datetime.utcnow() - posted).days
                        time_str = "אתמול" if days_ago == 1 else (f"לפני {days_ago} ימים" if days_ago > 0 else "היום")
                    else:
                        time_str = "?"
                    caption = post.get("caption", "")[:30]
                    views = self._format_number(post.get("views", 0))
                    likes = self._format_number(post.get("likes", 0))
                    response += f"{i}. [{time_str}] '{caption}' - 👁️ {views} ❤️ {likes}\n"
                response += "\n"

            # Database stats
            total_posts = scraper_status.get("total_posts", 0)
            avg_engagement = scraper_status.get("avg_engagement", 0)
            response += f"📈 *במערכת:* {total_posts} פוסטים | ממוצע engagement: {avg_engagement:.1f}%"

            return response

        except Exception as e:
            logger.error(f"Error getting scraper status: {e}")
            return "לא הצלחתי לשלוף סטטוס סקרייפר כרגע 🙏"

    async def _cmd_full_status(self) -> str:
        """Get comprehensive full status."""
        try:
            # Get all components status
            scraper_status = await self.profile_scanner.get_scraper_status()
            days_since_post = await self.profile_scanner.get_days_since_last_post()
            rss_result = await self.trend_radar.get_rss_headlines(limit=5)
            learning = await self.feedback_learner.get_learning_summary()

            response = "🔍 *סטטוס מלא:*\n\n"

            # Scraper health
            response += "📊 *סקרייפר:*\n"
            for platform in ["instagram", "tiktok"]:
                status = scraper_status.get(platform, {}).get("status", "unknown")
                emoji = "✅" if status == "working" else ("❌" if status == "failed" else "❓")
                response += f"• {platform.title()}: {emoji}\n"
            response += "\n"

            # RSS health
            rss_total = rss_result.get("total", 0)
            rss_errors = len(rss_result.get("errors", []))
            rss_status = "✅" if rss_total > 0 and rss_errors < 3 else "❌"
            response += f"📰 *RSS:* {rss_status} ({rss_total} כותרות)\n\n"

            # Days since last post
            response += "📅 *ימים מפוסט אחרון:*\n"
            for platform in ["instagram", "tiktok"]:
                days = days_since_post.get(platform)
                if days is not None:
                    warning = " ⚠️" if days >= 4 else ""
                    response += f"• {platform.title()}: {days} ימים{warning}\n"
                else:
                    response += f"• {platform.title()}: אין נתונים\n"
            response += "\n"

            # Learning stats
            response += "🧠 *למידה:*\n"
            response += f"• דפוסי הצלחה: {learning.get('patterns_learned', 0)}\n"
            response += f"• העדפות: {learning.get('preferences_learned', 0)}\n"
            response += f"• דירוג ממוצע: {learning.get('average_rating', 0):.1f}/5\n"
            response += f"• שיעור קבלת רעיונות: {learning.get('idea_acceptance_rate', 0):.0f}%\n\n"

            # Database stats
            total_posts = scraper_status.get("total_posts", 0)
            avg_engagement = scraper_status.get("avg_engagement", 0)
            response += f"💾 *מסד נתונים:* {total_posts} פוסטים | {avg_engagement:.1f}% engagement"

            return response

        except Exception as e:
            logger.error(f"Error getting full status: {e}")
            return "לא הצלחתי לשלוף סטטוס מלא כרגע 🙏"

    async def _cmd_liked(self) -> str:
        """Mark last idea as liked."""
        if not self.last_idea_id:
            return "אין רעיון אחרון לדרג 🤔\nשלח 'רעיון' כדי לקבל אחד!"

        try:
            await self.feedback_learner.process_explicit_feedback(
                idea_id=self.last_idea_id,
                rating=5,
                was_helpful=True
            )

            return """👍 מעולה! סימנתי שאהבת את הרעיון.

אני לומד מזה ואייצר יותר רעיונות דומים בעתיד! 🧠✨

רוצה עוד רעיון? שלח 'רעיון'"""

        except Exception as e:
            logger.error(f"Error recording like: {e}")
            return "שמרתי את המשוב, תודה! 👍"

    async def _cmd_disliked(self) -> str:
        """Mark last idea as disliked."""
        if not self.last_idea_id:
            return "אין רעיון אחרון לדרג 🤔\nשלח 'רעיון' כדי לקבל אחד!"

        try:
            await self.feedback_learner.process_explicit_feedback(
                idea_id=self.last_idea_id,
                rating=1,
                was_helpful=False
            )

            return """👎 הבנתי, הרעיון לא מתאים.

אני לומד מזה ואנסה להציע משהו אחר בפעם הבאה! 🧠

💬 אם תרצה, ספר לי למה לא אהבת - זה יעזור לי להשתפר.

רוצה רעיון אחר? שלח 'רעיון'"""

        except Exception as e:
            logger.error(f"Error recording dislike: {e}")
            return "שמרתי את המשוב, תודה! אנסה להשתפר 🙏"

    async def _cmd_status(self) -> str:
        """Get weekly performance summary."""
        try:
            stats = await self.memory_core.execute(operation="get_stats", days=7)
            learning = await self.feedback_learner.get_learning_summary()

            trend_emoji = {
                "improving": "📈",
                "stable": "➡️",
                "declining": "📉",
            }.get(stats.get("trend", "stable"), "➡️")

            response = f"""📊 *הסטטוס שלך השבוע:*

📱 פוסטים: {stats.get('total_posts', 0)}
👁️ צפיות: {self._format_number(stats.get('total_views', 0))}
❤️ לייקים: {self._format_number(stats.get('total_likes', 0))}
💬 תגובות: {self._format_number(stats.get('total_comments', 0))}

{trend_emoji} מגמה: {self._translate_trend(stats.get('trend', 'stable'))}
📈 שינוי: {stats.get('trend_change_percent', 0):+.1f}%

🧠 *מה למדתי עליך:*
• {learning.get('patterns_learned', 0)} דפוסי הצלחה
• {learning.get('preferences_learned', 0)} העדפות אישיות
• דירוג ממוצע לרעיונות: {learning.get('average_rating', 0):.1f}/5

רוצה רעיון חדש? שלח 'רעיון' 💡"""

            return response

        except Exception as e:
            logger.error(f"Error getting status: {e}")
            return "לא הצלחתי לשלוף נתונים כרגע 🙏"

    async def _cmd_help(self) -> str:
        """Show available commands."""
        return """🤖 *הפקודות שלי:*

💡 *"רעיון"* - קבל רעיון לתוכן חדש
🔥 *"טרנדים"* - מה חם עכשיו (עם ניתוח AI)
📰 *"חדשות"* - כותרות אחרונות מהעולם
📊 *"סטטוס"* - איך אתה מבצע השבוע
🔍 *"סקרייפר"* - בדוק סטטוס סריקה
📋 *"סטטוס מלא"* - כל הנתונים במקום אחד
👍 *"אהבתי"* - הרעיון האחרון היה טוב
👎 *"לא אהבתי"* - הרעיון לא מתאים

🚨 *תגובות ל"רגע זהב":*
• *"בוצע"* - השתמשתי ברעיון
• *"עוד"* - תן לי רעיון אחר לטרנד
• *"לא מעוניין"* - דלג על הטרנד הזה
• *"אחר כך"* - תזכיר לי בעוד שעה

💬 *טיפ:* אתה יכול גם לדבר איתי חופשי!
למשל:
• "אני לא אוהב סטורי טיימס"
• "תן לי יותר רעיונות עם זוהר"
• "מה דעתך על תוכן מוזיקלי?"

אני לומד מכל שיחה ומשתפר! 🧠"""

    async def _handle_preference(self, preference: Dict, original_message: str) -> str:
        """Handle a preference statement and learn from it."""
        pref_type = preference["type"]
        pref_value = preference["value"]

        try:
            # Store the preference
            await self._store_preference(pref_type, pref_value, original_message)

            if pref_type == "positive":
                return f"""👍 הבנתי! אתה אוהב {pref_value}.

שמרתי את זה ואשתדל לכלול יותר כאלה ברעיונות הבאים! 🧠✨

רוצה רעיון עכשיו? שלח 'רעיון'"""
            else:
                return f"""👍 הבנתי! אתה לא אוהב {pref_value}.

שמרתי את זה ואמנע מלהציע דברים כאלה בעתיד! 🧠

רוצה רעיון עכשיו? שלח 'רעיון'"""

        except Exception as e:
            logger.error(f"Error storing preference: {e}")
            return "שמעתי אותך! אני לומד מזה 🧠"

    async def _handle_conversation(self, message: str) -> str:
        """Handle free-form conversation using Claude."""
        if not self.client:
            return "אני כאן! שלח 'עזרה' לראות מה אני יכול לעשות 🤖"

        try:
            # Get conversation history
            history = await self._get_recent_conversation()

            # Get user preferences for context
            preferences = await self._get_user_preferences()

            # Build context
            pref_text = ""
            if preferences:
                likes = [p["value"] for p in preferences if p["type"] == "positive"]
                dislikes = [p["value"] for p in preferences if p["type"] == "negative"]
                if likes:
                    pref_text += f"העדפות חיוביות: {', '.join(likes)}\n"
                if dislikes:
                    pref_text += f"דברים להימנע מהם: {', '.join(dislikes)}\n"

            system_prompt = f"""אתה העוזר האישי של יוצר תוכן ישראלי (מוזיקאי).
אתה כמו חבר טוב שעוזר לו עם תוכן לרשתות החברתיות.

פרטים על היוצר:
- שם: {config.creator.name or 'יגל'}
- בת זוג: {config.creator.girlfriend_name or 'זוהר'}
- פלטפורמות: TikTok, Instagram
- סגנון: אותנטי, טבעי, לא מתיימר
- תוכן מצליח: תוכן זוגיות (3x), סטורי טיימס (2x), תגובות לטרנדים (1.5x)

{pref_text}

כללים:
1. דבר בעברית טבעית, כמו חבר
2. תהיה תומך ומעודד אבל כנה
3. אם שואלים על רעיונות - הפנה לפקודה 'רעיון'
4. אם שואלים על טרנדים - הפנה לפקודה 'טרנדים'
5. אם מזהה העדפה (אוהב/לא אוהב משהו) - אשר שלמדת את זה
6. תשובות קצרות וממוקדות (עד 5-6 שורות)
7. השתמש באימוג'ים בצורה טבעית (לא יותר מדי)

זכור: אתה לא רק בוט, אתה חבר שרוצה לעזור ליוצר להצליח!"""

            messages = []

            # Add recent conversation history
            for msg in history[-6:]:  # Last 6 messages for context
                role = "user" if msg["direction"] == "incoming" else "assistant"
                messages.append({"role": role, "content": msg["content"]})

            # Add current message
            messages.append({"role": "user", "content": message})

            response = self.client.messages.create(
                model=config.ai.model,
                max_tokens=500,
                system=system_prompt,
                messages=messages
            )

            return response.content[0].text

        except Exception as e:
            logger.error(f"Conversation error: {e}")
            return "אני כאן! מה אתה צריך? 🤖\n\nשלח 'עזרה' לראות את הפקודות שלי."

    async def _store_conversation(self, content: str, phone: str, direction: str):
        """Store a conversation message."""
        session = db.get_session()
        try:
            conv = Conversation(
                phone_number=phone,
                direction=direction,
                content=content,
            )
            session.add(conv)
            session.commit()
        except Exception as e:
            logger.error(f"Error storing conversation: {e}")
        finally:
            session.close()

    async def _get_recent_conversation(self, limit: int = 10) -> List[Dict]:
        """Get recent conversation messages."""
        session = db.get_session()
        try:
            messages = session.query(Conversation).order_by(
                Conversation.created_at.desc()
            ).limit(limit).all()

            return [
                {"content": m.content, "direction": m.direction, "time": m.created_at}
                for m in reversed(messages)
            ]
        finally:
            session.close()

    async def _store_preference(self, pref_type: str, value: str, original_message: str):
        """Store a user preference."""
        session = db.get_session()
        try:
            # Check if preference already exists
            existing = session.query(UserPreference).filter_by(
                preference_type=pref_type,
                value=value
            ).first()

            if existing:
                existing.strength = min(1.0, existing.strength + 0.1)
                existing.mention_count += 1
                existing.last_mentioned = datetime.utcnow()
            else:
                pref = UserPreference(
                    preference_type=pref_type,
                    value=value,
                    original_message=original_message,
                    strength=0.5,
                    mention_count=1,
                )
                session.add(pref)

            session.commit()
        finally:
            session.close()

    async def _get_user_preferences(self) -> List[Dict]:
        """Get all user preferences."""
        session = db.get_session()
        try:
            prefs = session.query(UserPreference).filter(
                UserPreference.strength >= 0.3
            ).order_by(UserPreference.strength.desc()).all()

            return [
                {"type": p.preference_type, "value": p.value, "strength": p.strength}
                for p in prefs
            ]
        finally:
            session.close()

    def _format_steps(self, steps: List[str]) -> str:
        """Format steps as numbered list."""
        if not steps:
            return ""
        return "\n".join([f"{i}. {step}" for i, step in enumerate(steps, 1)])

    def _format_hashtags(self, hashtags: List[str]) -> str:
        """Format hashtags."""
        if not hashtags:
            return ""
        return "🏷️ " + " ".join(hashtags)

    def _translate_performance(self, perf: str) -> str:
        """Translate performance level to Hebrew."""
        return {"high": "גבוה 🔥", "medium": "בינוני 👍", "low": "נמוך"}.get(perf, perf)

    def _translate_trend(self, trend: str) -> str:
        """Translate trend to Hebrew."""
        return {
            "improving": "משתפר! 🚀",
            "stable": "יציב",
            "declining": "יורד קצת",
        }.get(trend, trend)

    def _format_number(self, num: int) -> str:
        """Format large numbers."""
        if num >= 1_000_000:
            return f"{num / 1_000_000:.1f}M"
        elif num >= 1_000:
            return f"{num / 1_000:.1f}K"
        return str(num)
