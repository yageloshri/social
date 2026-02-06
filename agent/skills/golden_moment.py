"""
GoldenMomentDetector Skill
==========================
Detects perfect content opportunities and sends urgent alerts.

A "Golden Moment" requires ALL of these conditions:
1. Hot trend (relevance_score > 0.9) matching creator's style
2. Optimal posting time (default: 18:00-21:00, Sun-Thu)
3. Creator hasn't posted in last 20 hours
4. Trend is fresh (appeared in last 6 hours)
5. Not already alerted about this trend
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging
import pytz

from anthropic import Anthropic

from .base import BaseSkill
from ..config import config
from ..database import db, Post, Trend, GoldenMomentAlert, TopicWeight
from ..integrations.whatsapp import whatsapp

logger = logging.getLogger(__name__)

# Israel timezone
ISRAEL_TZ = pytz.timezone("Asia/Jerusalem")


class GoldenMomentDetector(BaseSkill):
    """
    Detects and alerts on perfect content opportunities.

    Runs every 30 minutes during optimal hours (16:00-21:00).
    Sends urgent WhatsApp alerts when all conditions are met.

    Cooldown rules:
    - Max 2 alerts per day
    - Minimum 3 hours between alerts
    - Learns from which alerts were used vs ignored
    """

    def __init__(self):
        super().__init__("GoldenMomentDetector")
        self.client = Anthropic(api_key=config.ai.api_key) if config.ai.api_key else None

        # Default optimal times (can be learned from data)
        self.optimal_hours = range(18, 22)  # 18:00-21:00
        self.optimal_days = [0, 1, 2, 3, 6]  # Mon-Thu, Sun (0=Mon, 6=Sun)

        # Alert limits
        self.max_alerts_per_day = 2
        self.min_hours_between_alerts = 3
        self.trend_freshness_hours = 6
        self.no_post_threshold_hours = 20

    async def execute(self, force: bool = False) -> Dict[str, Any]:
        """
        Check for golden moments and send alerts if conditions are met.

        Args:
            force: If True, skip time and cooldown checks (for testing)

        Returns:
            Dict with check results
        """
        self.log_start()

        results = {
            "checked": True,
            "golden_moment_found": False,
            "alert_sent": False,
            "reason_skipped": None,
            "trend": None,
        }

        try:
            # Check if we're in optimal time window (unless forced)
            if not force and not self._is_optimal_time():
                results["reason_skipped"] = "not_optimal_time"
                self.log_complete(results)
                return results

            # Check cooldown rules
            if not force and not self._can_send_alert():
                results["reason_skipped"] = "cooldown_active"
                self.log_complete(results)
                return results

            # Check if posted today
            posted_recently = await self._check_if_posted_recently()
            if posted_recently:
                results["reason_skipped"] = "already_posted_today"
                self.log_complete(results)
                return results

            # Get fresh, high-relevance trends
            golden_trends = await self._get_golden_trends()

            if not golden_trends:
                results["reason_skipped"] = "no_golden_trends"
                self.log_complete(results)
                return results

            # We have a golden moment!
            best_trend = golden_trends[0]
            results["golden_moment_found"] = True
            results["trend"] = {
                "topic": best_trend.title,
                "relevance": best_trend.relevance_score,
                "source": best_trend.source,
            }

            # Generate quick idea for the trend
            idea = await self._generate_quick_idea(best_trend)

            # Send alert
            alert_sent = await self._send_golden_moment_alert(best_trend, idea)
            results["alert_sent"] = alert_sent

            if alert_sent:
                # Record the alert
                await self._record_alert(best_trend, idea)

            results["summary"] = f"Golden moment: {best_trend.title}" if alert_sent else "Checked, no alert sent"
            self.log_complete(results)

        except Exception as e:
            self.log_error(e)
            results["error"] = str(e)

        return results

    def _is_optimal_time(self) -> bool:
        """Check if current time is optimal for posting."""
        now = datetime.now(ISRAEL_TZ)
        hour = now.hour
        day = now.weekday()

        return hour in self.optimal_hours and day in self.optimal_days

    def _can_send_alert(self) -> bool:
        """Check cooldown rules - max alerts per day and minimum gap."""
        session = db.get_session()
        try:
            # Check alerts in last 24 hours
            cutoff_day = datetime.utcnow() - timedelta(hours=24)
            alerts_today = session.query(GoldenMomentAlert).filter(
                GoldenMomentAlert.alert_sent_at >= cutoff_day
            ).count()

            if alerts_today >= self.max_alerts_per_day:
                logger.info(f"Max alerts reached ({alerts_today}/{self.max_alerts_per_day})")
                return False

            # Check last alert time
            cutoff_gap = datetime.utcnow() - timedelta(hours=self.min_hours_between_alerts)
            recent_alert = session.query(GoldenMomentAlert).filter(
                GoldenMomentAlert.alert_sent_at >= cutoff_gap
            ).first()

            if recent_alert:
                logger.info(f"Alert sent recently, waiting for cooldown")
                return False

            return True

        finally:
            session.close()

    async def _check_if_posted_recently(self) -> bool:
        """Check if creator posted in the last 20 hours."""
        session = db.get_session()
        try:
            cutoff = datetime.utcnow() - timedelta(hours=self.no_post_threshold_hours)

            recent_post = session.query(Post).filter(
                Post.posted_at >= cutoff
            ).first()

            return recent_post is not None

        finally:
            session.close()

    async def _get_golden_trends(self) -> List[Trend]:
        """
        Get trends that qualify as golden moments.

        Requirements:
        - relevance_score > 0.9 (adjusted by topic weights)
        - Discovered in last 6 hours
        - Not already alerted
        """
        session = db.get_session()
        try:
            # Get fresh trends
            freshness_cutoff = datetime.utcnow() - timedelta(hours=self.trend_freshness_hours)

            fresh_trends = session.query(Trend).filter(
                Trend.discovered_at >= freshness_cutoff,
                Trend.relevance_score >= 70,  # Base threshold before weighting
                Trend.status.in_(["new", "notified"])
            ).order_by(Trend.relevance_score.desc()).all()

            # Get already alerted trend IDs
            alerted_ids = set()
            recent_alerts = session.query(GoldenMomentAlert).filter(
                GoldenMomentAlert.alert_sent_at >= freshness_cutoff
            ).all()
            for alert in recent_alerts:
                if alert.trend_id:
                    alerted_ids.add(alert.trend_id)

            # Filter and apply topic weights
            golden_trends = []
            for trend in fresh_trends:
                # Skip already alerted
                if trend.id in alerted_ids:
                    continue

                # Apply topic weight
                weighted_score = self._apply_topic_weight(trend)

                if weighted_score >= 90:  # Golden threshold after weighting
                    trend._weighted_score = weighted_score
                    golden_trends.append(trend)

            # Sort by weighted score
            golden_trends.sort(key=lambda t: getattr(t, '_weighted_score', 0), reverse=True)

            return golden_trends

        finally:
            session.close()

    def _apply_topic_weight(self, trend: Trend) -> float:
        """Apply learned topic weights to relevance score."""
        session = db.get_session()
        try:
            base_score = trend.relevance_score or 0

            # Check keywords in trend for topic weights
            trend_text = f"{trend.title} {trend.summary or ''}".lower()

            # Get all topic weights
            weights = session.query(TopicWeight).all()

            multiplier = 1.0
            for weight in weights:
                if weight.topic.lower() in trend_text:
                    multiplier *= weight.weight

            return min(base_score * multiplier, 100)

        finally:
            session.close()

    async def _generate_quick_idea(self, trend: Trend) -> Dict[str, Any]:
        """Generate a quick content idea for the trend."""
        if not self.client:
            return {
                "title": f"תגובה ל-{trend.title}",
                "hook": "...",
                "steps": ["צלם תגובה מהירה", "הוסף דעה אישית", "סיים עם קריאה לתגובות"],
                "hashtags": ["#טרנד", "#תגובה"],
            }

        prompt = f"""אתה עוזר ליוצר תוכן ישראלי (מוזיקאי, תוכן זוגיות, סטורי טיימס).

