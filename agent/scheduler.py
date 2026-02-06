"""
Scheduler
=========
Manages scheduled tasks for the Content Master Agent.
Uses APScheduler for reliable cron-like scheduling.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import pytz

from .config import config
from .core_agent import agent
from .database import db, ReminderLog, Post
from .integrations.whatsapp import whatsapp
from .skills.golden_moment import GoldenMomentDetector

logger = logging.getLogger(__name__)

# Israel timezone
ISRAEL_TZ = pytz.timezone("Asia/Jerusalem")


class AgentScheduler:
    """
    Manages all scheduled tasks for the agent.

    Schedule:
    - 06:00: Morning routine (full scan, analysis, idea generation)
    - 09:00: Send morning message
    - 12:00: Quick update
    - 13:00: Send midday message (if trends)
    - 17:00: Send afternoon reminder
    - 18:00: Quick update
    - 21:00: Send evening message
    - 00:00: Quick update
    """

    def __init__(self):
        self.scheduler = AsyncIOScheduler(timezone=ISRAEL_TZ)
        self.golden_moment_detector = GoldenMomentDetector()
        self._setup_jobs()

    def _setup_jobs(self):
        """Set up all scheduled jobs."""

        # Morning routine - 6:00 AM Israel time
        self.scheduler.add_job(
            self._run_morning_routine,
            CronTrigger(hour=6, minute=0),
            id="morning_routine",
            name="Morning Routine (scan, analyze, generate ideas)",
            replace_existing=True,
        )

        # Morning message - 9:00 AM
        self.scheduler.add_job(
            self._run_morning_message,
            CronTrigger(hour=9, minute=0),
            id="morning_message",
            name="Send Morning Message",
            replace_existing=True,
        )

        # Midday trend check - 12:00 PM
        self.scheduler.add_job(
            self._run_quick_update,
            CronTrigger(hour=12, minute=0),
            id="midday_update",
            name="Midday Quick Update",
            replace_existing=True,
        )

        # Midday message - 1:00 PM
        self.scheduler.add_job(
            self._run_midday_message,
            CronTrigger(hour=13, minute=0),
            id="midday_message",
            name="Send Midday Message (if trends)",
            replace_existing=True,
        )

        # Afternoon message - 5:00 PM
        self.scheduler.add_job(
            self._run_afternoon_message,
            CronTrigger(hour=17, minute=0),
            id="afternoon_message",
            name="Send Afternoon Reminder",
            replace_existing=True,
        )

        # Evening update - 6:00 PM
        self.scheduler.add_job(
            self._run_quick_update,
            CronTrigger(hour=18, minute=0),
            id="evening_update",
            name="Evening Quick Update",
            replace_existing=True,
        )

        # Evening message - 9:00 PM
        self.scheduler.add_job(
            self._run_evening_message,
            CronTrigger(hour=21, minute=0),
            id="evening_message",
            name="Send Evening Message",
            replace_existing=True,
        )

        # Midnight update - 12:00 AM
        self.scheduler.add_job(
            self._run_quick_update,
            CronTrigger(hour=0, minute=0),
            id="midnight_update",
            name="Midnight Quick Update",
            replace_existing=True,
        )

        # No-post reminder check - every 6 hours
        self.scheduler.add_job(
            self._run_no_post_reminder_check,
            IntervalTrigger(hours=6),
            id="no_post_reminder",
            name="No Post Reminder Check",
            replace_existing=True,
        )

        # Golden Moment check - every 30 minutes during prime time (16:00-21:00)
        self.scheduler.add_job(
            self._run_golden_moment_check,
            CronTrigger(hour="16-21", minute="0,30"),
            id="golden_moment_check",
            name="Golden Moment Check (Prime Time)",
            replace_existing=True,
        )

        # Golden Moment remind later check - every hour
        self.scheduler.add_job(
            self._run_remind_later_check,
            IntervalTrigger(hours=1),
            id="remind_later_check",
            name="Golden Moment Remind Later Check",
            replace_existing=True,
        )

        # Golden Moment weekly learning - Sunday at midnight
        self.scheduler.add_job(
            self._run_golden_moment_learning,
            CronTrigger(day_of_week="sun", hour=0, minute=0),
            id="golden_moment_learning",
            name="Golden Moment Weekly Learning",
            replace_existing=True,
        )

        logger.info("All jobs scheduled")

    async def _run_morning_routine(self):
        """Execute morning routine."""
        try:
            logger.info("Executing scheduled morning routine")
            result = await agent.morning_routine()
            logger.info(f"Morning routine completed")
        except Exception as e:
            logger.error(f"Morning routine error: {e}")

    async def _run_morning_message(self):
        """Send morning message."""
        try:
            logger.info("Executing scheduled morning message")
            result = await agent.send_morning_message()
            logger.info(f"Morning message: sent={result.get('sent')}")
        except Exception as e:
            logger.error(f"Morning message error: {e}")

    async def _run_midday_message(self):
        """Send midday message."""
        try:
            logger.info("Executing scheduled midday message")
            result = await agent.send_midday_message()
            logger.info(f"Midday message: sent={result.get('sent')}")
        except Exception as e:
            logger.error(f"Midday message error: {e}")

    async def _run_afternoon_message(self):
        """Send afternoon message."""
        try:
            logger.info("Executing scheduled afternoon message")
            result = await agent.send_afternoon_message()
            logger.info(f"Afternoon message: sent={result.get('sent')}")
        except Exception as e:
            logger.error(f"Afternoon message error: {e}")

    async def _run_evening_message(self):
        """Send evening message."""
        try:
            logger.info("Executing scheduled evening message")
            result = await agent.send_evening_message()
            logger.info(f"Evening message: sent={result.get('sent')}")
        except Exception as e:
            logger.error(f"Evening message error: {e}")

    async def _run_quick_update(self):
        """Run quick update."""
        try:
            logger.info("Executing scheduled quick update")
            result = await agent.quick_update()
            logger.info(f"Quick update completed: alert_sent={result.get('breaking_alert_sent')}")
        except Exception as e:
            logger.error(f"Quick update error: {e}")

    async def _run_no_post_reminder_check(self):
        """
        Check if user hasn't posted in 4+ days and send reminder.
        Rules:
        - Threshold: 4 days without posting
        - Check interval: Every 6 hours
        - Spam prevention: Wait 12 hours between reminders
        """
        try:
            logger.info("Checking for no-post reminder")

            # Check if reminder was sent in last 12 hours
            if self._was_reminder_sent_recently("no_post", hours=12):
                logger.info("Reminder already sent in last 12 hours, skipping")
                return

            # Check days since last post on any platform
            days_since = self._get_days_since_last_post()

            if days_since is None:
                logger.info("No posts found in database, skipping reminder")
                return

            if days_since >= 4:
                logger.info(f"User hasn't posted in {days_since} days, sending reminder")

                # Craft reminder message
                if days_since == 4:
                    message = """⏰ *תזכורת חברית!*

