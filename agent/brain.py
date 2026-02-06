"""
AgentBrain
==========
Central intelligence that makes autonomous decisions.
The brain observes, thinks, decides, acts, and learns.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import pytz

from anthropic import Anthropic

from .config import config
from .database import db, Post, Trend, Idea, Message, Conversation, GoldenMomentAlert

logger = logging.getLogger(__name__)

# Israel timezone
ISRAEL_TZ = pytz.timezone("Asia/Jerusalem")


class AgentBrain:
    """
    Central intelligence that makes autonomous decisions.

    The brain:
    1. OBSERVES - Gathers context from all sources
    2. THINKS - Analyzes and makes decisions
    3. ACTS - Takes actions without being asked
    4. LEARNS - Improves from every interaction
    """

    def __init__(self, memory, goals, personality):
        self.client = Anthropic(api_key=config.ai.api_key) if config.ai.api_key else None
        self.memory = memory
        self.goals = goals
        self.personality = personality

        # Track actions to prevent spam
        self.messages_sent_today = 0
        self.last_message_time = None
        self.unanswered_messages = 0

        # Decision history for learning
        self.decision_history = []

    async def think(self) -> Dict[str, Any]:
        """
        Main thinking loop - runs every 30 minutes.

        Returns:
            Dict with thinking results and any action taken
        """
        logger.info("Brain thinking cycle started...")

        results = {
            "thought_at": datetime.now(ISRAEL_TZ).isoformat(),
            "context_gathered": False,
            "action_decided": None,
            "action_executed": False,
            "reason": None,
        }

        try:
            # 1. Gather current context
            context = await self.gather_context()
            results["context_gathered"] = True

            # 2. Evaluate goals progress
            goals_status = self.goals.evaluate_progress()

            # 3. Identify opportunities and problems
            opportunities = await self._identify_opportunities(context)
            problems = await self._identify_problems(context)

            # 4. Decide what action to take
            decision = await self._decide_action(context, goals_status, opportunities, problems)
            results["action_decided"] = decision.get("action") if decision else None
            results["reason"] = decision.get("reason") if decision else None

            # 5. Execute if needed
            if decision and self._should_act(decision):
                executed = await self._execute_action(decision)
                results["action_executed"] = executed

                if executed:
                    # Update tracking
                    self.messages_sent_today += 1
                    self.last_message_time = datetime.now(ISRAEL_TZ)

            # 6. Learn from this cycle
            self._learn_from_cycle(context, decision, results)

            logger.info(f"Brain cycle complete: action={results['action_decided']}, executed={results['action_executed']}")

        except Exception as e:
            logger.error(f"Brain thinking error: {e}")
            results["error"] = str(e)

        return results

    async def gather_context(self) -> Dict[str, Any]:
        """Gather all relevant information for decision making."""

        now = datetime.now(ISRAEL_TZ)

        context = {
            # Time context
            "time": now,
            "day_of_week": now.strftime("%A"),
            "day_hebrew": self._get_hebrew_day(now.weekday()),
            "hour": now.hour,
            "is_weekend": now.weekday() >= 4,  # Friday-Saturday in Israel
            "is_prime_time": 16 <= now.hour <= 21,
            "is_night": now.hour >= 23 or now.hour < 8,

            # Posting status
            "last_tiktok_post": await self._get_last_post("tiktok"),
            "last_instagram_post": await self._get_last_post("instagram"),
            "hours_since_tiktok": await self._hours_since_last_post("tiktok"),
            "hours_since_instagram": await self._hours_since_last_post("instagram"),

            # Performance
            "recent_performance": await self._get_recent_performance(),
            "trending_posts": await self._get_trending_posts(),
            "engagement_trend": await self._calculate_engagement_trend(),

            # External factors
            "hot_trends": await self._get_hot_trends(),
            "news_opportunities": await self._get_news_opportunities(),

            # User state
            "user_mood": self._estimate_user_mood(),
            "last_interaction": await self._get_last_interaction(),
            "response_rate": self._get_user_response_rate(),

            # Agent state
            "messages_sent_today": self.messages_sent_today,
            "unanswered_messages": self.unanswered_messages,

            # Goals
            "weekly_goal": self.goals.get_weekly_goal(),
            "goal_progress": self.goals.get_progress_summary(),
            "priority_goal": self.goals.get_priority_goal(),
        }

        return context

    async def _identify_opportunities(self, context: Dict) -> List[Dict]:
        """Identify current opportunities for content."""

        opportunities = []

        # Golden moment opportunity
        if context["is_prime_time"] and context["hours_since_tiktok"] > 20:
            hot_trends = context.get("hot_trends", [])
            if hot_trends:
                opportunities.append({
                    "type": "golden_moment",
                    "urgency": "high",
                    "description": f"טרנד חם + לא העלית היום: {hot_trends[0].get('title', '')}",
                    "trend": hot_trends[0],
                })

        # Viral post opportunity
        trending = context.get("trending_posts", [])
        for post in trending:
            if post.get("multiplier", 1) >= 2.0:
                opportunities.append({
                    "type": "viral_momentum",
                    "urgency": "medium",
                    "description": f"פוסט הולך ויראלי! ({post.get('views', 0):,} צפיות)",
                    "post": post,
                })

        # Weekend content opportunity
        if context["is_weekend"] and context["hours_since_tiktok"] > 24:
            opportunities.append({
                "type": "weekend_content",
                "urgency": "medium",
                "description": "סופ\"ש - זמן טוב לתוכן קליל",
            })

        # Goal achievement opportunity
        if context["goal_progress"].get("close_to_goal"):
            opportunities.append({
                "type": "goal_push",
                "urgency": "medium",
                "description": f"קרוב ליעד השבועי! ({context['goal_progress'].get('percentage', 0)}%)",
            })

        return opportunities

    async def _identify_problems(self, context: Dict) -> List[Dict]:
        """Identify current problems that need attention."""

        problems = []

        # Long time without posting
        if context["hours_since_tiktok"] and context["hours_since_tiktok"] > 72:
            problems.append({
                "type": "no_posts",
                "severity": "high",
                "description": f"לא העלית כבר {int(context['hours_since_tiktok'] / 24)} ימים!",
            })
        elif context["hours_since_tiktok"] and context["hours_since_tiktok"] > 48:
            problems.append({
                "type": "no_posts",
                "severity": "medium",
                "description": "יומיים בלי תוכן",
            })

        # Declining engagement
        if context["engagement_trend"] == "declining":
            problems.append({
                "type": "engagement_drop",
                "severity": "medium",
                "description": "האנגייג'מנט יורד השבוע",
            })

        # Behind on goals
        priority_goal = context.get("priority_goal")
        if priority_goal and priority_goal.get("behind"):
            problems.append({
                "type": "behind_goals",
                "severity": "medium",
                "description": f"מפגר ביעד: {priority_goal.get('name', '')}",
            })

        # User not responding
        if self.unanswered_messages >= 3:
            problems.append({
                "type": "user_unresponsive",
                "severity": "low",
                "description": "המשתמש לא עונה להודעות",
            })

        return problems

    async def _decide_action(
        self,
        context: Dict,
        goals_status: Dict,
        opportunities: List[Dict],
        problems: List[Dict]
    ) -> Optional[Dict]:
        """Use Claude to decide what action to take."""

        if not self.client:
            logger.warning("No AI client configured, skipping decision")
            return None

        # Format opportunities and problems for prompt
        opp_text = "\n".join([f"- [{o['urgency'].upper()}] {o['description']}" for o in opportunities]) or "אין הזדמנויות מיוחדות"
        prob_text = "\n".join([f"- [{p['severity'].upper()}] {p['description']}" for p in problems]) or "אין בעיות"

        # Format goals status
        goals_text = ""
        for goal_name, status in goals_status.items():
            emoji = "✅" if status["on_track"] else ("⚠️" if status["behind"] else "📊")
            goals_text += f"- {goal_name}: {status['progress']:.0f}% (צפוי: {status['expected']:.0f}%) {emoji}\n"

        prompt = f"""אתה הסוכן האוטונומי של יגל, יוצר תוכן ישראלי. תפקידך להחליט האם לפעול עכשיו.

