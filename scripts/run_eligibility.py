#!/usr/bin/env python3
"""
Run LLM eligibility filter over pre-filtered jobs.
Supports checkpoint/resume — safe to kill and restart at any time.

Usage:
    python scripts/run_eligibility.py                    # full run, batch LLM
    python scripts/run_eligibility.py --fast-only        # string pre-filter only
    python scripts/run_eligibility.py --limit 50         # test on first N
    python scripts/run_eligibility.py --batch-size 5     # jobs per LLM call
    python scripts/run_eligibility.py --status           # show checkpoint progress

Checkpoint: output/eligibility_checkpoint.json — stores every processed job hash.
Resume: restart the script; already-processed jobs are skipped automatically.
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── OpenTelemetry setup ───────────────────────────────────────────────────────
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource

_provider = TracerProvider(resource=Resource.create({"service.name": "dragnet-eligibility"}))
# Console exporter — every span prints one line to stderr as structured JSON
_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(_provider)
tracer = trace.get_tracer("dragnet.eligibility")

LOG_FILE = Path("output/eligibility.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, mode="a"),
    ],
)
logger = logging.getLogger("eligibility")

CHECKPOINT_FILE = Path("output/eligibility_checkpoint.json")
ELIGIBLE_FILE = Path("output/eligible_jobs.json")


def load_checkpoint() -> dict:
    """Returns {hash: result_dict} for all previously processed jobs."""
    if CHECKPOINT_FILE.exists():
        try:
            return json.loads(CHECKPOINT_FILE.read_text())
        except Exception:
            pass
    return {}


def save_checkpoint(checkpoint: dict) -> None:
    CHECKPOINT_FILE.write_text(json.dumps(checkpoint))


def show_status():
    cp = load_checkpoint()
    total = len(cp)
    eligible = sum(1 for v in cp.values() if v.get("eligible"))
    errors = sum(1 for v in cp.values() if v.get("reject_reason") == "classification_error")
    print(f"Checkpoint: {total} processed | {eligible} eligible | {errors} errors")
    if ELIGIBLE_FILE.exists():
        eligible_jobs = json.loads(ELIGIBLE_FILE.read_text())
        print(f"Eligible file: {len(eligible_jobs)} jobs")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--fast-only", action="store_true")
    parser.add_argument("--input", default="output/prefiltered_jobs.json",
                        help="Input file (pre-filtered jobs). Default: output/prefiltered_jobs.json")
    parser.add_argument("--output", default="output/eligible_jobs.json")
    parser.add_argument("--batch-size", type=int, default=3,
                        help="Jobs per LLM call (default: 3)")
    parser.add_argument("--status", action="store_true", help="Show checkpoint progress and exit")
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    from dragnet.eligibility.classifier import pre_filter, classify_jobs_batch, BATCH_SIZE

    batch_size = args.batch_size or BATCH_SIZE

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input not found: {input_path}. Run scripts/fetch_india_jobs.py first.")
        sys.exit(1)

    jobs = json.loads(input_path.read_text())
    if args.limit:
        jobs = jobs[:args.limit]

    logger.info(f"Loaded {len(jobs)} jobs from {input_path}")

    # Pre-filter if input is raw (not pre-filtered)
    if "prefiltered" not in args.input:
        pre_passed = []
        pre_rejected = 0
        for job in jobs:
            ok, reason = pre_filter(job.get("title", ""), job.get("content_text", ""))
            if ok:
                pre_passed.append(job)
            else:
                pre_rejected += 1
        logger.info(f"Pre-filter: {len(pre_passed)} passed, {pre_rejected} rejected")
        jobs = pre_passed
    else:
        logger.info(f"Skipping pre-filter (input is already pre-filtered)")

    if args.fast_only:
        _write_eligible(jobs, args.output, "pre-filter")
        return

    # ── Checkpoint/resume ────────────────────────────────────────────────────
    checkpoint = load_checkpoint()
    pending = [j for j in jobs if j.get("dedup_hash", "") not in checkpoint]
    already_done = len(jobs) - len(pending)

    if already_done:
        logger.info(f"Resuming: {already_done} already done, {len(pending)} remaining")
    else:
        logger.info(f"Fresh run: {len(pending)} jobs to classify in batches of {batch_size}")

    # ── Batch LLM classification ─────────────────────────────────────────────
    start_time = time.time()
    batches_done = 0
    errors = 0

    for i in range(0, len(pending), batch_size):
        batch = pending[i : i + batch_size]

        with tracer.start_as_current_span("classify_batch") as span:
            span.set_attribute("batch.size", len(batch))
            span.set_attribute("batch.index", i // batch_size)
            span.set_attribute("jobs.titles", " | ".join(j.get("title", "")[:40] for j in batch))
            t0 = time.time()

            try:
                results = await classify_jobs_batch(batch)
                span.set_attribute("batch.status", "ok")
            except Exception as e:
                span.set_attribute("batch.status", "error")
                span.set_attribute("batch.error", str(e))
                logger.error(f"Batch {i//batch_size} failed: {e}")
                errors += len(batch)
                # Mark as errors in checkpoint so we don't retry endlessly
                for j in batch:
                    h = j.get("dedup_hash", "")
                    if h:
                        checkpoint[h] = {"eligible": False, "reject_reason": "classification_error"}
                save_checkpoint(checkpoint)
                continue

            elapsed = time.time() - t0
            span.set_attribute("batch.elapsed_s", round(elapsed, 1))

            for job, result in zip(batch, results):
                h = job.get("dedup_hash", "")
                if not h:
                    continue
                checkpoint[h] = {
                    "eligible": result.eligible,
                    "reject_reason": result.reject_reason,
                    "market": result.market,
                    "city": result.city,
                    "seniority": result.seniority,
                    "comp_min_lpa": result.comp_min_lpa,
                    "comp_max_lpa": result.comp_max_lpa,
                    "comp_min_usd_month": result.comp_min_usd_month,
                    "comp_max_usd_month": result.comp_max_usd_month,
                    "stack_tags": result.stack_tags,
                    "eor_signals": result.eor_signals,
                    "reasoning": result.reasoning,
                }
                if result.reject_reason == "classification_error":
                    errors += 1

            save_checkpoint(checkpoint)
            batches_done += 1

            # Flush eligible_jobs.json after every batch so progress is visible
            _flush_eligible(jobs, checkpoint, args.output, input_path)

        # Progress
        done_total = already_done + i + len(batch)
        total_jobs = already_done + len(pending)
        pct = done_total / total_jobs * 100
        elapsed_total = time.time() - start_time
        rate = batches_done * batch_size / elapsed_total if elapsed_total > 0 else 0
        remaining = (len(pending) - i - len(batch)) / max(rate, 0.001)
        eta = datetime.now(timezone.utc).strftime("%H:%Mz")
        logger.info(
            f"[{pct:.0f}%] {done_total}/{total_jobs} | "
            f"{rate:.1f} jobs/s | ETA ~{int(remaining//60)}m | errors={errors}"
        )

    # ── Compile final eligible list ───────────────────────────────────────────
    eligible = []
    for job in jobs:
        h = job.get("dedup_hash", "")
        result_data = checkpoint.get(h, {})
        if result_data.get("eligible"):
            job["_classification"] = result_data
            eligible.append(job)

    # Also include already-done jobs from previous runs that are eligible
    done_hashes = {j.get("dedup_hash", "") for j in jobs}
    for job in json.loads(input_path.read_text()):
        h = job.get("dedup_hash", "")
        if h and h not in done_hashes and checkpoint.get(h, {}).get("eligible"):
            job["_classification"] = checkpoint[h]
            eligible.append(job)

    _write_eligible(eligible, args.output, "LLM classifier")

    total_time = time.time() - start_time
    logger.info(
        f"Done. {len(eligible)} eligible | {errors} errors | "
        f"{total_time/60:.1f} min total | checkpoint at {CHECKPOINT_FILE}"
    )


def _flush_eligible(jobs: list[dict], checkpoint: dict, output_path: str, input_path: Path):
    """Write all checkpoint-eligible jobs to file — called after every batch."""
    eligible = []
    for job in jobs:
        h = job.get("dedup_hash", "")
        r = checkpoint.get(h, {})
        if r.get("eligible"):
            job["_classification"] = r
            eligible.append(job)
    Path(output_path).write_text(json.dumps(eligible, default=str))


def _write_eligible(jobs: list[dict], output_path: str, stage: str):
    out = Path(output_path)
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(jobs, indent=2, default=str))
    print(f"\n{'─'*70}")
    print(f"ELIGIBLE after {stage}: {len(jobs)}")
    print(f"{'─'*70}")
    print(f"{'TITLE':<38} {'COMPANY':<25} {'LOCATION'}")
    print(f"{'─'*70}")
    for j in sorted(jobs, key=lambda x: x.get("company_name", ""))[:40]:
        title = (j.get("title") or "")[:36]
        company = (j.get("company_name") or "")[:23]
        location = (j.get("location") or "")[:20]
        cls = j.get("_classification", {})
        comp = ""
        if cls.get("comp_min_lpa"):
            comp = f"₹{cls['comp_min_lpa']}-{cls.get('comp_max_lpa', '?')} LPA"
        elif cls.get("comp_min_usd_month"):
            comp = f"${cls['comp_min_usd_month']}/mo"
        print(f"{title:<38} {company:<25} {location:<22} {comp}")
    if len(jobs) > 40:
        print(f"  ... and {len(jobs)-40} more")
    print(f"\nSaved to {output_path}")


asyncio.run(main())
