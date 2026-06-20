## 1. Regenerate all 4 category resumes

- [x] 1.1 Run `python scripts/generate_category_resumes.py` — all 4 categories
- [x] 1.2 Verify each PDF: open `output/category_resumes/{india_backend,india_ai,global_backend,global_ai}.pdf` — confirm 1 page, no truncation, contact line on one line
- [x] 1.3 Check fill% in logs — all must be ≥85% (underfull warning = trim loop did not converge, investigate)

**Result**: All 4 — 1 page, fill: india_backend 92.8%, india_ai 92.8%, global_backend 90.9%, global_ai 92.8%.
**Note**: Firewall WARNING in india_ai — "70% latency reduction" hallucinated (actual: 115s→6s). Category resume continues; per-posting pipeline blocks on violations. Add 95 to facts.yaml to give LLM the correct derived number.

## 2. Lock Python dependencies

- [x] 2.1 Run `uv lock` in the project root to generate `uv.lock`
- [x] 2.2 Add `uv sync` step to `scripts/setup.sh` (replace bare `pip install -e "[dev]"`)
- [x] 2.3 Commit `uv.lock` and `scripts/setup.sh`

**Result**: Committed in `bf4c3ab`. Closes security finding from 2026-06-20 audit.

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

## 6. Ponytail — INSTALL

**Correction**: Previous "SKIP" decision was based on the WRONG package (`ponytail@1.0.57` on npm — a JavaScript UI framework). The correct tool is https://github.com/DietrichGebert/ponytail — a Claude Code skill/plugin enforcing minimal code generation ("lazy senior dev" ladder: YAGNI → stdlib → native → one-liner → minimum).

**Why it matters**: Benchmarks show 46% fewer LOC, 80% of baseline cost. Applies directly to dragnet's Python pipeline.

**Install** (requires user to run in Claude Code UI):
```
/plugin marketplace add DietrichGebert/ponytail
/plugin install ponytail@ponytail
```

**After install**:
- `/ponytail full` — default intensity for all sessions
- `/ponytail-review` — run after any PR before merge

Tracked: https://github.com/adsha27/dragnet/issues/1
