## Why

Eligible jobs are classified and stored but there is no flow that takes a job from `eligible` state through resume generation, human review, and ATS submission. The system can source and filter jobs but cannot apply to any of them yet.

## What Changes

- New `scripts/run_apply_pipeline.py`: orchestrator that reads eligible jobs from DB, generates category resumes (if not already reviewed), presents a human-approval gate, then submits via the existing ATS adapters
- New `dragnet/tailoring/unicode_normalize.py`: ATS-safe text normalization (em-dash, smart quotes, zero-width chars → ASCII) applied before every form submission
- Update `dragnet/executor/adapters/greenhouse.py`: fix LinkedIn/GitHub field detection that is currently hardcoded to skip
- Update `dragnet/executor/queue.py`: add `category` field to queued items so the right pre-reviewed resume variant is selected
- Update `scripts/import_eligible_jobs.py`: wire liveness check into import so dead postings are marked ineligible before entering the queue

## Capabilities

### New Capabilities
- `application-flow`: end-to-end flow from eligible job → resume selection → human gate → ATS submission with state tracking
- `ats-unicode-normalization`: normalize all text sent to ATS forms to ASCII-safe equivalents

### Modified Capabilities
- none

## Impact

- `dragnet/executor/` adapters (greenhouse, lever, ashby)
- `dragnet/db/models.py` (ApplicationState transitions)
- `dragnet/tailoring/resume.py` (category-based selection instead of per-job generation)
- `output/category_resumes/` — human-reviewed `.typ` files are the canonical resume source; pipeline reads these, not generates fresh ones
