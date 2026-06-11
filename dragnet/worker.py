"""
APScheduler worker loop.
Runs sourcing, classification, tailoring, execution, and ghost-check on schedule.
"""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from dragnet.db.connection import SessionLocal, init_db

logger = logging.getLogger(__name__)


async def job_source():
    """M1: Crawl ATS APIs and ingest new postings."""
    from dragnet.sourcing.runner import run_sourcing
    async with SessionLocal() as db:
        counts = await run_sourcing(db)
        logger.info(f"Sourcing: {counts}")


async def job_classify():
    """M2: Classify and rank all unclassified postings."""
    from dragnet.eligibility.ranker import classify_and_rank_pending
    async with SessionLocal() as db:
        count = await classify_and_rank_pending(db)
        logger.info(f"Classified {count} postings")


async def job_tailor():
    """M3: Generate tailored resumes + answers for eligible postings."""
    from dragnet.executor.queue import run_tailoring_pass
    async with SessionLocal() as db:
        count = await run_tailoring_pass(db)
        logger.info(f"Tailored {count} applications")


async def job_execute():
    """M4: Submit applications (dry_run=False for production)."""
    from dragnet.executor.queue import run_executor_pass
    async with SessionLocal() as db:
        stats = await run_executor_pass(db, dry_run=False)
        logger.info(f"Executor: {stats}")


async def job_gmail():
    """M5: Ingest Gmail replies and advance application states."""
    from dragnet.crm.gmail import ingest_replies
    async with SessionLocal() as db:
        changes = await ingest_replies(db)
        logger.info(f"Gmail: {changes} state changes")


async def job_ghosts():
    """M5: Check for ghosted applications."""
    from dragnet.crm.state import check_ghost_timeouts
    async with SessionLocal() as db:
        count = await check_ghost_timeouts(db)
        logger.info(f"Ghost check: {count} applications marked ghosted")


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    # Sourcing: every Sunday at 2am + Tuesday at 2am
    scheduler.add_job(job_source, CronTrigger(day_of_week="sun,tue", hour=2), id="source")

    # Classify: 30 min after sourcing runs, also daily at 3am
    scheduler.add_job(job_classify, CronTrigger(hour=3), id="classify")

    # Tailor: daily at 4am
    scheduler.add_job(job_tailor, CronTrigger(hour=4), id="tailor")

    # Execute: Mon-Fri 9am IST (3:30am UTC) — business hours target
    scheduler.add_job(job_execute, CronTrigger(day_of_week="mon-fri", hour=3, minute=30), id="execute")

    # Gmail ingest: every 4 hours
    scheduler.add_job(job_gmail, IntervalTrigger(hours=4), id="gmail")

    # Ghost check: daily at 6am
    scheduler.add_job(job_ghosts, CronTrigger(hour=6), id="ghosts")

    return scheduler


async def run_worker():
    """Start the background worker. Blocks until interrupted."""
    await init_db()
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Dragnet worker started. Press Ctrl+C to exit.")
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Worker stopped.")