עברו 4 ימים מהפוסט האחרון שלך! 📱

הקהל שלך מחכה לך! 🙌

💡 רוצה רעיון לתוכן? שלח 'רעיון'
🔥 רוצה לראות מה חם עכשיו? שלח 'טרנדים'"""
                elif days_since <= 7:
                    message = f"""⚠️ *שבוע בלי תוכן!*

עברו כבר {days_since} ימים מהפוסט האחרון שלך.

האלגוריתם אוהב עקביות - בוא נחזיר אותך למשחק! 💪

שלח 'רעיון' ואני אעזור לך להתחיל!"""
                else:
                    message = f"""🚨 *הגיע הזמן לחזור!*

עברו {days_since} ימים מהפוסט האחרון.

אני יודע שזה קורה לפעמים, אבל הקהל שלך מתגעגע! ❤️

בוא נתחיל בקטן:
• שלח 'רעיון' - אני אייצר משהו קל ומהיר
• שלח 'טרנדים' - אולי משהו אקטואלי יעזור

אני כאן לעזור! 🤝"""

                # Send reminder via WhatsApp
                sid = whatsapp.send_message(message)

                if sid:
                    # Log the reminder
                    self._log_reminder("no_post", message)
                    logger.info(f"No-post reminder sent, SID: {sid}")
                else:
                    logger.error("Failed to send no-post reminder")

            else:
                logger.info(f"Last post was {days_since} days ago, no reminder needed")

        except Exception as e:
            logger.error(f"No-post reminder check error: {e}")

    def _get_days_since_last_post(self) -> int:
        """Get days since the last post on any platform."""
        session = db.get_session()
        try:
            latest = session.query(Post).order_by(Post.posted_at.desc()).first()

            if latest and latest.posted_at:
                return (datetime.utcnow() - latest.posted_at).days

            return None
        finally:
            session.close()

    def _was_reminder_sent_recently(self, reminder_type: str, hours: int = 12) -> bool:
        """Check if a reminder was sent in the last N hours."""
        session = db.get_session()
        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            recent = session.query(ReminderLog).filter(
                ReminderLog.reminder_type == reminder_type,
                ReminderLog.sent_at >= cutoff
            ).first()

            return recent is not None
        finally:
            session.close()

    def _log_reminder(self, reminder_type: str, message: str):
        """Log a sent reminder to prevent spam."""
        session = db.get_session()
        try:
            log = ReminderLog(
                reminder_type=reminder_type,
                message=message,
            )
            session.add(log)
            session.commit()
        finally:
            session.close()

    async def _run_golden_moment_check(self):
        """Check for golden moment opportunities during prime time."""
        try:
            logger.info("Checking for golden moments...")
            result = await self.golden_moment_detector.execute()

            if result.get("alert_sent"):
                logger.info(f"Golden moment alert sent for: {result.get('topic')}")
            elif result.get("skipped_reason"):
                logger.info(f"Golden moment skipped: {result.get('skipped_reason')}")
            else:
                logger.info("No golden moments found")

        except Exception as e:
            logger.error(f"Golden moment check error: {e}")

    async def _run_remind_later_check(self):
        """Check for remind_later golden moments that need re-alerting."""
        try:
            logger.info("Checking remind_later golden moments...")
            result = await self.golden_moment_detector.check_remind_later()

            if result.get("reminded"):
                logger.info(f"Re-sent reminder for: {result.get('topic')}")
            else:
                logger.info("No remind_later items ready")

        except Exception as e:
            logger.error(f"Remind later check error: {e}")

    async def _run_golden_moment_learning(self):
        """Run weekly learning to adjust topic weights based on usage patterns."""
        try:
            logger.info("Running golden moment weekly learning...")
            result = await self.golden_moment_detector.run_weekly_learning()

            logger.info(f"Learning completed: {result.get('topics_updated', 0)} topics updated")

        except Exception as e:
            logger.error(f"Golden moment learning error: {e}")

    def start(self):
        """Start the scheduler."""
        self.scheduler.start()
        logger.info("Scheduler started")

        # Log next run times
        for job in self.scheduler.get_jobs():
            next_run = job.next_run_time
            logger.info(f"  {job.name}: next run at {next_run}")

    def stop(self):
        """Stop the scheduler."""
        self.scheduler.shutdown()
        logger.info("Scheduler stopped")

    def get_jobs(self):
        """Get all scheduled jobs."""
        return [
            {
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            }
            for job in self.scheduler.get_jobs()
        ]

    async def run_now(self, job_id: str):
        """
        Run a specific job immediately.

        Args:
            job_id: ID of the job to run
        """
        job_map = {
            "morning_routine": self._run_morning_routine,
            "morning_message": self._run_morning_message,
            "midday_message": self._run_midday_message,
            "afternoon_message": self._run_afternoon_message,
            "evening_message": self._run_evening_message,
            "quick_update": self._run_quick_update,
        }

        if job_id in job_map:
            await job_map[job_id]()
        else:
            raise ValueError(f"Unknown job: {job_id}")


# Global scheduler instance
scheduler = AgentScheduler()
