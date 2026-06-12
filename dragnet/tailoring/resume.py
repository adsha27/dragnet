"""
M3 — Resume generator.
LLM selects + orders bullets from facts.yaml for a specific posting.
Generates Typst source → compiles to PDF → runs firewall check.
All numeric claims in output must exist in facts.yaml or submission is blocked.
"""

import hashlib
import json
import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from dragnet.config import settings
from dragnet.llm import complete_json
from dragnet.tailoring.facts import facts_as_context_string, load_facts
from dragnet.tailoring.firewall import FirewallResult, check_resume_against_facts

logger = logging.getLogger(__name__)

def _typst_escape(value: object) -> object:
    if isinstance(value, str):
        # Escape Typst special chars that break content mode
        return value.replace("#", r"\#").replace("]", r"\]")
    return value


JINJA_ENV = Environment(
    loader=FileSystemLoader(str(settings.root / "resume_templates")),
    autoescape=False,
    finalize=_typst_escape,
)

SYSTEM_PROMPT = """You are a resume tailoring assistant. Select and rephrase experience bullets from a candidate's verified fact sheet to match a specific job posting.

STRICT RULES:
1. Every number you use MUST appear in the provided facts. Do not invent metrics.
2. Do NOT use raw internal counts as bullets. Do not write "46 MCP tools", "148 test cases", "563 tool calls", "172 commits", "88,636 lines". These are scope context, not resume points.
3. Use scope numbers to frame impact and scale. "46 MCP tools" becomes "built the MCP tool layer covering the full government-portal workflow end to end."
4. Do not claim skills not in the facts. Select, reorder, rephrase - do not invent.
5. Select 3-5 bullets per role. Lead with what changed, not what you did.
6. Write a 2-sentence summary connecting the candidate's actual work to this specific role. Be direct. No "excited to", "would love to", "passionate about".
7. Never use em-dashes. Use a comma, period, or plain dash instead.
8. Write like a person, not a language model. Avoid corporate buzzwords: leverage, spearhead, synergy, facilitate. Use plain direct words.
9. For the 115s to 6s benchmark: only use those numbers if interview_prep_required is false. Otherwise use the framing: "removed BAML orchestration and inline DB operations from the hot path, making the pipeline purely LLM-bound."

Return valid JSON only, no markdown or explanation."""

SELECTION_SCHEMA = """{
  "summary": "string (2 sentences, connects facts to this specific role)",
  "experience": [
    {
      "role_id": "string (e.g., 'right_walk', 'mercury_digital', 'custard')",
      "bullets": ["string", "string", "string"]
    }
  ],
  "include_projects": ["string (project name)"],
  "skills_emphasis": {
    "languages": "string (comma-separated, most relevant first)",
    "backend": "string",
    "ai_agents": "string",
    "infra": "string"
  }
}"""


async def generate_resume(posting: dict) -> tuple[Path, str]:
    """
    Generate a tailored resume for a posting.
    Returns (pdf_path, typst_source).
    Raises ValueError if firewall check fails.
    """
    facts_context = facts_as_context_string()
    facts = load_facts()

    prompt = f"""JOB POSTING:
Company: {posting.get('company', '')}
Title: {posting.get('title', '')}
Description:
{posting.get('text', posting.get('content_text', ''))[:3000]}

CANDIDATE FACTS (these are the ONLY facts you may use):
{facts_context}

Select and tailor bullets from these facts to match this posting.
Return JSON matching this schema:
{SELECTION_SCHEMA}"""

    selection = await complete_json(SYSTEM_PROMPT, prompt, max_tokens=2048)

    typst_source = _render_typst(selection, facts, posting)

    firewall: FirewallResult = check_resume_against_facts(typst_source)
    if not firewall.passed:
        raise ValueError(f"Firewall FAIL — invented numbers: {firewall.violations}")

    posting_hash = hashlib.sha256(
        f"{posting.get('company', '')}|{posting.get('title', '')}".encode()
    ).hexdigest()[:12]

    typ_path = settings.resumes_dir / f"{posting_hash}.typ"
    typ_path.write_text(typst_source)

    pdf_path = _compile_typst(typ_path)

    return pdf_path, typst_source


def _render_typst(selection: dict, facts: dict, posting: dict) -> str:
    template = JINJA_ENV.get_template("resume.typ.jinja")

    identity = facts["identity"]
    skills_sel = selection.get("skills_emphasis", {})
    skills_defaults = facts.get("skills", {})

    roles_map = {
        "right_walk": next((e for e in facts["experience"] if "Right Walk" in e["company"]), None),
        "mercury_digital": next((e for e in facts["experience"] if "Mercury" in e["company"]), None),
        "custard": next((e for e in facts["experience"] if "Custard" in e["company"]), None),
    }

    experience = []
    for role_sel in selection.get("experience", []):
        role_id = role_sel.get("role_id", "")
        role_data = roles_map.get(role_id)
        if not role_data:
            continue
        experience.append({
            "title": role_data["role"],
            "company": role_data["company"],
            "location": role_data["location"],
            "start": role_data["start"],
            "end": role_data["end"],
            "bullets": role_sel.get("bullets", []),
        })

    included_project_names = {p.lower() for p in selection.get("include_projects", [])}
    projects = []
    for proj in facts.get("projects", []):
        if proj["name"].lower() in included_project_names:
            projects.append({
                "name": proj["name"],
                "stack": ", ".join(proj.get("stack", [])),
                "bullets": [f["claim"] for f in proj.get("facts", [])],
            })

    education = [
        {
            "degree": edu["degree"],
            "institution": edu["institution"],
            "cgpa": edu["cgpa"],
            "graduation": edu["graduation"],
        }
        for edu in facts.get("education", [])
    ]

    return template.render(
        generated_at=datetime.utcnow().isoformat(),
        company=posting.get("company", ""),
        title=posting.get("title", ""),
        name=identity["name"],
        tagline=identity["tagline"],
        email=identity["email"],
        email_display=identity["email"].replace("@", r"\@"),
        phone=identity["phone"],
        github=identity["github"],
        summary=selection.get("summary", ""),
        experience=experience,
        projects=projects,
        skills={
            "languages": skills_sel.get("languages", ", ".join(
                skills_defaults.get("languages", {}).get("primary", []) +
                skills_defaults.get("languages", {}).get("secondary", [])
            )),
            "backend": skills_sel.get("backend", ", ".join(skills_defaults.get("backend", []))),
            "ai_agents": skills_sel.get("ai_agents", ", ".join(skills_defaults.get("ai_agents", []))),
            "infra": skills_sel.get("infra", ", ".join(skills_defaults.get("infra", []))),
        },
        education=education,
    )


def _compile_typst(typ_path: Path) -> Path:
    if not shutil.which("typst"):
        raise EnvironmentError("typst CLI not found. Install: https://github.com/typst/typst/releases")

    pdf_path = typ_path.with_suffix(".pdf")
    result = subprocess.run(
        ["typst", "compile", str(typ_path), str(pdf_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"typst compile failed:\n{result.stderr}")

    return pdf_path
