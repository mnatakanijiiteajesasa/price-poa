"""
Enhanced worker script for PricePoa scraping service.
Coordinates spider execution, scheduling, and data processing.
"""
import asyncio
import logging
import signal
import sys
from typing import Optional
import argparse

from .scheduler import scrape_scheduler, setup_default_schedules
from .base_spider import BasePricePoaSpider

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('scraping.log')
    ]
)

logger = logging.getLogger(__name__)


class PricePoaWorker:
    """
    Main worker class for PricePoa scraping operations.
    Can run spiders directly or via scheduler.
    """

    def __init__(self):
        self.running = False
        logger.info("PricePoaWorker initialized")

    async def run_spider_direct(self, spider_name: str) -> None:
        """
        Run a specific spider directly (not via scheduler).

        Args:
            spider_name: Name of the spider to run
        """
        logger.info(f"Starting direct execution of spider: {spider_name}")

        try:
            from scrapy.crawler import CrawlerRunner
            from scrapy.utils.project import get_project_settings
            from twisted.internet import asyncioreactor

            # Setup Twisted reactor for asyncio compatibility
            asyncioreactor.install()

            # Get project settings
            settings = get_project_settings()
            # Enhance settings for better performance
            settings.set('LOG_LEVEL', 'INFO')
            settings.set('CONCURRENT_REQUESTS', 16)
            settings.set('DOWNLOAD_DELAY', 1)
            settings.set('AUTOTHROTTLE_ENABLED', True)
            settings.set('AUTOTHROTTLE_START_DELAY', 1)
            settings.set('AUTOTHROTTLE_MAX_DELAY', 10)
            settings.set('AUTOTHROTTLE_TARGET_CONCURRENCY', 5.0)

            # Create and run crawler
            runner = CrawlerRunner(settings)
            await runner.crawl(spider_name)
            await runner.join()

            logger.info(f"Completed direct execution of spider: {spider_name}")

        except ImportError as e:
            logger.error(f"Missing required dependency for direct spider run: {e}")
            logger.info("Falling back to process-based execution")
            await self._run_spider_process(spider_name)
        except Exception as e:
            logger.error(f"Error running spider {spider_name} directly: {e}")
            raise

    async def _run_spider_process(self, spider_name: str) -> None:
        """
        Run spider as a separate process (fallback method).

        Args:
            spider_name: Name of the spider to run
        """
        import subprocess
        import os

        try:
            # Change to scraper directory
            scraper_dir = os.path.dirname(os.path.abspath(__file__))
            cmd = [
                sys.executable,
                '-m', 'scrapy', 'crawl', spider_name,
                '-s', 'LOG_LEVEL=INFO',
                '-s', 'CONCURRENT_REQUESTS=16',
                '-s', 'DOWNLOAD_DELAY=1'
            ]

            logger.info(f"Running spider {spider_name} as process: {' '.join(cmd)}")

            # Run the process
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=scraper_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Wait for completion and capture output
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                logger.info(f"Spider {spider_name} completed successfully")
                if stdout:
                    logger.debug(f"Spider stdout: {stdout.decode()[:500]}...")
            else:
                logger.error(f"Spider {spider_name} failed with return code {process.returncode}")
                if stderr:
                    logger.error(f"Spider stderr: {stderr.decode()[:500]}...")
                raise RuntimeError(f"Spider {spider_name} failed")

        except Exception as e:
            logger.error(f"Error running spider {spider_name} as process: {e}")
            raise

    def start_scheduled_mode(self) -> None:
        """Start worker in scheduled mode using APScheduler."""
        logger.info("Starting PricePoa worker in scheduled mode")

        try:
            # Setup default scraping schedules
            setup_default_schedules()

            # Start the scheduler
            scrape_scheduler.start()

            self.running = True
            logger.info("PricePoa worker scheduled mode started successfully")

            # Keep the main thread alive
            try:
                while self.running:
                    import time
                    time.sleep(1)
            except KeyboardInterrupt:
                logger.info("Received interrupt signal, shutting down...")
                self.stop()

        except Exception as e:
            logger.error(f"Error starting scheduled mode: {e}")
            self.stop()
            raise

    def stop(self) -> None:
        """Stop the worker and cleanup resources."""
        logger.info("Stopping PricePoa worker...")
        self.running = False

        try:
            # Shutdown scheduler
            scrape_scheduler.shutdown(wait=True)
            logger.info("PricePoa worker stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping worker: {e}")

    def run_spider_list(self, spider_names: list) -> None:
        """
        Run a list of spiders sequentially.

        Args:
            spider_names: List of spider names to run
        """
        logger.info(f"Starting sequential execution of {len(spider_names)} spiders")

        async def run_all():
            for spider_name in spider_names:
                try:
                    await self.run_spider_direct(spider_name)
                    # Small delay between spiders to be respectful
                    await asyncio.sleep(5)
                except Exception as e:
                    logger.error(f"Failed to run spider {spider_name}: {e}")
                    # Continue with other spiders instead of stopping completely

        # Run the async function
        asyncio.run(run_all())


def main():
    """Main entry point for the worker script."""
    parser = argparse.ArgumentParser(description='PricePoa Scraping Worker')
    parser.add_argument(
        '--mode',
        choices=['direct', 'scheduled', 'list'],
        default='scheduled',
        help='Execution mode: direct (single spider), scheduled (APScheduler), or list (multiple spiders)'
    )
    parser.add_argument(
        '--spider',
        type=str,
        help='Spider name to run (required for direct mode)'
    )
    parser.add_argument(
        '--spiders',
        nargs='+',
        help='List of spider names to run (required for list mode)'
    )
    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default='INFO',
        help='Logging level'
    )

    args = parser.parse_args()

    # Set logging level
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # Create worker instance
    worker = PricePoaWorker()

    try:
        if args.mode == 'direct':
            if not args.spider:
                parser.error("--spider is required for direct mode")
            asyncio.run(worker.run_spider_direct(args.spider))

        elif args.mode == 'list':
            if not args.spiders:
                parser.error("--spiders is required for list mode")
            worker.run_spider_list(args.spiders)

        elif args.mode == 'scheduled':
            worker.start_scheduled_mode()

    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
        worker.stop()
    except Exception as e:
        logger.error(f"Fatal error in worker: {e}")
        worker.stop()
        sys.exit(1)


if __name__ == "__main__":
    main()