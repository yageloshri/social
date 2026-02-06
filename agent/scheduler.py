"""
Scheduler
=========
Manages scheduled tasks for the Content Master Agent.
Uses APScheduler for reliable cron-like scheduling.
"""

import asyncio
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from .config import config
from .core_agent import agent

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
