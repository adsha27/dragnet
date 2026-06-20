## ADDED Requirements

### Requirement: Lockfile exists and is committed

All Python dependencies must be pinned to exact versions via `uv.lock`.

#### Scenario: Fresh install is reproducible
- **WHEN** a new developer runs `uv sync`
- **THEN** they get the exact same package versions as the original environment

#### Scenario: Lockfile is tracked
- **WHEN** `git ls-files uv.lock` is run
- **THEN** the file appears (it is committed, not gitignored)
