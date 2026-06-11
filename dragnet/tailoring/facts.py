"""
facts.yaml loader and validator.
Ground truth. Immutable at runtime. The generator reads this; it does not write to it.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from dragnet.config import settings


@lru_cache(maxsize=1)
def load_facts() -> dict[str, Any]:
    return yaml.safe_load(settings.facts_path.read_text())


def get_all_numbers() -> set[str]:
    """Extract every numeric value from facts.yaml as strings for firewall comparison."""
    facts = load_facts()
    numbers: set[str] = set()
    _extract_numbers_recursive(facts, numbers)
    return numbers


def _extract_numbers_recursive(obj: Any, numbers: set[str]):
    if isinstance(obj, int):
        numbers.add(str(obj))
        numbers.add(f"{obj:,}")
    elif isinstance(obj, float):
        numbers.add(str(obj))
        numbers.add(f"{obj:.1f}")
        numbers.add(str(int(obj)))
    elif isinstance(obj, str):
        import re
        for m in re.finditer(r'\b\d[\d,]*\.?\d*\b', obj):
            numbers.add(m.group().replace(",", ""))
            numbers.add(m.group())
    elif isinstance(obj, dict):
        for v in obj.values():
            _extract_numbers_recursive(v, numbers)
    elif isinstance(obj, list):
        for item in obj:
            _extract_numbers_recursive(item, numbers)


def facts_as_context_string() -> str:
    """Serialize facts as a readable context string for LLM prompts."""
    facts = load_facts()
    lines = []

    lines.append("== POSITIONING ==")
    for stream, line in facts.get("positioning", {}).items():
        lines.append(f"  [{stream}] {line}")

    lines.append("\n== EXPERIENCE ==")
    for exp in facts.get("experience", []):
        lines.append(f"\nROLE: {exp['role']} @ {exp['company']} ({exp['start']} – {exp['end']})")
        if exp.get("context"):
            lines.append(f"  Context: {exp['context'].strip()}")

        scope = exp.get("scope_indicators", {})
        if scope:
            lines.append(f"  [SCOPE — for framing impact, NOT for direct bullet use]")
            for k, v in scope.items():
                lines.append(f"    {k}: {v}")

        lines.append(f"  [RESUME-SAFE FACTS]:")
        for fact in exp.get("facts", []):
            prep = " [INTERVIEW PREP REQUIRED — see detail before using]" if fact.get("interview_prep_required") else ""
            lines.append(f"  FACT ({fact['id']}){prep}: {fact['claim']}")
            if fact.get("detail"):
                lines.append(f"    Detail: {fact['detail']}")
            if fact.get("resume_use"):
                lines.append(f"    How to use: {fact['resume_use']}")

        stack = exp.get("stack", {})
        all_stack = (
            stack.get("languages", []) +
            stack.get("frameworks", []) +
            stack.get("concepts", []) +
            stack.get("databases", []) +
            stack.get("infra", [])
        )
        if all_stack:
            lines.append(f"  Stack: {', '.join(all_stack)}")

    lines.append("\n== PROJECTS ==")
    for proj in facts.get("projects", []):
        lines.append(f"\nPROJECT: {proj['name']} ({', '.join(proj.get('stack', []))})")
        lines.append(f"  Priority: {proj.get('priority', 'medium')}")
        for fact in proj.get("facts", []):
            lines.append(f"  FACT: {fact['claim']}")
            if fact.get("detail"):
                lines.append(f"    Detail: {fact['detail']}")
            if fact.get("resume_use"):
                lines.append(f"    How to use: {fact['resume_use']}")

    skills = facts.get("skills", {})
    lines.append("\n== SKILLS ==")
    lines.append(f"  Languages: {', '.join(skills.get('languages', {}).get('primary', []) + skills.get('languages', {}).get('secondary', []))}")
    lines.append(f"  Backend: {', '.join(skills.get('backend', []))}")
    lines.append(f"  AI/Agents: {', '.join(skills.get('ai_agents', []))}")
    lines.append(f"  Infra: {', '.join(skills.get('infra', []))}")

    return "\n".join(lines)
