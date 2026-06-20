## ADDED Requirements

### Requirement: Ponytail evaluated and decision documented

The npm package `ponytail` must be researched and a use/skip decision recorded.

#### Scenario: Evaluation complete
- **WHEN** research is done
- **THEN** a one-paragraph decision note exists in design.md explaining what ponytail does and whether it applies to dragnet

#### Scenario: Decision is actionable
- **WHEN** ponytail is relevant
- **THEN** integration task is added to tasks.md
- **WHEN** ponytail is not relevant
- **THEN** decision is recorded as "skip — reason" and no further work is done
