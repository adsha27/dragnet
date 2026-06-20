## 1. Regenerate all 4 category resumes

- [ ] 1.1 Run `python scripts/generate_category_resumes.py` — all 4 categories
- [ ] 1.2 Verify each PDF: open `output/category_resumes/{india_backend,india_ai,global_backend,global_ai}.pdf` — confirm 1 page, no truncation, contact line on one line
- [ ] 1.3 Check fill% in logs — all must be ≥85% (underfull warning = trim loop did not converge, investigate)

## 2. Lock Python dependencies

- [ ] 2.1 Run `uv lock` in the project root to generate `uv.lock`
- [ ] 2.2 Add `uv sync` step to `scripts/setup.sh` (replace bare `pip install -e "[dev]"`)
- [ ] 2.3 Commit `uv.lock` and `scripts/setup.sh`

## 3. Import eligible jobs to DB

- [ ] 3.1 Ensure Postgres is running (`docker ps` or `pg_isready`)
- [ ] 3.2 Run `dragnet init` if tables don't exist yet
- [ ] 3.3 Run `python scripts/import_eligible_jobs.py` — loads `output/eligible_jobs.json` into DB
- [ ] 3.4 Verify: run `python scripts/run_apply_pipeline.py --categorize-only` or check DB row count

## 4. Dry-run 5 applications

- [ ] 4.1 Run `python scripts/run_apply_pipeline.py --dry-run --limit 5`
- [ ] 4.2 At approval gate: approve at least 3 with `y`, reject 1 with `n`, test `a` (approve all)
- [ ] 4.3 Verify screenshots saved to `output/screenshots/`
- [ ] 4.4 Verify state of approved apps is `tailored` (NOT `submitted`) in DB
- [ ] 4.5 Inspect one screenshot — confirm resume was uploaded and fields filled correctly

## 5. Go live (first batch)

- [ ] 5.1 Run `python scripts/run_apply_pipeline.py --limit 20`
- [ ] 5.2 At approval gate: review each company/role, approve selectively
- [ ] 5.3 Monitor `output/screenshots/` for CAPTCHA/login-wall failures
- [ ] 5.4 After run: check DB for `submitted` vs `human_queue` vs `failed` counts

## 6. Ponytail — SKIP

**Decision**: ponytail (npm `ponytail@1.0.57`) is a JavaScript UI component-sharing framework (TaleManager + MiddlewareManager for multi-site component reuse). Empty README, zero npm dependencies. Entirely irrelevant to dragnet, which is a Python-only backend automation pipeline with no frontend. No further action required.
