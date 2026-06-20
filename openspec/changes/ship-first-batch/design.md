## Context

WeasyPrint pipeline is live. `global_ai.pdf` was verified at 1 page, 94.7% fill. The other 3 categories (`india_backend`, `india_ai`, `global_backend`) still have Typst-era PDFs from Jun 15. `eligible_jobs.json` has 945 jobs; `prefiltered_jobs.json` has 945 jobs across the 4 category buckets. The executor supports Greenhouse, Lever, and a generic adapter. Human approval gate requires explicit `y/n/a/q` per app for the first 50 submissions.

## Goals / Non-Goals

**Goals:**
- All 4 category PDFs regenerated, verified 1-page, ≥85% fill
- Eligible jobs in DB, applications in `eligible` state
- Dry-run of 5 apps confirms form-fill works, screenshots saved, state stays `tailored` (not `submitted`)
- `uv.lock` committed so fresh installs are reproducible
- Ponytail evaluated and decision made (use / skip)

**Non-Goals:**
- Going live until dry-run passes human review
- Changing resume content or template (locked in)
- Switching job sources

## Decisions

**Resume generation order**: Run all 4 in one `generate_category_resumes.py` call. Each takes ~30s LLM call. Total ~2min. No parallelism needed.

**DB import**: `import_eligible_jobs.py` reads `output/eligible_jobs.json` → inserts Posting + Application rows. Idempotent via `external_id` dedup. Run once.

**Dry-run target**: Pick `global_backend` category (28 jobs, highest value). Run `--dry-run --limit 5`. Check screenshots in `output/screenshots/`. Visually verify form-fill before approving live run.

**Lockfile tool**: `uv` is already the standard for this project (Python 3.12, pyproject.toml). `uv lock` generates `uv.lock`. Add `uv sync` to `setup.sh`.

**Ponytail**: https://github.com/DietrichGebert/ponytail — Claude Code skill enforcing minimal code generation. Benchmarks: 46% fewer LOC, 80% cost. Install via `/plugin marketplace add DietrichGebert/ponytail`. Use `/ponytail full` each session; `/ponytail-review` before every merge. Decision: INSTALL (previously marked SKIP due to confusion with unrelated npm package).

## Risks / Trade-offs

- LLM tailoring varies per run — the 3 remaining category resumes may need fill% check and trim loop to verify ≤1 page
- Browserbase requires API key and active session — if the key in `.env` has expired, dry-run will fail at the executor stage
- `ponytail` has no README; evaluation may conclude "not applicable"
