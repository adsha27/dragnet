"""
Facts firewall — automated check that every number in generated content
exists in facts.yaml. This is the non-corruptible quality gate.

The check is purely string-based (not LLM). Cannot be gamed by prompt engineering.
A submission is BLOCKED if this check fails.
"""

import re
from dataclasses import dataclass, field


@dataclass
class FirewallResult:
    passed: bool
    violations: list[str] = field(default_factory=list)
    checked_numbers: list[str] = field(default_factory=list)


def check_resume_against_facts(text: str) -> FirewallResult:
    """
    Extract all standalone numbers from text and verify each exists in facts.yaml.
    Standalone = not part of a year (2023-2026), not a phone number, not a version string.
    Only checks content sections — skips Typst template directives and comments.
    """
    from dragnet.tailoring.facts import get_all_numbers

    allowed = get_all_numbers()
    content = _extract_typst_content(text)
    found_numbers = _extract_meaningful_numbers(content)

    violations = []
    for num_str in found_numbers:
        canonical = num_str.replace(",", "")
        if canonical not in allowed and num_str not in allowed:
            violations.append(f"'{num_str}' not found in facts.yaml")

    return FirewallResult(
        passed=len(violations) == 0,
        violations=violations,
        checked_numbers=list(found_numbers),
    )


def _extract_typst_content(source: str) -> str:
    """
    Extract only the content strings from Typst source — the human-visible text.
    Strips: Typst comment lines (//), layout directive lines (#set, #show, #v, #h, etc.),
    and the generated-at header block.
    """
    content_lines = []
    for line in source.splitlines():
        stripped = line.strip()
        # Skip Typst comments and generator metadata
        if stripped.startswith("//"):
            continue
        # Skip Typst layout directives
        if stripped.startswith("#") and any(
            stripped.startswith(f"#{kw}") for kw in (
                "set", "show", "align", "v(", "h(", "line(", "pagebreak",
                "grid(", "table(", "text(", "list(", "columns", "block(",
            )
        ):
            continue
        content_lines.append(line)
    return "\n".join(content_lines)


def _extract_meaningful_numbers(text: str) -> set[str]:
    """
    Extract numbers that could be fabricated claims.
    Skip: years (2020-2026), phone numbers, GPA-like decimals,
    percentage symbols, pure version numbers (1.0, 2.3.4).
    """
    numbers: set[str] = set()

    # Find all number-like tokens
    pattern = r'\b(\d[\d,]*(?:\.\d+)?)\b'
    for match in re.finditer(pattern, text):
        raw = match.group(1)
        numeric = float(raw.replace(",", ""))

        # Skip years
        if 2000 <= numeric <= 2030 and "." not in raw:
            continue

        # Skip small ordinals / percentages that don't need fact-checking (1, 2, 3, 10%)
        # We care about specific claimed metrics: 46, 1000, 115, 563, etc.
        if numeric <= 3 and "." not in raw:
            continue

        # Skip version-like patterns (e.g., "3.12", "2.0")
        if re.match(r'^\d+\.\d+$', raw) and numeric < 100:
            continue

        numbers.add(raw)
        numbers.add(raw.replace(",", ""))  # also check without comma

    return numbers
