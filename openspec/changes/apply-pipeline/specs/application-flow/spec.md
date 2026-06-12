## ADDED Requirements

### Requirement: Category PDF selection in tailoring pass
The system SHALL resolve each eligible posting's resume by looking up `raw_json["category"]` and loading the pre-compiled PDF from `output/category_resumes/<category>.pdf`. No LLM call SHALL occur during the tailoring pass.

#### Scenario: Category PDF exists
- **WHEN** a posting has `raw_json["category"] = "india_backend"` and `output/category_resumes/india_backend.pdf` exists
- **THEN** the tailoring pass sets `application.resume_path` to that PDF and advances state to `tailored`

#### Scenario: Category PDF missing
- **WHEN** the category PDF does not exist on disk
- **THEN** the tailoring pass skips the posting, logs a WARNING, and leaves state as `eligible`

### Requirement: Liveness check before tailoring
The system SHALL call `check_liveness(posting.apply_url)` before processing each posting in the tailoring pass. LinkedIn URLs (containing `linkedin.com`) SHALL be skipped (always assumed live).

#### Scenario: Posting is dead
- **WHEN** `check_liveness` returns `live=False` for a non-LinkedIn URL
- **THEN** the application state is set to `ineligible`, a StateTransition is recorded with trigger `liveness_check`, and the posting is skipped

#### Scenario: LinkedIn apply URL
- **WHEN** `posting.apply_url` contains `linkedin.com`
- **THEN** liveness check is skipped and the posting proceeds normally

### Requirement: Terminal human approval gate
The system SHALL pause before each submission during the first 50 submissions and prompt the user interactively. The prompt SHALL display company name, role title, apply URL, and category. Accepted keys: `y` (approve), `n` (reject), `a` (approve all remaining), `q` (quit pipeline).

#### Scenario: User approves
- **WHEN** user enters `y` at the prompt
- **THEN** the application proceeds to submission

#### Scenario: User rejects
- **WHEN** user enters `n` at the prompt
- **THEN** application state is set to `human_rejected` and a StateTransition is recorded

#### Scenario: User approves all
- **WHEN** user enters `a` at the prompt
- **THEN** all remaining applications in the current batch proceed without further prompts

#### Scenario: User quits
- **WHEN** user enters `q` at the prompt
- **THEN** the pipeline stops cleanly; already-submitted applications are preserved in DB

### Requirement: Dry-run mode
The pipeline script SHALL accept `--dry-run` flag. In dry-run mode, all form fields SHALL be filled but no submit button SHALL be clicked. A preflight screenshot SHALL be captured.

#### Scenario: Dry-run execution
- **WHEN** `--dry-run` is passed
- **THEN** application state is NOT advanced to `submitted`; screenshot is saved to `output/screenshots/`
