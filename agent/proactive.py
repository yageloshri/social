"""
ProactiveAgent
==============
Takes actions automatically without being asked.
Handles morning routines, opportunity scanning, evening reflections, and weekly planning.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import pytz

from anthropic import Anthropic

from .config import config
from .database import db, Post, Trend, Idea, Message
from .integrations.whatsapp import whatsapp

logger = logging.getLogger(__name__)

ISRAEL_TZ = pytz.timezone("Asia/Jerusalem")


class ProactiveAgent:
    """
    Takes actions automatically without being asked.

    Scheduled actions:
    - Morning routine (8:00): Scan, analyze, plan
    - Opportunity scanner (every 30 min): Look for golden moments
    - Evening reflection (22:00): Analyze day, plan tomorrow
    - Weekly strategy (Sunday 10:00): Deep analysis + weekly plan
    """

    def __init__(self, brain, memory, goals, personality):
        self.brain = brain
        self.memory = memory
        self.goals = goals
        self.personality = personality
        self.client = Anthropic(api_key=config.ai.api_key) if config.ai.api_key else None

    async def morning_routine(self) -> Dict[str, Any]:
        """
        Morning routine - runs at 8:00 AM.

        1. Scan profiles for new posts
        2. Check overnight trends
        3. Analyze what happened overnight
        4. Generate personalized morning message
        """
        logger.info("Starting morning routine...")

        results = {
            "executed_at": datetime.now(ISRAEL_TZ).isoformat(),
            "message_sent": False,
        }

        try:
            # 1. Gather overnight data
            overnight_data = await self._gather_overnight_data()
            results["overnight_data"] = overnight_data

            # 2. Check for hot trends
            hot_trends = await self._check_overnight_trends()
            results["trends_found"] = len(hot_trends)

            # 3. Analyze performance of recent posts
            performance = await self._analyze_overnight_performance()
            results["performance"] = performance

            # 4. Generate morning message
            should_send, message = await self._generate_morning_message(
                overnight_data, hot_trends, performance
            )

            # 5. Send if appropriate
            if should_send:
                sid = whatsapp.send_message(message)
                results["message_sent"] = bool(sid)
                if sid:
                    self.brain.messages_sent_today += 1

            logger.info(f"Morning routine complete: sent={results['message_sent']}")

        except Exception as e:
            logger.error(f"Morning routine error: {e}")
            results["error"] = str(e)

        return results

    async def _gather_overnight_data(self) -> Dict:
        """Gather data from overnight period."""
        session = db.get_session()
        try:
            # Posts from last 12 hours
            cutoff = datetime.utcnow() - timedelta(hours=12)

            new_posts = session.query(Post).filter(
                Post.posted_at >= cutoff
            ).all()

            # Views/engagement changes
            return {
                "new_posts": len(new_posts),
                "posts": [
                    {
                        "caption": p.caption[:30] if p.caption else "",
                        "views": p.views,
                        "likes": p.likes,
                    }
                    for p in new_posts
                ],
            }
        finally:
            session.close()

    async def _check_overnight_trends(self) -> List[Dict]:
        """Check for hot trends from overnight."""
        session = db.get_session()
        try:
            cutoff = datetime.utcnow() - timedelta(hours=12)

            trends = session.query(Trend).filter(
                Trend.discovered_at >= cutoff,
                Trend.relevance_score >= 0.7
            ).order_by(Trend.relevance_score.desc()).limit(5).all()

            return [
                {
                    "title": t.title,
                    "relevance": t.relevance_score,
                    "opportunity": t.content_opportunity,
                }
                for t in trends
            ]
        finally:
            session.close()

    async def _analyze_overnight_performance(self) -> Dict:
        """Analyze how recent posts performed overnight."""
        session = db.get_session()
        try:
            # Get posts from last 3 days
            cutoff = datetime.utcnow() - timedelta(days=3)

            posts = session.query(Post).filter(
                Post.posted_at >= cutoff
            ).all()

            if not posts:
                return {"has_data": False}

            # Calculate metrics
            total_views = sum(p.views or 0 for p in posts)
            total_likes = sum(p.likes or 0 for p in posts)
            avg_engagement = (total_likes / total_views * 100) if total_views > 0 else 0

            # Find standout posts
            avg_views = total_views / len(posts) if posts else 0
            standouts = [
                p for p in posts
                if p.views and p.views > avg_views * 1.5
            ]

            return {
                "has_data": True,
                "total_views": total_views,
                "total_likes": total_likes,
                "avg_engagement": avg_engagement,
                "standout_count": len(standouts),
            }
        finally:
            session.close()

    async def _generate_morning_message(
        self,
        overnight_data: Dict,
        trends: List[Dict],
        performance: Dict
    ) -> tuple[bool, str]:
        """Generate personalized morning message."""

        # Decide if we should send a morning message
        # Don't send if nothing interesting happened
        if not trends and not performance.get("standout_count"):
            if not overnight_data.get("new_posts"):
                # Nothing new - maybe just send a tip
                if datetime.now(ISRAEL_TZ).weekday() < 5:  # Weekday
                    tip = self.personality.get_daily_tip()
                    return True, f"{self.personality.get_time_greeting()}\n\n{tip}\n\nצריך רעיון? שלח 'רעיון' 💡"
                else:
                    return False, ""

        # Build the message
        parts = [self.personality.get_time_greeting()]

        # Add performance update if relevant
        if performance.get("has_data"):
            if performance.get("standout_count", 0) > 0:
                parts.append(f"🌟 יש לך {performance['standout_count']} פוסטים שעושים מעל הממוצע!")

            parts.append(f"📊 סה\"כ {self.personality.format_number(performance['total_views'])} צפיות בימים האחרונים")

        # Add trend alert if relevant
        if trends:
            best_trend = trends[0]
            parts.append(f"\n🔥 *טרנד חם:* {best_trend['title']}")
            if best_trend.get("opportunity"):
                parts.append(f"💡 {best_trend['opportunity']}")

        # Add goals reminder
        progress = self.goals.get_progress_summary()
        if progress.get("behind"):
            parts.append(f"\n🎯 יש עוד עבודה על היעדים השבועיים ({progress['percentage']:.0f}%)")

        # Add call to action
        if trends:
            parts.append("\nרוצה רעיון? שלח 'רעיון' 💡")
        else:
            parts.append("\nשיהיה יום מעולה! 🚀")

        message = "\n".join(parts)
        return True, message

    async def opportunity_scanner(self) -> Dict[str, Any]:
        """
        Opportunity scanner - runs every 30 minutes.

        Looks for:
        - Golden moments (hot trend + no recent post)
        - Viral posts that need attention
        - Posting reminders if too long without content
        """
        logger.info("Scanning for opportunities...")

        results = {
            "scanned_at": datetime.now(ISRAEL_TZ).isoformat(),
            "opportunity_found": False,
            "action_taken": None,
        }

        try:
            # Check for golden moments
            golden = await self._check_golden_moment()
            if golden:
                results["opportunity_found"] = True
                results["opportunity_type"] = "golden_moment"
                action = await self._handle_golden_moment(golden)
                results["action_taken"] = action
                return results

            # Check if any post is going viral
            viral = await self._check_virality()
            if viral:
                results["opportunity_found"] = True
                results["opportunity_type"] = "viral_post"
                action = await self._handle_viral_alert(viral)
                results["action_taken"] = action
                return results

            # Check if should remind about posting
            if await self._should_remind_posting():
                results["opportunity_found"] = True
                results["opportunity_type"] = "posting_reminder"
                action = await self._send_gentle_reminder()
                results["action_taken"] = action
                return results

            logger.info("No opportunities found this scan")

        except Exception as e:
            logger.error(f"Opportunity scanner error: {e}")
            results["error"] = str(e)

        return results

    async def _check_golden_moment(self) -> Optional[Dict]:
        """Check if there's a golden moment opportunity."""
        now = datetime.now(ISRAEL_TZ)

        # Only during prime time
        if not (16 <= now.hour <= 21):
            return None

        # Check if posted recently
        hours_since = await self.brain._hours_since_last_post("tiktok")
        if hours_since and hours_since < 20:
            return None

        # Check for hot trends
        trends = await self.brain._get_hot_trends()
        if trends:
            return {
                "trend": trends[0],
                "hours_since_post": hours_since,
            }

        return None

    async def _handle_golden_moment(self, golden: Dict) -> str:
        """Handle a golden moment opportunity."""
        trend = golden.get("trend", {})

        message = f"""🚨 *רגע זהב!*

יש טרנד חם עכשיו: *{trend.get('title', '')}*

💡 *הזדמנות:* {trend.get('opportunity', 'תוכן על הנושא הזה')}

⏰ עכשיו זה הזמן לעשות תוכן על זה!

---
מעוניין? שלח 'רעיון' לקבל פירוט
לא עכשיו? שלח 'אחר כך'"""

        sid = whatsapp.send_message(message)
        if sid:
            self.brain.messages_sent_today += 1
            self.brain.unanswered_messages += 1
            return "alert_sent"

        return "send_failed"

    async def _check_virality(self) -> Optional[Dict]:
        """Check if any recent post is going viral."""
        session = db.get_session()
        try:
            # Get posts from last 24 hours
            cutoff = datetime.utcnow() - timedelta(hours=24)

            posts = session.query(Post).filter(
                Post.posted_at >= cutoff
            ).all()

            if not posts:
                return None

            # Get average views
            avg_posts = session.query(Post).filter(
                Post.posted_at >= datetime.utcnow() - timedelta(days=30)
            ).all()

            if not avg_posts:
                return None

            avg_views = sum(p.views or 0 for p in avg_posts) / len(avg_posts)

            # Find viral posts (more than 2x average)
            for post in posts:
                if post.views and post.views > avg_views * 2:
                    multiplier = post.views / avg_views
                    return {
                        "post": post,
                        "multiplier": multiplier,
                        "views": post.views,
                        "avg_views": avg_views,
                    }

            return None

        finally:
            session.close()

    async def _handle_viral_alert(self, viral: Dict) -> str:
        """Handle a viral post alert."""
        post = viral.get("post")
        multiplier = viral.get("multiplier", 1)

        caption = post.caption[:30] if post.caption else "הפוסט"

        message = f"""🚀 *הפוסט שלך הולך ויראלי!*

*"{caption}..."*

📊 *{viral['views']:,}* צפיות (פי {multiplier:.1f} מהממוצע!)

💡 *טיפים לרגע הזה:*
1. תענה לתגובות - זה מגביר חשיפה
2. תעלה עוד תוכן בנושא דומה
3. תעשה המשך/חלק 2

רוצה רעיון להמשך? שלח 'רעיון' 🔥"""

        sid = whatsapp.send_message(message)
        if sid:
            self.brain.messages_sent_today += 1
            return "alert_sent"

        return "send_failed"

    async def _should_remind_posting(self) -> bool:
        """Check if we should remind about posting."""
        # Don't remind too often
        if self.brain.messages_sent_today >= 2:
            return False

        # Check hours since last post
        hours_since = await self.brain._hours_since_last_post("tiktok")

        # Remind after 48 hours
        if hours_since and hours_since > 48:
            return True

        return False

    async def _send_gentle_reminder(self) -> str:
        """Send a gentle reminder to post."""
        message = self.personality.get_reminder_message()
        message += "\n\nרוצה רעיון? שלח 'רעיון' 💡"

        sid = whatsapp.send_message(message)
        if sid:
            self.brain.messages_sent_today += 1
            self.brain.unanswered_messages += 1
            return "reminder_sent"

        return "send_failed"

    async def end_of_day_reflection(self) -> Dict[str, Any]:
        """
        End of day reflection - runs at 22:00.

        1. Analyze today's performance
        2. Generate insights
        3. Plan for tomorrow
        4. Send summary if meaningful
        """
        logger.info("Starting end of day reflection...")

        results = {
            "executed_at": datetime.now(ISRAEL_TZ).isoformat(),
            "message_sent": False,
        }

        try:
            # 1. Analyze today
            today_analysis = await self._analyze_today()
            results["today"] = today_analysis

            # 2. Generate insights
            insights = await self._generate_insights(today_analysis)
            results["insights"] = insights

            # 3. Plan tomorrow
            tomorrow_plan = await self._plan_tomorrow(today_analysis)
            results["tomorrow_plan"] = tomorrow_plan

            # 4. Send summary only if meaningful
            if today_analysis.get("posts_count", 0) > 0 or insights:
                message = self._format_evening_summary(today_analysis, insights, tomorrow_plan)
                sid = whatsapp.send_message(message)
                results["message_sent"] = bool(sid)

            logger.info(f"End of day reflection complete: sent={results['message_sent']}")

        except Exception as e:
            logger.error(f"End of day reflection error: {e}")
            results["error"] = str(e)

        return results

    async def _analyze_today(self) -> Dict:
        """Analyze today's activity and performance."""
        session = db.get_session()
        try:
            today = datetime.utcnow().date()
            start_of_day = datetime.combine(today, datetime.min.time())

            posts = session.query(Post).filter(
                Post.posted_at >= start_of_day
            ).all()

            return {
                "posts_count": len(posts),
                "total_views": sum(p.views or 0 for p in posts),
                "total_likes": sum(p.likes or 0 for p in posts),
                "posts": [
                    {
                        "caption": p.caption[:30] if p.caption else "",
                        "views": p.views,
                        "likes": p.likes,
                    }
                    for p in posts
                ],
            }
        finally:
            session.close()

    async def _generate_insights(self, today: Dict) -> List[str]:
        """Generate insights from today's data."""
        insights = []

        if today["posts_count"] == 0:
            insights.append("לא הועלה תוכן היום")
        elif today["posts_count"] >= 2:
            insights.append(f"יום פרודוקטיבי! {today['posts_count']} פוסטים")

        if today["total_views"] > 10000:
            insights.append(f"יום חזק! {today['total_views']:,} צפיות")

        return insights

    async def _plan_tomorrow(self, today: Dict) -> Dict:
        """Create a simple plan for tomorrow."""
        return {
            "goal": "להעלות לפחות פוסט אחד",
            "best_time": "18:00-20:00",
            "suggestion": "לבדוק טרנדים בבוקר",
        }

    def _format_evening_summary(self, today: Dict, insights: List[str], tomorrow: Dict) -> str:
        """Format the evening summary message."""
        parts = ["🌙 *סיכום היום:*\n"]

        if today["posts_count"] > 0:
            parts.append(f"📱 פוסטים: {today['posts_count']}")
            parts.append(f"👁️ צפיות: {today['total_views']:,}")
            parts.append(f"❤️ לייקים: {today['total_likes']:,}")
        else:
            parts.append("לא הועלה תוכן היום")

        if insights:
            parts.append(f"\n💡 *תובנות:*")
            for insight in insights:
                parts.append(f"• {insight}")

        parts.append(f"\n📋 *למחר:*")
        parts.append(f"🎯 {tomorrow['goal']}")
        parts.append(f"⏰ זמן מומלץ: {tomorrow['best_time']}")

        parts.append("\nלילה טוב! 🌙")

        return "\n".join(parts)

    async def weekly_strategy_session(self) -> Dict[str, Any]:
        """
        Weekly strategy session - runs Sunday at 10:00.

        1. Deep analysis of past week
        2. Identify winning formula
        3. Set goals for next week
        4. Create content calendar
        """
        logger.info("Starting weekly strategy session...")

        results = {
            "executed_at": datetime.now(ISRAEL_TZ).isoformat(),
            "message_sent": False,
        }

        try:
            # 1. Deep analysis
            week_analysis = await self._deep_week_analysis()
            results["analysis"] = week_analysis

            # 2. Find winning formula
            formula = await self._identify_winning_formula(week_analysis)
            results["formula"] = formula

            # 3. Set goals
            goals = self._set_weekly_goals(week_analysis)
            results["goals"] = goals

            # 4. Create plan
            plan = await self._create_weekly_plan(week_analysis, formula)
            results["plan"] = plan

            # 5. Send comprehensive message
            message = self._format_weekly_strategy(week_analysis, formula, goals, plan)
            sid = whatsapp.send_message(message)
            results["message_sent"] = bool(sid)

            # Reset goals for new week
            self.goals.reset_weekly()

            logger.info(f"Weekly strategy complete: sent={results['message_sent']}")

        except Exception as e:
            logger.error(f"Weekly strategy error: {e}")
            results["error"] = str(e)

        return results

    async def _deep_week_analysis(self) -> Dict:
        """Deep analysis of the past week."""
        session = db.get_session()
        try:
            week_ago = datetime.utcnow() - timedelta(days=7)

            posts = session.query(Post).filter(
                Post.posted_at >= week_ago
            ).all()

            if not posts:
                return {"has_data": False, "posts_count": 0}

            total_views = sum(p.views or 0 for p in posts)
            total_likes = sum(p.likes or 0 for p in posts)

            # Find best post
            best_post = max(posts, key=lambda p: p.views or 0) if posts else None

            # Analyze by day
            by_day = {}
            for post in posts:
                if post.posted_at:
                    day = post.posted_at.strftime("%A")
                    if day not in by_day:
                        by_day[day] = []
                    by_day[day].append(post.views or 0)

            best_day = max(by_day.keys(), key=lambda d: sum(by_day[d])) if by_day else None

            return {
                "has_data": True,
                "posts_count": len(posts),
                "total_views": total_views,
                "total_likes": total_likes,
                "avg_views": total_views / len(posts) if posts else 0,
                "best_post": {
                    "caption": best_post.caption[:30] if best_post and best_post.caption else "",
                    "views": best_post.views if best_post else 0,
                } if best_post else None,
                "best_day": best_day,
            }
        finally:
            session.close()

    async def _identify_winning_formula(self, analysis: Dict) -> Dict:
        """Identify what's working based on analysis."""
        if not analysis.get("has_data"):
            return {}

        return {
            "best_day": analysis.get("best_day"),
            "avg_performance": analysis.get("avg_views", 0),
            "recommendation": f"תמשיך עם {analysis.get('best_day', 'יום ראשון')} - זה עובד!"
        }

    def _set_weekly_goals(self, analysis: Dict) -> Dict:
        """Set goals for next week based on analysis."""
        base_posts = 5
        if analysis.get("posts_count", 0) >= 5:
            base_posts = min(7, analysis["posts_count"] + 1)

        return {
            "posts_target": base_posts,
            "views_target": int(analysis.get("avg_views", 1000) * base_posts * 1.1),
        }

    async def _create_weekly_plan(self, analysis: Dict, formula: Dict) -> Dict:
        """Create a content plan for the week."""
        return {
            "monday": "תוכן מעורר (שאלה/דעה)",
            "tuesday": "טרנד או תגובה",
            "wednesday": "תוכן אישי/אותנטי",
            "thursday": "סטורי טיימ או טיפ",
            "friday": "תוכן קליל לסופ\"ש",
        }

    def _format_weekly_strategy(
        self,
        analysis: Dict,
        formula: Dict,
        goals: Dict,
        plan: Dict
    ) -> str:
        """Format the weekly strategy message."""
        parts = ["📊 *סיכום שבועי + תוכנית!*\n"]

        if analysis.get("has_data"):
            parts.append("*השבוע שעבר:*")
            parts.append(f"📱 {analysis['posts_count']} פוסטים")
            parts.append(f"👁️ {analysis['total_views']:,} צפיות")
            parts.append(f"📈 ממוצע: {int(analysis['avg_views']):,} לפוסט")

            if analysis.get("best_post"):
                parts.append(f"\n🏆 *הפוסט הכי טוב:*")
                parts.append(f"'{analysis['best_post']['caption']}...' ({analysis['best_post']['views']:,})")

        parts.append(f"\n🎯 *יעדים לשבוע:*")
        parts.append(f"• {goals['posts_target']} פוסטים")
        parts.append(f"• {goals['views_target']:,} צפיות")

        if formula.get("recommendation"):
            parts.append(f"\n💡 *טיפ:* {formula['recommendation']}")

        parts.append("\nשבוע מעולה! 🚀")

        return "\n".join(parts)