יש טרנד חם עכשיו:
כותרת: {trend.title}
תקציר: {trend.summary or 'אין תקציר'}

צור רעיון מהיר לסרטון תגובה/תוכן רלוונטי.
פורמט JSON בלבד:
{{
    "title": "כותרת קצרה לרעיון",
    "hook": "משפט פתיחה שתופס תשומת לב",
    "steps": ["צעד 1", "צעד 2", "צעד 3"],
    "hashtags": ["#האשטג1", "#האשטג2"],
    "angle": "זווית ייחודית - למשל: שלב עם תוכן זוגיות / תגובה אישית / סטורי טיים"
}}"""

        try:
            response = self.client.messages.create(
                model=config.ai.model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )

            import json
            text = response.content[0].text

            # Try to parse JSON
            try:
                # Find JSON in response
                start = text.find('{')
                end = text.rfind('}') + 1
                if start >= 0 and end > start:
                    return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass

            # Fallback
            return {
                "title": f"תגובה ל-{trend.title}",
                "hook": "...",
                "steps": ["צלם תגובה", "הוסף דעה", "סיים בקריאה לפעולה"],
                "hashtags": ["#טרנד"],
            }

        except Exception as e:
            logger.error(f"Error generating idea: {e}")
            return {
                "title": f"תגובה ל-{trend.title}",
                "hook": "...",
                "steps": ["צלם תגובה מהירה"],
                "hashtags": ["#טרנד"],
            }

    async def _send_golden_moment_alert(self, trend: Trend, idea: Dict) -> bool:
        """Send the golden moment alert via WhatsApp."""
        now = datetime.now(ISRAEL_TZ)
        day_hebrew = self._get_day_hebrew(now.weekday())
        time_str = now.strftime("%H:%M")

        hashtags = " ".join(idea.get("hashtags", []))

        message = f"""🚨 *רגע הזהב!*

