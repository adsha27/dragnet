"""
M3 — Resume generator.
LLM selects + orders bullets from facts.yaml for a specific posting.
Generates HTML → compiles to PDF via WeasyPrint → runs firewall check.
All numeric claims in output must exist in facts.yaml or submission is blocked.
"""

import hashlib
import logging
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from dragnet.config import settings
from dragnet.llm import complete_json
from dragnet.tailoring.facts import facts_as_context_string, load_facts
from dragnet.tailoring.firewall import FirewallResult, check_resume_against_facts

logger = logging.getLogger(__name__)

JINJA_ENV = Environment(
    loader=FileSystemLoader(str(settings.root / "resume_templates")),
    autoescape=select_autoescape(["html", "jinja"]),
)

SYSTEM_PROMPT = """You are a resume tailoring assistant. Select and rephrase experience bullets from a candidate's verified fact sheet to match a specific job posting.

STRICT RULES:
1. Every number you use MUST appear verbatim in the provided facts. Do not invent or estimate metrics.
2. SCOPE INDICATORS are labelled [SCOPE] in the facts. NEVER use scope indicators as resume bullets. Do not cite: 46 MCP tools, 148 tests, 88636 lines, 563 tool calls, 79.6% success rate.
3. RESUME-SAFE FACTS are labelled [RESUME-SAFE FACTS]. Use ONLY these for bullets. Every bullet must be traceable to a named fact.
4. Prefer facts that have concrete numbers. A bullet with a number (1,000 users, 156 conversations, 115s to 6s, 5 languages, 2 bots) is worth 3 generic bullets.
5. For the main role (right_walk): write 5 bullets. For supporting roles: 1-2 bullets each. Lead with what changed, not what you did.
6. Write a 2-sentence summary connecting the candidate's actual work to this specific role. Be direct. No "excited to", "would love to", "passionate about".
7. Never use em-dashes. Use a comma, period, or plain dash instead.
8. Write like a person. Avoid corporate buzzwords: leverage, spearhead, synergy, facilitate. Use plain direct words.

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
    Returns (pdf_path, html_source).
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

    html_source = _render_html(selection, facts, posting)

    firewall: FirewallResult = check_resume_against_facts(html_source)
    if not firewall.passed:
        raise ValueError(f"Firewall FAIL — invented numbers: {firewall.violations}")

    posting_hash = hashlib.sha256(
        f"{posting.get('company', '')}|{posting.get('title', '')}".encode()
    ).hexdigest()[:12]

    html_path = settings.resumes_dir / f"{posting_hash}.html"
    html_path.write_text(html_source)

    pdf_path = html_path.with_suffix(".pdf")
    HTML(string=html_source).write_pdf(str(pdf_path))

    return pdf_path, html_source


def _render_html(selection: dict, facts: dict, posting: dict) -> str:
    template = JINJA_ENV.get_template("resume.html.jinja")

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
    projects = [
        {
            "name": proj["name"],
            "stack": ", ".join(proj.get("stack", [])),
            "bullets": [f["claim"] for f in proj.get("facts", [])],
        }
        for proj in facts.get("projects", [])
        if proj["name"].lower() in included_project_names
    ]

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
        name=identity["name"],
        tagline=identity["tagline"],
        email=identity["email"],
        phone=identity["phone"],
        github=identity["github"],
        linkedin=identity.get("linkedin", ""),
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
