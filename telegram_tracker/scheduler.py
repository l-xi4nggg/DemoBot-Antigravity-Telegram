import os
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from telegram_tracker.services import check_pending_reminders

logger = logging.getLogger(__name__)

def setup_scheduler(application) -> AsyncIOScheduler:
    """Configures and starts the background AsyncIOScheduler for checking reminders."""
    scheduler = AsyncIOScheduler()
    
    # Check if a test interval is configured (in seconds) for testing purposes
    test_interval = os.getenv("TEST_SCHEDULER_INTERVAL_SECONDS")
    
    if test_interval:
        try:
            seconds = int(test_interval)
            logger.info(f"Test scheduler detected! Running reminder checks every {seconds} seconds.")
            trigger = IntervalTrigger(seconds=seconds)
        except ValueError:
            logger.warning("Invalid TEST_SCHEDULER_INTERVAL_SECONDS. Defaulting to daily cron.")
            trigger = CronTrigger(hour=0, minute=0)
    else:
        logger.info("Scheduling daily reminder checks at 00:00.")
        trigger = CronTrigger(hour=0, minute=0)
        
    # Add job to scheduler. Pass the application object to the job.
    scheduler.add_job(
        check_pending_reminders,
        trigger=trigger,
        args=[application],
        id="check_pending_reminders",
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("Scheduler started successfully.")
    return scheduler