🔥 הטרנד *'{trend.title}'* מתפוצץ עכשיו והוא מושלם בשבילך!

⏰ עכשיו זה הזמן הכי טוב שלך להעלות ({day_hebrew} {time_str})

📱 לא העלית היום עדיין - זו ההזדמנות!

💡 *רעיון מהיר:*
*{idea.get('title', 'רעיון')}*

🎬 פתיחה: "{idea.get('hook', '...')}"

📝 מה לעשות:
{self._format_steps(idea.get('steps', []))}

🏷️ {hashtags}

⏳ *חלון ההזדמנות: 2-3 שעות* לפני שזה יהיה ישן

---
שלח *"בוצע"* אם השתמשת ברעיון
שלח *"עוד"* אם רוצה רעיון אחר לטרנד הזה
שלח *"לא מעוניין"* לדלג על הטרנד הזה"""

        sid = whatsapp.send_message(message)
        return sid is not None

    def _format_steps(self, steps: List[str]) -> str:
        """Format steps as numbered list."""
        if not steps:
            return "• צלם תגובה מהירה"
        return "\n".join([f"{i}. {step}" for i, step in enumerate(steps, 1)])

    def _get_day_hebrew(self, weekday: int) -> str:
        """Get Hebrew day name."""
        days = ["יום שני", "יום שלישי", "יום רביעי", "יום חמישי", "יום שישי", "שבת", "יום ראשון"]
        return days[weekday]

    async def _record_alert(self, trend: Trend, idea: Dict):
        """Record the alert in database."""
        session = db.get_session()
        try:
            alert = GoldenMomentAlert(
                trend_id=trend.id,
                trend_topic=trend.title,
                trend_source=trend.source,
                relevance_score=trend.relevance_score,
                trend_discovered_at=trend.discovered_at,
                idea_suggested=idea.get("title"),
                hashtags_suggested=idea.get("hashtags"),
            )
            session.add(alert)
            session.commit()
            logger.info(f"Recorded golden moment alert for: {trend.title}")
        finally:
            session.close()

    async def handle_response(self, response: str) -> Optional[str]:
        """
        Handle user response to a golden moment alert.

        Args:
            response: User's response text

        Returns:
            Reply message, or None if not a golden moment response
        """
        response_lower = response.lower().strip()

        # FIRST: Check if message matches any golden moment keyword
        # If not, return None immediately without touching the database
        golden_keywords = {
            "used": ["בוצע", "עשיתי", "השתמשתי", "פרסמתי", "done", "used"],
            "more": ["עוד", "אחר", "רעיון אחר"],
            "not_interested": ["לא מעוניין", "דלג", "לא רלוונטי", "skip"],
            "later": ["אחר כך", "מאוחר יותר", "בעוד שעה", "later"],
        }

        matched_type = None
        for response_type, keywords in golden_keywords.items():
            if any(word in response_lower for word in keywords):
                matched_type = response_type
                break

        # Not a golden moment response - return None to let other handlers process it
        if not matched_type:
            return None

        # Get the most recent alert (only if we matched a keyword)
        session = db.get_session()
        try:
            recent_alert = session.query(GoldenMomentAlert).order_by(
                GoldenMomentAlert.alert_sent_at.desc()
            ).first()

            if not recent_alert:
                return "אין התראת 'רגע זהב' פעילה כרגע 🤷‍♂️\n\nשלח 'רעיון' לקבל רעיון לתוכן חדש!"

            # Handle based on matched type
            if matched_type == "used":
                return await self._handle_used_response(session, recent_alert)
            elif matched_type == "more":
                return await self._handle_more_response(session, recent_alert)
            elif matched_type == "not_interested":
                return await self._handle_not_interested_response(session, recent_alert)
            elif matched_type == "later":
                return await self._handle_remind_later_response(session, recent_alert)

        finally:
            session.close()

        return None

    async def _handle_used_response(self, session, alert: GoldenMomentAlert) -> str:
        """Mark alert as used and update learning."""
        alert.was_used = True
        alert.response = "used"
        alert.response_at = datetime.utcnow()

        # Increase topic weight (positive learning)
        self._update_topic_weight(session, alert.trend_topic, used=True)

        session.commit()

        return """מעולה! 🎉

