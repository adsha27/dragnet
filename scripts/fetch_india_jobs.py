#!/usr/bin/env python3
"""
Standalone script — fetches India jobs from LinkedIn (and Naukri if Browserbase is configured).
No database required. Prints results to stdout and writes to output/india_jobs.json.

Usage:
    python scripts/fetch_india_jobs.py
    python scripts/fetch_india_jobs.py --pages 3       # pages per query (default: 2)
    python scripts/fetch_india_jobs.py --linkedin-only
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--linkedin-only", action="store_true")
    args = parser.parse_args()

    from dragnet.sourcing import linkedin, naukri

    all_jobs = []

    print("── LinkedIn ─────────────────────────────────")
    li_jobs = await linkedin.fetch_postings(max_pages=args.pages)
    print(f"Found {len(li_jobs)} LinkedIn jobs")
    all_jobs.extend(li_jobs)

    if not args.linkedin_only:
        print("\n── Naukri ───────────────────────────────────")
        try:
            naukri_jobs = await naukri.fetch_postings()
            print(f"Found {len(naukri_jobs)} Naukri jobs")
            all_jobs.extend(naukri_jobs)
        except Exception as e:
            print(f"Naukri skipped: {e}")

    # Print summary table
    print(f"\n{'─' * 80}")
    print(f"{'TITLE':<40} {'COMPANY':<25} {'LOCATION':<20}")
    print(f"{'─' * 80}")
    for j in sorted(all_jobs, key=lambda x: x.get("company_name", "")):
        title = j.get("title", "")[:38]
        company = j.get("company_name", "")[:23]
        location = j.get("location", "")[:18]
        source = j.get("source", "")
        print(f"{title:<40} {company:<25} {location:<20} [{source}]")

    print(f"\nTotal: {len(all_jobs)} jobs")

    out = Path("output/india_jobs.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(all_jobs, indent=2, default=str))
    print(f"Saved to {out}")


asyncio.run(main())
