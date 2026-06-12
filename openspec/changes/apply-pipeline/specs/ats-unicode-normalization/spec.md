## ADDED Requirements

### Requirement: Unicode normalization before ATS field fill
The system SHALL normalize all text sent to ATS form fields via `normalize(text: str) -> str` before passing to `session.act()`. The function SHALL convert: em-dash (–, —) → hyphen, smart quotes (' ' " ") → straight quotes, ellipsis (…) → three dots, bullet (•) → hyphen, non-breaking space → space, zero-width chars (​ ‌ ‍ ﻿) → empty string.

#### Scenario: Em-dash in job title or answer text
- **WHEN** an answer string contains `—` (em-dash)
- **THEN** `normalize()` returns the string with `—` replaced by `-`

#### Scenario: Smart quotes in answer
- **WHEN** an answer contains `"quoted text"` with curly quotes
- **THEN** `normalize()` returns `"quoted text"` with straight double quotes

#### Scenario: Clean text passthrough
- **WHEN** input text contains only ASCII printable characters
- **THEN** `normalize()` returns the string unchanged

### Requirement: LinkedIn URL in Greenhouse adapter
The Greenhouse adapter SHALL fill the LinkedIn URL field when `settings.applicant_linkedin` is set. When not set, the field SHALL be skipped without error.

#### Scenario: LinkedIn URL configured
- **WHEN** `APPLICANT_LINKEDIN` env var is set and the Greenhouse form has a LinkedIn field
- **THEN** the adapter fills the field with the configured URL

#### Scenario: LinkedIn URL not configured
- **WHEN** `APPLICANT_LINKEDIN` is empty or unset
- **THEN** the adapter skips the LinkedIn field and continues with other fields