סימנתי שהשתמשת ברעיון. אני לומד מזה ואחפש עוד טרנדים דומים!

💡 טיפ: כשהסרטון יעלה, שלח לי את הלינק ואני אעקוב אחרי הביצועים שלו."""

    async def _handle_more_response(self, session, alert: GoldenMomentAlert) -> str:
        """Generate another idea for the same trend."""
        # Get the trend
        trend = session.query(Trend).filter_by(id=alert.trend_id).first()

        if not trend:
            return "לא מצאתי את הטרנד, נסה 'רעיון' לקבל רעיון חדש"

        # Generate new idea
        idea = await self._generate_quick_idea(trend)

        return f"""💡 *רעיון נוסף לטרנד:*

*{idea.get('title', 'רעיון')}*

🎬 פתיחה: "{idea.get('hook', '...')}"

📝 מה לעשות:
{self._format_steps(idea.get('steps', []))}

🏷️ {' '.join(idea.get('hashtags', []))}

---
שלח "בוצע" כשתשתמש ברעיון!"""

    async def _handle_not_interested_response(self, session, alert: GoldenMomentAlert) -> str:
        """Mark as not interested and learn."""
        alert.response = "not_interested"
        alert.response_at = datetime.utcnow()

        # Decrease topic weight (negative learning)
        self._update_topic_weight(session, alert.trend_topic, used=False)

        session.commit()

        return """הבנתי! 👍

לא אציע טרנדים דומים בקרוב. אני לומד מהעדפות שלך!

שלח 'רעיון' מתי שתרצה רעיון לתוכן אחר."""

    async def _handle_remind_later_response(self, session, alert: GoldenMomentAlert) -> str:
        """Schedule a reminder in 1 hour."""
        alert.response = "remind_later"
        alert.response_at = datetime.utcnow()
        session.commit()

        # The scheduler will check if trend is still relevant
        return """בסדר! ⏰

אזכיר לך בעוד שעה אם הטרנד עדיין רלוונטי.