## מצב נוכחי:
- שעה: {context['hour']}:00, יום {context['day_hebrew']}
- TikTok: העלה לפני {context['hours_since_tiktok'] or 'N/A'} שעות
- Instagram: העלה לפני {context['hours_since_instagram'] or 'N/A'} שעות
- הודעות שנשלחו היום: {context['messages_sent_today']}
- הודעות ללא מענה: {self.unanswered_messages}
- מגמת אנגייג'מנט: {context['engagement_trend']}

## יעדים:
{goals_text}

## הזדמנויות:
{opp_text}

## בעיות:
{prob_text}

## אפשרויות פעולה:
1. SEND_IDEA - לשלוח רעיון לתוכן (כשהמשתמש צריך השראה)
2. SEND_TREND_ALERT - להתריע על טרנד חם (רק אם באמת דחוף)
3. SEND_MOTIVATION - לשלוח עידוד (כשהמשתמש צריך דחיפה)
4. SEND_REMINDER - תזכורת להעלות (כשעבר הרבה זמן)
5. SEND_PERFORMANCE_UPDATE - עדכון ביצועים (כשיש משהו מעניין)
6. SEND_GOAL_UPDATE - עדכון על התקדמות ביעדים
7. STAY_QUIET - לא לשלוח כלום

## כללים חשובים:
- אם כבר נשלחו 3 הודעות היום - STAY_QUIET (אלא אם קריטי)
- אם השעה 23:00-08:00 - STAY_QUIET (אלא אם חירום)
- אם יש 3+ הודעות ללא מענה - STAY_QUIET (תן מרווח)
- אם אין שום דבר חשוב - STAY_QUIET (שקט זה בסדר!)

