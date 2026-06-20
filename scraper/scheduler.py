"""
APScheduler configuration for PricePoa scraping jobs.
Handles timed execution of scraping spiders.
"""
import logging
from typing import Dict, Any, Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import asyncio
import signal
import sys

logger = logging.getLogger(__name__)


class ScrapeScheduler:
    """
    Manages scheduled scraping jobs using APScheduler.
    Supports both cron-based and interval-based scheduling.
    """

    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.jobs: Dict[str, Any] = {}
        self.running = False
        logger.info("ScrapeScheduler initialized")

    def add_scrape_job(
        self,
        job_id: str,
        spider_name: str,
        schedule_type: str = "interval",
        **schedule_kwargs
    ) -> bool:
        """
        Add a scraping job to the scheduler.

        Args:
            job_id: Unique identifier for the job
            spider_name: Name of the spider to run
            schedule_type: Either "interval" or "cron"
            **schedule_kwargs: Arguments for the trigger (hours, minutes, etc. for interval;
                              cron expressions for cron)

        Returns:
            True if job added successfully, False otherwise
        """
        if job_id in self.jobs:
            logger.warning(f"Job {job_id} already exists, updating schedule")

        try:
            if schedule_type == "interval":
                trigger = IntervalTrigger(**schedule_kwargs)
                logger.info(
                    f"Added interval job '{job_id}' for spider '{spider_name}' "
                    f"every {schedule_kwargs}"
                )
            elif schedule_type == "cron":
                trigger = CronTrigger(**schedule_kwargs)
                logger.info(
                    f"Added cron job '{job_id}' for spider '{spider_name}' "
                    f"with schedule {schedule_kwargs}"
                )
            else:
                raise ValueError(f"Invalid schedule_type: {schedule_type}. Use 'interval' or 'cron'")

            # Add job to scheduler
            job = self.scheduler.add_job(
                func=self._run_spider_job,
                trigger=trigger,
                args=[spider_name],
                id=job_id,
                name=f"Scrape {spider_name}",
                replace_existing=True,
                max_instances=1,  # Prevent overlapping runs
                misfire_grace_time=300  # 5 minutes grace period for missed runs
            )

            self.jobs[job_id] = job
            logger.info(f"Successfully scheduled job '{job_id}'")
            return True

        except Exception as e:
            logger.error(f"Failed to add scrape job {job_id}: {e}")
            return False

    def remove_job(self, job_id: str) -> bool:
        """
        Remove a job from the scheduler.

        Args:
            job_id: ID of job to remove

        Returns:
            True if job removed, False if not found
        """
        if job_id not in self.jobs:
            logger.warning(f"Job {job_id} not found")
            return False

        try:
            self.scheduler.remove_job(job_id)
            del self.jobs[job_id]
            logger.info(f"Removed job '{job_id}'")
            return True
        except Exception as e:
            logger.error(f"Error removing job {job_id}: {e}")
            return False

    def start(self) -> None:
        """Start the scheduler."""
        if self.running:
            logger.warning("Scheduler is already running")
            return

        try:
            self.scheduler.start()
            self.running = True
            logger.info("ScrapeScheduler started")

            # Setup signal handlers for graceful shutdown
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)

        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")
            self.running = False

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the scheduler."""
        if not self.running:
            logger.warning("Scheduler is not running")
            return

        try:
            self.scheduler.shutdown(wait=wait)
            self.running = False
            logger.info("ScrapeScheduler shutdown complete")
        except Exception as e:
            logger.error(f"Error shutting down scheduler: {e}")

    def pause_job(self, job_id: str) -> bool:
        """Pause a scheduled job."""
        if job_id not in self.jobs:
            logger.warning(f"Job {job_id} not found")
            return False

        try:
            self.scheduler.pause_job(job_id)
            logger.info(f"Paused job '{job_id}'")
            return True
        except Exception as e:
            logger.error(f"Error pausing job {job_id}: {e}")
            return False

    def resume_job(self, job_id: str) => bool:
        """Resume a paused job."""
        if job_id not in self.jobs:
            logger.warning(f"Job {job_id} not found")
            return False

        try:
            self.scheduler.resume_job(job_id)
            logger.info(f"Resumed job '{job_id}'")
            return True
        except Exception as e:
            logger.error(f"Error resuming job {job_id}: {e}")
            return False

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get status of a specific job.

        Args:
            job_id: ID of job to check

        Returns:
            Job status dictionary or None if not found
        """
        if job_id not in self.jobs:
            return None

        job = self.jobs[job_id]
        return {
            'id': job.id,
            'name': job.name,
            'next_run_time': job.next_run_time,
            'trigger': str(job.trigger),
            'func': job.func_ref,
            'args': job.args,
            'kwargs': job.kwargs
        }

    def list_jobs(self) -> Dict[str, Dict[str, Any]]:
        """
        List all scheduled jobs.

        Returns:
            Dictionary of job IDs to their status information
        """
        jobs_status = {}
        for job_id in self.jobs:
            jobs_status[job_id] = self.get_job_status(job_id)
        return jobs_status

    async def _run_spider_job(self, spider_name: str) -> None:
        """
        Execute a scraping spider job.
        This runs in a separate thread from the scheduler.

        Args:
            spider_name: Name of the spider to run
        """
        logger.info(f"Starting scheduled scrape job for spider: {spider_name}")

        try:
            # Import here to avoid circular imports
            from scrapy.crawler import CrawlerProcess
            from scrapy.utils.project import get_project_settings
            import os

            # Setup Scrapy settings
            settings = get_project_settings()
            # Override some settings for scheduled runs
            settings.set('LOG_LEVEL', 'INFO')
            settings.set('JOBDIR', f'crawls/{spider_name}')

            # Create and run crawler process
            process = CrawlerProcess(settings)
            process.crawl(spider_name)
            process.start()  # This blocks until crawling is finished

            logger.info(f"Completed scrape job for spider: {spider_name}")

        except Exception as e:
            logger.error(f"Error running spider {spider_name}: {e}")
            # Re-raise to let APScheduler handle the error according to its policy
            raise

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, shutting down scheduler...")
        self.shutdown(wait=True)
        sys.exit(0)


# Global scheduler instance
scrape_scheduler = ScrapeScheduler()


def setup_default_schedules():
    """
    Setup default scraping schedules for PricePoa.
    Call this to initialize standard scraping routines.
    """
    # Daily full scrape at 2 AM
    scrape_scheduler.add_scrape_job(
        job_id="daily_full_scrape",
        spider_name="naivas_spider",  # Will be replaced with actual spider names
        schedule_type="cron",
        hour=2,
        minute=0
    )

    # Add spiders for other stores
    stores = ["carrefour_spider", "quickmart_spider", "chandarana_spider"]
    for i, spider_name in enumerate(stores):
        scrape_scheduler.add_scrape_job(
            job_id=f"daily_{spider_name}",
            spider_name=spider_name,
            schedule_type="cron",
            hour=2,
            minute=(i + 1) * 15  # Stagger at 2:15, 2:30, 2:45 AM
        )

    # Hourly promotional checks (every 6 hours)
    scrape_scheduler.add_scrape_job(
        job_id="hourly_promo_check",
        spider_name="promo_spider",  # Special spider for promotions
        schedule_type="interval",
        hours=6
    )

    logger.info("Default scraping schedules configured")


if __name__ == "__main__":
    # Test the scheduler
    setup_default_schedules()
    scrape_scheduler.start()

    try:
        # Keep running until interrupted
        print("Scheduler running. Press Ctrl+C to stop.")
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        scrape_scheduler.shutdown()