בהצלחה! 💪"""

    def _update_topic_weight(self, session, topic: str, used: bool):
        """Update topic weight based on user response."""
        # Extract keywords from topic
        keywords = topic.lower().split()

        for keyword in keywords:
            if len(keyword) < 3:  # Skip short words
                continue

            weight_record = session.query(TopicWeight).filter_by(topic=keyword).first()

            if not weight_record:
                weight_record = TopicWeight(topic=keyword)
                session.add(weight_record)

            weight_record.times_alerted += 1
            weight_record.last_updated = datetime.utcnow()

            if used:
                weight_record.times_used += 1
                # Increase weight (max 2.0)
                weight_record.weight = min(weight_record.weight * 1.1, 2.0)
            else:
                weight_record.times_ignored += 1
                # Decrease weight (min 0.3)
                weight_record.weight = max(weight_record.weight * 0.9, 0.3)

    async def learn_from_golden_moments(self) -> Dict[str, Any]:
        """
        Weekly analysis of golden moment effectiveness.

        Analyzes which alerts were used vs ignored and adjusts weights.

        Returns:
            Dict with learning summary
        """
        session = db.get_session()
        try:
            # Get alerts from last 7 days
            cutoff = datetime.utcnow() - timedelta(days=7)
            alerts = session.query(GoldenMomentAlert).filter(
                GoldenMomentAlert.alert_sent_at >= cutoff
            ).all()

            total = len(alerts)
            used = sum(1 for a in alerts if a.was_used)
            ignored = sum(1 for a in alerts if a.response == "not_interested")

            # Get top used topics
            used_topics = {}
            ignored_topics = {}

            for alert in alerts:
                topic = alert.trend_topic or ""
                if alert.was_used:
                    used_topics[topic] = used_topics.get(topic, 0) + 1
                elif alert.response == "not_interested":
                    ignored_topics[topic] = ignored_topics.get(topic, 0) + 1

            return {
                "total_alerts": total,
                "used_count": used,
                "ignored_count": ignored,
                "usage_rate": used / total * 100 if total > 0 else 0,
                "top_used_topics": sorted(used_topics.items(), key=lambda x: x[1], reverse=True)[:5],
                "top_ignored_topics": sorted(ignored_topics.items(), key=lambda x: x[1], reverse=True)[:5],
            }

        finally:
            session.close()

    async def check_remind_later(self) -> Dict[str, Any]:
        """
        Check if there's a pending 'remind later' and the trend is still relevant.
        Called by scheduler.

        Returns:
            Dict with reminder status
        """
        result = {"reminded": False, "topic": None, "reason": None}

        session = db.get_session()
        try:
            # Find 'remind_later' responses from about 1 hour ago
            one_hour_ago = datetime.utcnow() - timedelta(hours=1)
            thirty_min_ago = datetime.utcnow() - timedelta(minutes=30)

            pending = session.query(GoldenMomentAlert).filter(
                GoldenMomentAlert.response == "remind_later",
                GoldenMomentAlert.response_at >= one_hour_ago,
                GoldenMomentAlert.response_at <= thirty_min_ago,
            ).first()

            if not pending:
                result["reason"] = "no_pending_reminders"
                return result

            result["topic"] = pending.trend_topic

            # Check if trend is still fresh
            trend = session.query(Trend).filter_by(id=pending.trend_id).first()
            if not trend:
                result["reason"] = "trend_not_found"
                return result

            hours_old = (datetime.utcnow() - (trend.discovered_at or datetime.utcnow())).total_seconds() / 3600
            if hours_old > self.trend_freshness_hours + 2:  # Give extra buffer
                # Trend is too old now
                pending.response = "expired"
                session.commit()
                result["reason"] = "trend_expired"
                return result

            # Check if still hasn't posted
            posted = await self._check_if_posted_recently()
            if posted:
                pending.response = "posted_anyway"
                session.commit()
                result["reason"] = "user_posted"
                return result

            # Send reminder
            message = f"""⏰ *תזכורת!*

הטרנד '{trend.title}' עדיין חם!

עדיין לא העלית היום - עכשיו הזמן! 🔥

שלח 'רעיון' לקבל רעיון מפורט
או 'לא מעוניין' לדלג"""

            sid = whatsapp.send_message(message)

            if sid:
                pending.response = "reminded"
                session.commit()
                result["reminded"] = True
                return result

            result["reason"] = "send_failed"
            return result

        finally:
            session.close()

    async def run_weekly_learning(self) -> Dict[str, Any]:
        """
        Run weekly learning to adjust topic weights based on usage patterns.
        Called by scheduler every Sunday at midnight.

        Returns:
            Dict with learning results
        """
        result = {"topics_updated": 0, "insights": []}

        try:
            # Get learning data
            learning_data = await self.learn_from_golden_moments()

            result["total_alerts"] = learning_data.get("total_alerts", 0)
            result["usage_rate"] = learning_data.get("usage_rate", 0)

            session = db.get_session()
            try:
                # Get all topic weights
                weights = session.query(TopicWeight).all()

                for weight in weights:
                    # Recalculate weight based on historical usage
                    if weight.times_alerted > 0:
                        actual_rate = weight.times_used / weight.times_alerted

                        # Adjust weight based on usage rate
                        if actual_rate > 0.5:  # More than 50% used
                            new_weight = min(weight.weight * 1.1, 2.0)
                            if new_weight != weight.weight:
                                result["insights"].append(f"↑ '{weight.topic}' ({weight.times_used}/{weight.times_alerted} used)")
                        elif actual_rate < 0.2:  # Less than 20% used
                            new_weight = max(weight.weight * 0.9, 0.3)
                            if new_weight != weight.weight:
                                result["insights"].append(f"↓ '{weight.topic}' ({weight.times_ignored}/{weight.times_alerted} ignored)")
                        else:
                            new_weight = weight.weight

                        if new_weight != weight.weight:
                            weight.weight = new_weight
                            weight.last_updated = datetime.utcnow()
                            result["topics_updated"] += 1

                session.commit()

            finally:
                session.close()

            logger.info(f"Weekly learning: {result['topics_updated']} topics updated")

        except Exception as e:
            logger.error(f"Weekly learning error: {e}")
            result["error"] = str(e)

        return result