## החלטתך:
ענה בפורמט הבא בלבד:
ACTION: [שם הפעולה]
REASON: [סיבה קצרה בעברית]
URGENCY: [low/medium/high/critical]
CONTENT: [תוכן ההודעה אם רלוונטי, או "N/A"]"""

        try:
            response = self.client.messages.create(
                model=config.ai.model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )

            return self._parse_decision(response.content[0].text)

        except Exception as e:
            logger.error(f"Decision error: {e}")
            return None

    def _parse_decision(self, response_text: str) -> Dict:
        """Parse Claude's decision response."""

        decision = {
            "action": "STAY_QUIET",
            "reason": "",
            "urgency": "low",
            "content": None,
        }

        lines = response_text.strip().split("\n")
        for line in lines:
            if line.startswith("ACTION:"):
                decision["action"] = line.replace("ACTION:", "").strip()
            elif line.startswith("REASON:"):
                decision["reason"] = line.replace("REASON:", "").strip()
            elif line.startswith("URGENCY:"):
                decision["urgency"] = line.replace("URGENCY:", "").strip().lower()
            elif line.startswith("CONTENT:"):
                content = line.replace("CONTENT:", "").strip()
                if content and content != "N/A":
                    decision["content"] = content

        return decision

    def _should_act(self, decision: Dict) -> bool:
        """Final check before acting."""

        action = decision.get("action", "STAY_QUIET")
        urgency = decision.get("urgency", "low")

        # Don't act on STAY_QUIET
        if action == "STAY_QUIET":
            return False

        now = datetime.now(ISRAEL_TZ)

        # Night mode - only critical actions
        if now.hour >= 23 or now.hour < 8:
            if urgency not in ["critical", "high"]:
                logger.info("Night mode - skipping non-critical action")
                return False

        # Spam prevention - max 3 messages/day unless critical
        if self.messages_sent_today >= 3 and urgency != "critical":
            logger.info("Daily limit reached - skipping non-critical action")
            return False

        # User not responding - back off
        if self.unanswered_messages >= 3 and urgency not in ["critical", "high"]:
            logger.info("User unresponsive - backing off")
            return False

        # Minimum time between messages (30 minutes unless high urgency)
        if self.last_message_time:
            minutes_since = (now - self.last_message_time).total_seconds() / 60
            if minutes_since < 30 and urgency not in ["critical", "high"]:
                logger.info(f"Too soon since last message ({minutes_since:.0f} min)")
                return False

        return True

    async def _execute_action(self, decision: Dict) -> bool:
        """Execute the decided action."""

        action = decision.get("action")
        content = decision.get("content")

        logger.info(f"Executing action: {action}")

        try:
            # Import here to avoid circular imports
            from .integrations.whatsapp import whatsapp

            if action == "SEND_IDEA":
                return await self._send_idea_message()

            elif action == "SEND_TREND_ALERT":
                return await self._send_trend_alert()

            elif action == "SEND_MOTIVATION":
                message = content or self.personality.get_motivation_message()
                return self._send_message(message)

            elif action == "SEND_REMINDER":
                message = content or self.personality.get_reminder_message()
                return self._send_message(message)

            elif action == "SEND_PERFORMANCE_UPDATE":
                return await self._send_performance_update()

            elif action == "SEND_GOAL_UPDATE":
                return await self._send_goal_update()

            else:
                logger.warning(f"Unknown action: {action}")
                return False

        except Exception as e:
            logger.error(f"Action execution error: {e}")
            return False

    def _send_message(self, message: str) -> bool:
        """Send a WhatsApp message."""
        from .integrations.whatsapp import whatsapp

        # Apply personality to message
        styled_message = self.personality.style_message(message)

        sid = whatsapp.send_message(styled_message)
        if sid:
            self.unanswered_messages += 1
            return True
        return False

    async def _send_idea_message(self) -> bool:
        """Generate and send an idea."""
        from .skills import IdeaEngine

        engine = IdeaEngine()
        result = await engine.execute(count=1)
        ideas = result.get("ideas", [])

        if not ideas:
            return False

        idea = ideas[0]
        message = f"""💡 *רעיון לתוכן!*

*{idea.get('title', '')}*

🎬 "{idea.get('hook', '')}"

{idea.get('description', '')}

⏰ זמן טוב להעלות: {idea.get('best_time', '18:00-20:00')}

---
רוצה עוד רעיון? שלח "עוד" 🔄"""

        return self._send_message(message)

    async def _send_trend_alert(self) -> bool:
        """Send a trend alert."""
        from .skills import TrendRadar

        radar = TrendRadar()
        result = await radar.execute(max_trends=1)
        trends = result.get("relevant_trends", [])

        if not trends:
            return False

        trend = trends[0]
        message = f"""🔥 *טרנד חם עכשיו!*

*{trend.get('title', '')}*

💡 *הזדמנות:* {trend.get('content_opportunity', '')}

⏰ זה הזמן לעשות תוכן על זה!

---
מעוניין? שלח "רעיון" לקבל פירוט"""

        return self._send_message(message)

    async def _send_performance_update(self) -> bool:
        """Send performance update."""
        performance = await self._get_recent_performance()

        if not performance:
            return False

        message = f"""📊 *עדכון ביצועים*

השבוע עד עכשיו:
👁️ צפיות: {performance.get('total_views', 0):,}
❤️ לייקים: {performance.get('total_likes', 0):,}
📈 שינוי: {performance.get('change_percent', 0):+.1f}%

{self._get_performance_comment(performance)}"""

        return self._send_message(message)

    async def _send_goal_update(self) -> bool:
        """Send goal progress update."""
        progress = self.goals.get_progress_summary()

        message = f"""🎯 *התקדמות ביעדים*

{self.goals.format_progress_message()}

{self._get_goal_encouragement(progress)}"""

        return self._send_message(message)

    def _learn_from_cycle(self, context: Dict, decision: Optional[Dict], results: Dict):
        """Learn from this thinking cycle."""

        # Store decision in history
        self.decision_history.append({
            "timestamp": datetime.now(ISRAEL_TZ).isoformat(),
            "context_summary": {
                "hour": context.get("hour"),
                "hours_since_post": context.get("hours_since_tiktok"),
                "opportunities_count": len(context.get("opportunities", [])),
                "problems_count": len(context.get("problems", [])),
            },
            "decision": decision,
            "executed": results.get("action_executed", False),
        })

        # Keep only last 100 decisions
        if len(self.decision_history) > 100:
            self.decision_history = self.decision_history[-100:]

        # Update memory with patterns
        if decision and results.get("action_executed"):
            self.memory.record_action(
                action=decision.get("action"),
                hour=context.get("hour"),
                day=context.get("day_of_week"),
                context_type=self._get_context_type(context),
            )

    def reset_daily_counters(self):
        """Reset daily counters (call at midnight)."""
        self.messages_sent_today = 0

    def on_user_response(self):
        """Call when user responds to a message."""
        self.unanswered_messages = 0

    # Helper methods

    def _get_hebrew_day(self, weekday: int) -> str:
        """Convert weekday to Hebrew."""
        days = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
        return days[weekday]

    async def _get_last_post(self, platform: str) -> Optional[Dict]:
        """Get the last post for a platform."""
        session = db.get_session()
        try:
            post = session.query(Post).filter(
                Post.platform == platform
            ).order_by(Post.posted_at.desc()).first()

            if post:
                return {
                    "id": post.id,
                    "caption": post.caption[:50] if post.caption else "",
                    "posted_at": post.posted_at,
                    "views": post.views,
                    "likes": post.likes,
                }
            return None
        finally:
            session.close()

    async def _hours_since_last_post(self, platform: str) -> Optional[float]:
        """Get hours since last post."""
        session = db.get_session()
        try:
            post = session.query(Post).filter(
                Post.platform == platform
            ).order_by(Post.posted_at.desc()).first()

            if post and post.posted_at:
                delta = datetime.utcnow() - post.posted_at
                return delta.total_seconds() / 3600
            return None
        finally:
            session.close()

    async def _get_recent_performance(self) -> Dict:
        """Get recent performance metrics."""
        session = db.get_session()
        try:
            week_ago = datetime.utcnow() - timedelta(days=7)
            two_weeks_ago = datetime.utcnow() - timedelta(days=14)

            # This week
            this_week = session.query(Post).filter(
                Post.posted_at >= week_ago
            ).all()

            # Last week for comparison
            last_week = session.query(Post).filter(
                Post.posted_at >= two_weeks_ago,
                Post.posted_at < week_ago
            ).all()

            this_views = sum(p.views or 0 for p in this_week)
            this_likes = sum(p.likes or 0 for p in this_week)
            last_views = sum(p.views or 0 for p in last_week)

            change = ((this_views - last_views) / last_views * 100) if last_views > 0 else 0

            return {
                "total_views": this_views,
                "total_likes": this_likes,
                "posts_count": len(this_week),
                "change_percent": change,
            }
        finally:
            session.close()

    async def _get_trending_posts(self) -> List[Dict]:
        """Get posts that are performing above average."""
        session = db.get_session()
        try:
            # Get average views
            posts = session.query(Post).filter(
                Post.posted_at >= datetime.utcnow() - timedelta(days=30)
            ).all()

            if not posts:
                return []

            avg_views = sum(p.views or 0 for p in posts) / len(posts)

            # Find posts doing better than average
            trending = []
            recent_posts = session.query(Post).filter(
                Post.posted_at >= datetime.utcnow() - timedelta(days=3)
            ).all()

            for post in recent_posts:
                if post.views and post.views > avg_views * 1.5:
                    trending.append({
                        "id": post.id,
                        "caption": post.caption[:50] if post.caption else "",
                        "views": post.views,
                        "multiplier": post.views / avg_views if avg_views > 0 else 1,
                    })

            return sorted(trending, key=lambda x: x["multiplier"], reverse=True)
        finally:
            session.close()

    async def _calculate_engagement_trend(self) -> str:
        """Calculate if engagement is improving, stable, or declining."""
        performance = await self._get_recent_performance()
        change = performance.get("change_percent", 0)

        if change > 10:
            return "improving"
        elif change < -10:
            return "declining"
        else:
            return "stable"

    async def _get_hot_trends(self) -> List[Dict]:
        """Get current hot trends."""
        session = db.get_session()
        try:
            trends = session.query(Trend).filter(
                Trend.discovered_at >= datetime.utcnow() - timedelta(hours=12),
                Trend.relevance_score >= 0.7
            ).order_by(Trend.relevance_score.desc()).limit(5).all()

            return [
                {
                    "id": t.id,
                    "title": t.title,
                    "relevance": t.relevance_score,
                    "opportunity": t.content_opportunity,
                }
                for t in trends
            ]
        finally:
            session.close()

    async def _get_news_opportunities(self) -> List[Dict]:
        """Get news items that could be content opportunities."""
        # Similar to hot trends but from news sources
        return await self._get_hot_trends()

    def _estimate_user_mood(self) -> str:
        """Estimate user's likely mood based on patterns."""
        # Based on recent interactions
        return self.memory.get_estimated_mood()

    async def _get_last_interaction(self) -> Optional[datetime]:
        """Get timestamp of last user interaction."""
        session = db.get_session()
        try:
            conv = session.query(Conversation).filter(
                Conversation.direction == "incoming"
            ).order_by(Conversation.created_at.desc()).first()

            return conv.created_at if conv else None
        finally:
            session.close()

    def _get_user_response_rate(self) -> float:
        """Get user's response rate to messages."""
        return self.memory.get_response_rate()

    def _get_context_type(self, context: Dict) -> str:
        """Categorize the context type for learning."""
        if context.get("is_prime_time"):
            return "prime_time"
        elif context.get("is_weekend"):
            return "weekend"
        elif context.get("is_night"):
            return "night"
        else:
            return "regular"

    def _get_performance_comment(self, performance: Dict) -> str:
        """Get a comment about performance."""
        change = performance.get("change_percent", 0)
        if change > 20:
            return "🚀 שבוע מעולה! ממשיכים ככה!"
        elif change > 0:
            return "📈 מגמה חיובית, כל הכבוד!"
        elif change > -10:
            return "➡️ יציב. בוא נשפר!"
        else:
            return "📉 יש מקום לשיפור. בוא נעבוד על זה!"

    def _get_goal_encouragement(self, progress: Dict) -> str:
        """Get encouragement based on goal progress."""
        pct = progress.get("percentage", 0)
        if pct >= 100:
            return "🎉 השגת את היעד! מדהים!"
        elif pct >= 80:
            return "💪 כמעט שם! עוד קצת!"
        elif pct >= 50:
            return "👍 באמצע הדרך, ממשיכים!"
        else:
            return "🚀 יש עבודה, אבל אתה יכול!"
