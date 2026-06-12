## Context

The current queue.py `run_tailoring_pass` calls `generate_resume()` per job — an LLM call for each posting that generates a fresh Typst file and compiles it. This is slow (300s per call), non-deterministic, and bypasses human review. The category system built in the previous session produces 4 pre-reviewed resumes; the pipeline should use those instead.

The greenhouse.py adapter skips LinkedIn with a placeholder comment and has no unicode normalization before form filling. ATS parsers (especially older Greenhouse tenants) reject em-dashes and smart quotes.

Current state:
- `output/category_resumes/<category>.typ` — human-edited source
- `output/category_resumes/<category>.pdf` — compiled PDF
- `dragnet/db/models.py` — `Application.state` tracks the full lifecycle
- `dragnet/executor/queue.py` — tailoring + executor passes exist but use per-job LLM
- `dragnet/executor/adapters/greenhouse.py` — LinkedIn field skipped

## Goals / Non-Goals

**Goals:**
- Replace per-job LLM resume generation with category-PDF lookup (zero LLM calls in tailoring pass)
- Add Unicode normalization to all text sent to ATS form fields
- Fix LinkedIn URL field in Greenhouse adapter
- Add liveness check before tailoring so dead postings skip the queue
- Produce a `scripts/run_apply_pipeline.py` that runs the full cycle: import → liveness → tailor → human gate → submit

**Non-Goals:**
- Cover letter generation (out of scope for now)
- Lever/Ashby adapters (Greenhouse first, others follow same pattern)
- Building a TUI dashboard (CLI output is sufficient)
- Automatic retry on captcha (human queue handles it)

## Decisions

**D1: Category PDF as resume, not per-job generation**

The tailoring pass will look up `raw_json["category"]` on the Posting, then resolve to `output/category_resumes/<category>.pdf`. If the PDF doesn't exist (human hasn't reviewed yet), the posting stays in `eligible` state and is skipped. No LLM call. No firewall check needed — the human already reviewed the source.

Alternative: generate a fresh resume per job each time. Rejected: too slow (300s/job), non-deterministic, and defeats the point of human review.

**D2: Unicode normalization as a thin wrapper, not in the adapter**

Add `dragnet/tailoring/unicode_normalize.py` with a single `normalize(text: str) -> str` function. The queue.py executor pass calls it on every string before passing to `session.act(...)`. Keeping it out of the adapter makes it testable without a browser.

**D3: Liveness check in tailoring pass, not import**

Run `check_liveness(posting.apply_url)` at the start of the tailoring pass (not at import time). Job postings can die between import and application. If dead, mark Application.state = `ineligible` and record a transition. This keeps import fast.

Alternative: check at import. Rejected: 945 HTTP requests at import time is slow and many postings are live when imported but die later. Checking right before tailoring catches the freshest state.

**D4: Human gate via terminal prompt**

The `run_apply_pipeline.py` script pauses before each submission (for first 50) and prints the company, title, apply URL, and category. User types `y` to submit, `n` to reject, `q` to quit. Simple, no UI needed. After 50 submissions, sample at 10% (existing logic in queue.py).

**D5: LinkedIn fix — use settings.applicant_linkedin**

Add `applicant_linkedin` to `dragnet/config.py` (reads from env `APPLICANT_LINKEDIN`). Greenhouse adapter uses it to fill the LinkedIn field instead of the current skip. Falls back gracefully if not set.

## Risks / Trade-offs

- [Human gate bottleneck] → Accepting a batch of N postings at once (bulk approve) reduces friction; implement as `a` key in the terminal prompt ("approve all remaining")
- [Category PDF not found] → Pipeline skips the posting silently; log at WARNING so user knows to run `generate_category_resumes.py` first
- [Liveness check rate limits] → LinkedIn URLs return 999 for bots; skip liveness check for `linkedin.com` apply URLs (they redirect to auth wall anyway) and only check direct ATS URLs

## Migration Plan

1. Run `python scripts/generate_category_resumes.py` to produce 4 PDFs; user reviews and edits `.typ` files, recompiles
2. Run `python scripts/import_eligible_jobs.py` to populate DB
3. Run `python scripts/run_apply_pipeline.py --dry-run` to verify form-fill without submitting
4. Run without `--dry-run` for live submissions

No data migration needed — DB schema is unchanged. ApplicationState enum gains no new values.
