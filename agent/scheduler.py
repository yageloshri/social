"""
Scheduler
=========
Manages scheduled tasks for the Autonomous Content Agent.
Uses APScheduler for reliable cron-like scheduling.

NEW: Integrates with AutonomousAgent for brain-driven decision making.
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
from .skills.virality_predictor import ViralityPredictor
from .skills.series_detector import SeriesDetector
from .skills.weekly_reporter import WeeklyReporter

logger = logging.getLogger(__name__)

# Israel timezone
ISRAEL_TZ = pytz.timezone("Asia/Jerusalem")


class AgentScheduler:
    """
    Manages all scheduled tasks for the autonomous agent.

    NEW AUTONOMOUS SCHEDULE:
    - Every 30 min: Brain thinking cycle (decides what to do)
    - 08:00: Morning routine (scan, analyze, plan)
    - 22:00: Evening reflection (analyze day, plan tomorrow)
    - 03:00: Learn communication patterns
    - Sunday 10:00: Weekly strategy session
    - Sunday 00:00: Reset weekly counters
    - 00:00: Reset daily counters

    LEGACY SCHEDULE (still active):
    - Golden moment checks (prime time)
    - Virality checks (hourly)
    - Series scans (Saturday)
    - Weekly reports (Friday)
    """

    def __init__(self):
        self.scheduler = AsyncIOScheduler(timezone=ISRAEL_TZ)
        self.golden_moment_detector = GoldenMomentDetector()
        self.virality_predictor = ViralityPredictor()
        self.series_detector = SeriesDetector()
        self.weekly_reporter = WeeklyReporter()

        # Autonomous agent - lazy load to avoid circular imports
        self._autonomous_agent = None

        self._setup_jobs()

    @property
    def autonomous_agent(self):
        """Lazy load autonomous agent."""
        if self._autonomous_agent is None:
            from .autonomous import autonomous_agent
            self._autonomous_agent = autonomous_agent
        return self._autonomous_agent

    def _setup_jobs(self):
        """Set up all scheduled jobs."""

        # ========================================
        # AUTONOMOUS AGENT JOBS (NEW)
        # ========================================

        # Brain thinking cycle - every 30 minutes
        self.scheduler.add_job(
            self._run_brain_think,
            IntervalTrigger(minutes=30),
            id="brain_think",
            name="Brain Thinking Cycle",
            replace_existing=True,
        )

        # Autonomous morning routine - 8:00 AM
        self.scheduler.add_job(
            self._run_autonomous_morning,
            CronTrigger(hour=8, minute=0),
            id="autonomous_morning",
            name="Autonomous Morning Routine",
            replace_existing=True,
        )

        # Opportunity scanner - every 30 minutes during waking hours
        self.scheduler.add_job(
            self._run_opportunity_scan,
            CronTrigger(hour="8-23", minute="15,45"),
            id="opportunity_scan",
            name="Opportunity Scanner",
            replace_existing=True,
        )

        # Evening reflection - 22:00
        self.scheduler.add_job(
            self._run_evening_reflection,
            CronTrigger(hour=22, minute=0),
            id="evening_reflection",
            name="Evening Reflection",
            replace_existing=True,
        )

        # Learn communication patterns - 3:00 AM daily
        self.scheduler.add_job(
            self._run_pattern_learning,
            CronTrigger(hour=3, minute=0),
            id="pattern_learning",
            name="Learn Communication Patterns",
            replace_existing=True,
        )

        # Weekly strategy session - Sunday 10:00
        self.scheduler.add_job(
            self._run_weekly_strategy,
            CronTrigger(day_of_week="sun", hour=10, minute=0),
            id="weekly_strategy",
            name="Weekly Strategy Session",
            replace_existing=True,
        )

        # Reset daily counters - midnight
        self.scheduler.add_job(
            self._run_daily_reset,
            CronTrigger(hour=0, minute=0),
            id="daily_reset",
            name="Reset Daily Counters",
            replace_existing=True,
        )

        # Reset weekly counters - Sunday midnight
        self.scheduler.add_job(
            self._run_weekly_reset,
            CronTrigger(day_of_week="sun", hour=0, minute=5),
            id="weekly_reset",
            name="Reset Weekly Counters",
            replace_existing=True,
        )

        # ========================================
        # LEGACY JOBS (Still needed)
        # ========================================

        # Legacy morning routine - 6:00 AM (for scraping/analysis)
        self.scheduler.add_job(
            self._run_morning_routine,
            CronTrigger(hour=6, minute=0),
            id="morning_routine",
            name="Morning Routine (scan, analyze)",
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
            CronTrigger(day_of_week="sun", hour=0, minute=30),
            id="golden_moment_learning",
            name="Golden Moment Weekly Learning",
            replace_existing=True,
        )

        # Virality check - every hour
        self.scheduler.add_job(
            self._run_virality_check,
            IntervalTrigger(hours=1),
            id="virality_check",
            name="Check New Posts for Virality",
            replace_existing=True,
        )

        # Series potential scan - Saturday at 20:00
        self.scheduler.add_job(
            self._run_series_scan,
            CronTrigger(day_of_week="sat", hour=20, minute=0),
            id="series_scan",
            name="Scan for Series Potential",
            replace_existing=True,
        )

        # Weekly report - Friday at 18:00
        self.scheduler.add_job(
            self._run_weekly_report,
            CronTrigger(day_of_week="fri", hour=18, minute=0),
            id="weekly_report",
            name="Send Weekly Performance Report",
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

        logger.info("All jobs scheduled (autonomous + legacy)")

    # ========================================
    # AUTONOMOUS AGENT METHODS
    # ========================================

    async def _run_brain_think(self):
        """Run the brain's thinking cycle."""
        try:
            logger.info("Running brain thinking cycle...")
            result = await self.autonomous_agent.think_cycle()
            action = result.get("action_decided", "STAY_QUIET")
            executed = result.get("action_executed", False)
            logger.info(f"Brain cycle: action={action}, executed={executed}")
        except Exception as e:
            logger.error(f"Brain think error: {e}")

    async def _run_autonomous_morning(self):
        """Run autonomous morning routine."""
        try:
            logger.info("Running autonomous morning routine...")
            result = await self.autonomous_agent.morning_routine()
            logger.info(f"Morning routine: sent={result.get('message_sent')}")
        except Exception as e:
            logger.error(f"Autonomous morning error: {e}")

    async def _run_opportunity_scan(self):
        """Run opportunity scanner."""
        try:
            logger.info("Running opportunity scan...")
            result = await self.autonomous_agent.opportunity_scan()
            if result.get("opportunity_found"):
                logger.info(f"Opportunity: {result.get('opportunity_type')}, action={result.get('action_taken')}")
            else:
                logger.debug("No opportunities found")
        except Exception as e:
            logger.error(f"Opportunity scan error: {e}")

    async def _run_evening_reflection(self):
        """Run evening reflection."""
        try:
            logger.info("Running evening reflection...")
            result = await self.autonomous_agent.evening_reflection()
            logger.info(f"Evening reflection: sent={result.get('message_sent')}")
        except Exception as e:
            logger.error(f"Evening reflection error: {e}")

    async def _run_pattern_learning(self):
        """Run communication pattern learning."""
        try:
            logger.info("Learning communication patterns...")
            await self.autonomous_agent.learn_patterns()
            logger.info("Pattern learning completed")
        except Exception as e:
            logger.error(f"Pattern learning error: {e}")

    async def _run_weekly_strategy(self):
        """Run weekly strategy session."""
        try:
            logger.info("Running weekly strategy session...")
            result = await self.autonomous_agent.weekly_strategy()
            logger.info(f"Weekly strategy: sent={result.get('message_sent')}")
        except Exception as e:
            logger.error(f"Weekly strategy error: {e}")

    async def _run_daily_reset(self):
        """Reset daily counters."""
        try:
            logger.info("Resetting daily counters...")
            self.autonomous_agent.reset_daily()
        except Exception as e:
            logger.error(f"Daily reset error: {e}")

    async def _run_weekly_reset(self):
        """Reset weekly counters."""
        try:
            logger.info("Resetting weekly counters...")
            self.autonomous_agent.reset_weekly()
        except Exception as e:
            logger.error(f"Weekly reset error: {e}")

    # ========================================
    # LEGACY METHODS (Still needed)
    # ========================================

    async def _run_morning_routine(self):
        """Execute legacy morning routine (scanning)."""
        try:
            logger.info("Executing legacy morning routine")
            result = await agent.morning_routine()
            logger.info("Morning routine completed")
        except Exception as e:
            logger.error(f"Morning routine error: {e}")

    async def _run_no_post_reminder_check(self):
        """Check if user hasn't posted in 4+ days and send reminder."""
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

    async def _run_virality_check(self):
        """Check new posts for early virality signals."""
        try:
            logger.info("Checking posts for virality...")
            result = await self.virality_predictor.execute()

            if result.get("alerts_sent", 0) > 0:
                logger.info(f"Virality alerts sent: {result.get('alerts_sent')}")
            else:
                logger.info(f"Checked {result.get('posts_checked', 0)} posts, no viral signals")

        except Exception as e:
            logger.error(f"Virality check error: {e}")

    async def _run_series_scan(self):
        """Scan successful posts for series potential."""
        try:
            logger.info("Scanning for series potential...")
            result = await self.series_detector.execute()

            logger.info(f"Series scan: {result.get('series_potential_found', 0)} potential series found")

        except Exception as e:
            logger.error(f"Series scan error: {e}")

    async def _run_weekly_report(self):
        """Generate and send weekly performance report."""
        try:
            logger.info("Generating weekly report...")
            result = await self.weekly_reporter.execute()

            if result.get("sent"):
                logger.info(f"Weekly report sent: {result.get('total_views', 0)} total views")
            else:
                logger.error("Failed to send weekly report")

        except Exception as e:
            logger.error(f"Weekly report error: {e}")

    def start(self):
        """Start the scheduler and autonomous agent."""
        # Ensure database tables are created
        db.create_tables()
        logger.info("Database tables initialized")

        # Start autonomous agent
        asyncio.create_task(self.autonomous_agent.start())

        # Start scheduler
        self.scheduler.start()
        logger.info("Scheduler started (autonomous mode)")

        # Log next run times
        for job in self.scheduler.get_jobs():
            next_run = job.next_run_time
            logger.info(f"  {job.name}: next run at {next_run}")

        # Run initial scan on startup (don't wait for scheduled time)
        asyncio.create_task(self._run_startup_scan())

    async def _run_startup_scan(self):
        """Run initial profile scan on startup."""
        try:
            from .skills.profile_scanner import ProfileScanner

            logger.info("Running startup profile scan...")
            scanner = ProfileScanner()
            result = await scanner.execute(platforms=["instagram", "tiktok"])

            new_posts = result.get("new_posts", 0)
            updated_posts = result.get("updated_posts", 0)
            errors = result.get("errors", [])

            if errors:
                logger.warning(f"Startup scan completed with errors: {errors}")
            else:
                logger.info(f"Startup scan complete: {new_posts} new posts, {updated_posts} updated posts")

        except Exception as e:
            logger.error(f"Startup scan error: {e}")

    def stop(self):
        """Stop the scheduler and autonomous agent."""
        # Stop autonomous agent
        asyncio.create_task(self.autonomous_agent.stop())

        # Stop scheduler
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

    def get_agent_status(self):
        """Get autonomous agent status."""
        return self.autonomous_agent.get_status()

    async def run_now(self, job_id: str):
        """Run a specific job immediately."""
        job_map = {
            # Autonomous jobs
            "brain_think": self._run_brain_think,
            "autonomous_morning": self._run_autonomous_morning,
            "opportunity_scan": self._run_opportunity_scan,
            "evening_reflection": self._run_evening_reflection,
            "weekly_strategy": self._run_weekly_strategy,
            # Legacy jobs
            "morning_routine": self._run_morning_routine,
            "golden_moment_check": self._run_golden_moment_check,
            "virality_check": self._run_virality_check,
            "weekly_report": self._run_weekly_report,
        }

        if job_id in job_map:
            await job_map[job_id]()
        else:
            raise ValueError(f"Unknown job: {job_id}")


# Global scheduler instance
scheduler = AgentScheduler()
