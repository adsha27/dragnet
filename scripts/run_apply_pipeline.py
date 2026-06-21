"""
End-to-end application pipeline.

Steps:
  1. Tailoring pass — assign category PDFs, run liveness checks
  2. Human approval gate — y/n/a/q per posting (first 50 submissions)
  3. Executor pass — fill forms and submit

Usage:
    python scripts/run_apply_pipeline.py
    python scripts/run_apply_pipeline.py --dry-run
    python scripts/run_apply_pipeline.py --dry-run --limit 5
    python scripts/run_apply_pipeline.py --limit 10

Prerequisites:
    1. python scripts/generate_category_resumes.py    # produces output/category_resumes/*.pdf
    2. python scripts/import_eligible_jobs.py         # loads eligible jobs to DB
    3. Set APPLICANT_LINKEDIN in .env (optional)
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from sqlalchemy.orm import selectinload
from dragnet.db.connection import SessionLocal, init_db
from dragnet.db.models import Application, ApplicationState, Posting, Company, StateTransition
from dragnet.executor.queue import run_executor_pass, run_tailoring_pass, _record_transition
from datetime import datetime, timezone
UTC = timezone.utc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def approval_gate(db, limit: int, auto_approve: bool = False) -> tuple[int, int]:
    """
    Present tailored applications for human review.
    Returns (approved_count, rejected_count).
    """
    result = await db.execute(
        select(Application, Posting)
        .join(Posting, Application.posting_id == Posting.id)
        .join(Company, Posting.company_id == Company.id)
        .where(Application.state == ApplicationState.tailored)
        .options(selectinload(Application.posting).selectinload(Posting.company))
        .limit(limit)
    )
    rows = result.all()

    if not rows:
        print("No tailored applications pending review.")
        return 0, 0

    approved = rejected = 0
    approve_all = auto_approve

    print(f"\n{'='*60}")
    if auto_approve:
        print(f"HUMAN REVIEW GATE — auto-approving {len(rows)} (dry-run mode)")
    else:
        print(f"HUMAN REVIEW GATE — {len(rows)} application(s) to review")
        print("Keys: y=approve  n=reject  a=approve all  q=quit")
    print('='*60)

    for app, posting in rows:
        if approve_all:
            app.state = ApplicationState.human_review
            await _record_transition(db, app, ApplicationState.human_review, "human_gate")
            approved += 1
            continue

        category = (posting.raw_json or {}).get("category", "unknown")
        company = posting.company.name if posting.company else "Unknown"
        print(f"\n  Company : {company}")
        print(f"  Role    : {posting.title}")
        print(f"  Category: {category}")
        print(f"  URL     : {posting.apply_url}")
        print(f"  Resume  : {app.resume_path}")

        while True:
            choice = input("  Action [y/n/a/q]: ").strip().lower()
            if choice in ("y", "n", "a", "q"):
                break
            print("  Invalid input — enter y, n, a, or q")

        if choice == "y":
            app.state = ApplicationState.human_review
            await _record_transition(db, app, ApplicationState.human_review, "human_gate")
            approved += 1
        elif choice == "n":
            app.state = ApplicationState.human_rejected
            await _record_transition(db, app, ApplicationState.human_rejected, "human_gate")
            rejected += 1
        elif choice == "a":
            approve_all = True
            app.state = ApplicationState.human_review
            await _record_transition(db, app, ApplicationState.human_review, "human_gate")
            approved += 1
        elif choice == "q":
            print("\nPipeline stopped by user.")
            await db.commit()
            return approved, rejected

    await db.commit()
    return approved, rejected


async def main():
    parser = argparse.ArgumentParser(description="Run the job application pipeline")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fill forms but do not click submit")
    parser.add_argument("--limit", type=int, default=20,
                        help="Max applications to process per run (default: 20)")
    args = parser.parse_args()

    await init_db()

    print(f"\n{'='*60}")
    print(f"DRAGNET APPLICATION PIPELINE")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'} | Limit: {args.limit}")
    print('='*60)

    # Step 1: Tailoring pass
    print("\n[1/3] Tailoring pass — assigning category resumes...")
    async with SessionLocal() as db:
        tailored = await run_tailoring_pass(db, limit=args.limit)
    print(f"      Tailored: {tailored}")

    # Step 2: Human approval gate (auto-approve in dry-run)
    print("\n[2/3] Human approval gate...")
    async with SessionLocal() as db:
        approved, rejected = await approval_gate(db, limit=args.limit, auto_approve=args.dry_run)
    print(f"      Approved: {approved}  Rejected: {rejected}")

    if approved == 0 and not args.dry_run:
        print("\nNothing approved — stopping.")
        return

    # Step 3: Executor pass
    print("\n[3/3] Executor pass — submitting applications...")
    async with SessionLocal() as db:
        stats = await run_executor_pass(db, dry_run=args.dry_run)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"  Tailored  : {tailored}")
    print(f"  Approved  : {approved}")
    print(f"  Rejected  : {rejected}")
    print(f"  Submitted : {stats.get('submitted', 0)}")
    print(f"  Human queue (captcha/login wall): {stats.get('human_queue', 0)}")
    print(f"  Failed    : {stats.get('failed', 0)}")
    print('='*60)


if __name__ == "__main__":
    asyncio.run(main())
