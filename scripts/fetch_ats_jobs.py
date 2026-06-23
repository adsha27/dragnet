"""
Scrape Greenhouse / Lever / Ashby boards for seeded companies.
Produces output/ats_jobs.json with real apply URLs and full JD content.
No auth required — all public APIs.

Usage:
    python scripts/fetch_ats_jobs.py
    python scripts/fetch_ats_jobs.py --ats greenhouse
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from dragnet.sourcing.ats import ashby, greenhouse, lever, recruitee

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SEED_FILE = Path("slugs/seed.yaml")
OUTPUT_FILE = Path("output/ats_jobs.json")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ats", choices=["greenhouse", "lever", "ashby", "recruitee", "all"], default="all")
    args = parser.parse_args()

    seed = yaml.safe_load(SEED_FILE.read_text())
    fetchers = {
        "greenhouse": greenhouse.fetch_postings,
        "lever": lever.fetch_postings,
        "ashby": ashby.fetch_postings,
        "recruitee": recruitee.fetch_postings,
    }

    all_jobs = []
    counts = {}

    for ats_type, entries in seed.items():
        if ats_type not in fetchers:
            continue
        if args.ats != "all" and args.ats != ats_type:
            continue
        if not entries:
            continue

        for entry in entries:
            jobs = await fetchers[ats_type](entry["slug"], entry["company"])
            counts[entry["company"]] = len(jobs)
            if jobs:
                logger.info(f"  {entry['company']:30s} ({ats_type}): {len(jobs)} jobs")
            all_jobs.extend(jobs)

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(all_jobs, indent=2, default=str))

    print(f"\nTotal: {len(all_jobs)} jobs from {len(counts)} companies")
    print(f"Written to {OUTPUT_FILE}")
    print(f"\nSample apply URLs:")
    for j in all_jobs[:5]:
        print(f"  {j.get('title','?')[:40]:42} {j.get('apply_url','?')[:60]}")


if __name__ == "__main__":
    asyncio.run(main())
