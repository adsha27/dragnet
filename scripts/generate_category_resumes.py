"""
Generates one tailored resume per job category.
Run after eligibility filter has built output/eligible_jobs.json.

Output: output/category_resumes/<category>.typ  (edit these)
        output/category_resumes/<category>.pdf   (compiled for review)

Usage:
    python scripts/generate_category_resumes.py
    python scripts/generate_category_resumes.py --categorize-only   # just tag categories, no resume
    python scripts/generate_category_resumes.py --category india_ai  # regenerate one
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dragnet.tailoring.categories import CATEGORIES, categorize_job
from dragnet.tailoring.facts import facts_as_context_string, load_facts
from dragnet.tailoring.firewall import check_resume_against_facts
from dragnet.llm import complete_json
from dragnet.config import settings

import subprocess
from jinja2 import Environment, FileSystemLoader

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("output/category_resumes")


def _pdf_page_count(pdf_path: Path) -> int:
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        n = doc.page_count
        doc.close()
        return n
    except Exception:
        return -1


def _pdf_fill_pct(pdf_path: Path) -> float:
    """Render page as image and find lowest non-white row."""
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        page = doc.load_page(0)
        pix = page.get_pixmap(matrix=fitz.Matrix(1, 1))
        w, h = pix.width, pix.height
        samples = pix.samples
        doc.close()
        last_row = 0
        for y in range(h - 1, -1, -1):
            row = samples[y * w * 3: (y + 1) * w * 3]
            if any(b < 245 for b in row):
                last_row = y
                break
        return last_row / h * 100
    except Exception as e:
        logger.warning(f"fill check failed: {e}")
        return -1.0

def _typst_escape(value: object) -> object:
    if isinstance(value, str):
        return value.replace("#", r"\#").replace("]", r"\]")
    return value


def _latex_escape(value: object) -> object:
    if isinstance(value, str):
        # Order matters: backslash first
        value = value.replace("\\", r"\textbackslash{}")
        value = value.replace("#",  r"\#")
        value = value.replace("&",  r"\&")
        value = value.replace("%",  r"\%")
        value = value.replace("$",  r"\$")
        value = value.replace("_",  r"\_")
        value = value.replace("^",  r"\^{}")
        value = value.replace("~",  r"\textasciitilde{}")
    return value


JINJA_ENV = Environment(
    loader=FileSystemLoader(str(settings.root / "resume_templates")),
    autoescape=False,
    finalize=_typst_escape,
)

LATEX_JINJA_ENV = Environment(
    loader=FileSystemLoader(str(settings.root / "resume_templates")),
    autoescape=False,
    finalize=_latex_escape,
    comment_start_string="<{#",   # avoid conflict with LaTeX {#1} in \newcommand
    comment_end_string="#}>",
    trim_blocks=True,
    lstrip_blocks=True,
)

SYSTEM_PROMPT = """You are a resume tailoring assistant. Given a job category and sample job descriptions, select and rephrase experience bullets from a candidate's fact sheet to produce the strongest possible resume for that category.

STRICT RULES:
1. Every number you use MUST appear verbatim in the provided facts. Do not invent or estimate metrics.
2. SCOPE INDICATORS are labelled [SCOPE] in the facts. NEVER use scope indicators as resume bullets. They exist only to help you understand scale. Do not cite: 46 MCP tools, 148 tests, 88636 lines, 563 tool calls, 79.6% success rate.
3. RESUME-SAFE FACTS are labelled [RESUME-SAFE FACTS]. Use ONLY these for bullets. Every bullet must be traceable to a named fact.
4. Prefer facts that have numbers in them. A bullet with a concrete number (1,000 users, 156 conversations, 115s to 6s, 5 languages, 2 bots) is worth 3 generic bullets.
5. For right_walk: write exactly 5 bullets. For mercury_digital: write exactly 2 bullets. For custard: write exactly 1 bullet. Lead with what changed, not what you did.
6. Write a 2-sentence summary connecting the candidate to the target category. Direct. No "excited to" or "passionate about".
7. Never use em-dashes. Use commas, periods, or plain dashes.
8. Write like a person. No buzzwords: leverage, spearhead, synergy, facilitate.
9. CRITICAL: Every bullet must be 100 characters or shorter. A bullet that wraps to a second line wastes space and looks bad. Count characters. If over 100, cut words until it fits. This is non-negotiable.

Return valid JSON only, no markdown."""

SELECTION_SCHEMA = """{
  "summary": "2-sentence summary for this category of role",
  "experience": [
    {"role_id": "right_walk", "bullets": ["...", "...", "...", "...", "..."]},
    {"role_id": "mercury_digital", "bullets": ["...", "..."]},
    {"role_id": "custard", "bullets": ["..."]}
  ],
  "include_projects": ["dragnet", "Birbal"],
  "skills_emphasis": {
    "languages": "comma-separated, most relevant first",
    "backend": "comma-separated frameworks and tools",
    "ai_agents": "comma-separated AI/agent tools",
    "infra": "comma-separated infra tools"
  }
}"""


def _categorize_prefiltered() -> dict[str, list[dict]]:
    """Read prefiltered jobs and group by category (adds category field)."""
    jobs_path = Path("output/prefiltered_jobs.json")
    if not jobs_path.exists():
        logger.error("output/prefiltered_jobs.json not found")
        sys.exit(1)
    jobs = json.loads(jobs_path.read_text())
    buckets: dict[str, list[dict]] = {k: [] for k in CATEGORIES}
    for job in jobs:
        cat = categorize_job(job)
        job["category"] = cat
        buckets[cat].append(job)
    return buckets


def _pick_samples(jobs: list[dict], n: int = 5) -> list[dict]:
    """Pick n representative jobs — prefer those with content_text."""
    with_content = [j for j in jobs if j.get("content_text") and len(j["content_text"]) > 100]
    pool = with_content if with_content else jobs
    step = max(1, len(pool) // n)
    return pool[::step][:n]


async def generate_one(category: str, jobs: list[dict]) -> None:
    cat_info = CATEGORIES[category]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    samples = _pick_samples(jobs)
    sample_text = "\n\n---\n\n".join(
        f"Title: {j.get('title', '?')}\nCompany: {j.get('company_name') or j.get('company', '?')}\nLocation: {j.get('location', '?')}\n{(j.get('content_text') or '')[:600]}"
        for j in samples
    )

    facts_context = facts_as_context_string()
    facts = load_facts()

    prompt = f"""CATEGORY: {cat_info['label']}
DESCRIPTION: {cat_info['description']}

SAMPLE JOB POSTINGS FROM THIS CATEGORY ({len(jobs)} total):
{sample_text}

CANDIDATE FACTS (only these may be used):
{facts_context}

Select and tailor bullets from these facts to best match this job category.
Return JSON matching this schema:
{SELECTION_SCHEMA}"""

    logger.info(f"Generating resume for: {cat_info['label']}")
    selection = await complete_json(SYSTEM_PROMPT, prompt, max_tokens=2048)

    # Enforce project selection — LLM guidance is advisory; code is authoritative
    selection["include_projects"] = ["dragnet", "Birbal"]

    # Pre-resolve projects as mutable list so trim loop can shed bullets
    included_names = {p.lower() for p in selection["include_projects"]}
    selection["_projects_rendered"] = [
        {
            "name": proj["name"],
            "stack": ", ".join(proj.get("stack", [])),
            "bullets": [f["claim"] for f in proj.get("facts", [])[:3]],
        }
        for proj in facts.get("projects", [])
        if proj["name"].lower() in included_names
    ]

    # Trim-to-fit loop: compile, check pages, shed content until 1 page
    typ_path = OUTPUT_DIR / f"{category}.typ"
    pdf_path = typ_path.with_suffix(".pdf")
    rw_entry = next((e for e in selection.get("experience", []) if e.get("role_id") == "right_walk"), None)
    md_entry = next((e for e in selection.get("experience", []) if e.get("role_id") == "mercury_digital"), None)

    def _trim_one(attempt: int) -> bool:
        """Remove one bullet. Returns True if something was trimmed."""
        # 1. RWF down to 2
        if rw_entry and len(rw_entry["bullets"]) > 2:
            dropped = rw_entry["bullets"].pop()
            logger.info(f"Overflow (attempt {attempt}): dropped RWF bullet: {dropped[:60]}…")
            return True
        # 2. Mercury down to 1
        if md_entry and len(md_entry["bullets"]) > 1:
            dropped = md_entry["bullets"].pop()
            logger.info(f"Overflow (attempt {attempt}): dropped Mercury bullet: {dropped[:60]}…")
            return True
        # 3. Project bullets down to 1 each (in order)
        for proj in selection["_projects_rendered"]:
            if len(proj["bullets"]) > 1:
                dropped = proj["bullets"].pop()
                logger.info(f"Overflow (attempt {attempt}): dropped {proj['name']} bullet: {dropped[:60]}…")
                return True
        return False

    for attempt in range(12):
        typst_source = _render_typst(selection, facts, cat_info)
        typ_path.write_text(typst_source)
        try:
            result = subprocess.run(
                ["typst", "compile", str(typ_path), str(pdf_path)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                logger.warning(f"typst compile failed:\n{result.stderr[:300]}")
                break
            pages = _pdf_page_count(pdf_path)
            if pages == 1:
                break
            if not _trim_one(attempt + 1):
                logger.warning(f"Cannot trim further — still {pages} pages")
                break
        except Exception as e:
            logger.warning(f"Compile error: {e}")
            break

    firewall = check_resume_against_facts(typst_source)
    if not firewall.passed:
        logger.warning(f"Firewall violations in {category}: {firewall.violations}")

    fill = _pdf_fill_pct(pdf_path)
    fill_warn = " *** UNDERFULL ***" if 0 < fill < 85 else ""
    logger.info(f"Written: {typ_path}")
    logger.info(f"Compiled (typst): {pdf_path}  pages={_pdf_page_count(pdf_path)}  fill={fill:.1f}%{fill_warn}")

    # LaTeX output
    latex_source = _render_latex(selection, facts, cat_info)
    tex_path = OUTPUT_DIR / f"{category}.tex"
    tex_path.write_text(latex_source)
    logger.info(f"Written: {tex_path}")

    try:
        import shutil
        latex_out_dir = OUTPUT_DIR / "latex"
        latex_out_dir.mkdir(exist_ok=True)
        if shutil.which("tectonic"):
            result = subprocess.run(
                ["tectonic", str(tex_path), "--outdir", str(latex_out_dir)],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                logger.info(f"Compiled (latex): {latex_out_dir / tex_path.with_suffix('.pdf').name}")
            else:
                logger.warning(f"tectonic failed for {category}:\n{result.stderr[:300]}\n{result.stdout[:300]}")
        else:
            logger.warning("tectonic not found — skipping LaTeX PDF compile")
    except Exception as e:
        logger.warning(f"Could not compile LaTeX PDF for {category}: {e}")


def _render_typst(selection: dict, facts: dict, cat_info: dict) -> str:
    template = JINJA_ENV.get_template("resume.typ.jinja")
    from datetime import datetime

    identity = facts["identity"]
    skills_sel = selection.get("skills_emphasis", {})
    skills_defaults = facts.get("skills", {})

    roles_map = {
        "right_walk": next((e for e in facts["experience"] if "Right Walk" in e["company"]), None),
        "mercury_digital": next((e for e in facts["experience"] if "Mercury" in e.get("company", "")), None),
        "custard": next((e for e in facts["experience"] if "Custard" in e.get("company", "")), None),
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

    # Use pre-resolved (and trim-loop-mutable) projects when available
    if "_projects_rendered" in selection:
        projects = selection["_projects_rendered"]
    else:
        included_project_names = {p.lower() for p in selection.get("include_projects", [])}
        projects = [
            {
                "name": proj["name"],
                "stack": ", ".join(proj.get("stack", [])),
                "bullets": [f["claim"] for f in proj.get("facts", [])[:3]],
            }
            for proj in facts.get("projects", [])
            if proj["name"].lower() in included_project_names
        ]

    education = [
        {
            "degree": edu["degree"],
            "institution": edu["institution"],
            "cgpa": edu["cgpa"],
            "graduation": edu.get("graduation", ""),
        }
        for edu in facts.get("education", [])
    ]

    return template.render(
        generated_at=datetime.utcnow().isoformat(),
        company=cat_info["label"],
        title=cat_info["description"][:60],
        name=identity["name"],
        tagline=identity["tagline"],
        email=identity["email"],
        email_display=identity["email"].replace("@", r"\@"),
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


def _render_latex(selection: dict, facts: dict, cat_info: dict) -> str:
    template = LATEX_JINJA_ENV.get_template("resume.tex.jinja")
    from datetime import datetime

    identity = facts["identity"]
    skills_sel = selection.get("skills_emphasis", {})
    skills_defaults = facts.get("skills", {})

    roles_map = {
        "right_walk": next((e for e in facts["experience"] if "Right Walk" in e["company"]), None),
        "mercury_digital": next((e for e in facts["experience"] if "Mercury" in e.get("company", "")), None),
        "custard": next((e for e in facts["experience"] if "Custard" in e.get("company", "")), None),
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

    if "_projects_rendered" in selection:
        projects = selection["_projects_rendered"]
    else:
        included_project_names = {p.lower() for p in selection.get("include_projects", [])}
        projects = [
            {
                "name": proj["name"],
                "stack": ", ".join(proj.get("stack", [])),
                "bullets": [f["claim"] for f in proj.get("facts", [])[:3]],
            }
            for proj in facts.get("projects", [])
            if proj["name"].lower() in included_project_names
        ]

    education = [
        {
            "degree": edu["degree"],
            "institution": edu["institution"],
            "cgpa": edu["cgpa"],
            "graduation": edu.get("graduation", ""),
        }
        for edu in facts.get("education", [])
    ]

    return template.render(
        generated_at=datetime.utcnow().isoformat(),
        company=cat_info["label"],
        title=cat_info["description"][:60],
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


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--categorize-only", action="store_true",
                        help="Tag jobs with categories and print stats, no resume generation")
    parser.add_argument("--category", help="Generate resume for one category only")
    args = parser.parse_args()

    buckets = _categorize_prefiltered()

    print("\nCategory distribution (from prefiltered_jobs.json):")
    total = 0
    for cat, jobs in buckets.items():
        print(f"  {CATEGORIES[cat]['label']:35s}  {len(jobs):4d} jobs")
        total += len(jobs)
    print(f"  {'TOTAL':35s}  {total:4d}\n")

    if args.categorize_only:
        return

    targets = [args.category] if args.category else list(CATEGORIES.keys())
    for cat in targets:
        if cat not in CATEGORIES:
            logger.error(f"Unknown category: {cat}")
            continue
        jobs = buckets[cat]
        if not jobs:
            logger.warning(f"No jobs in category {cat}, skipping")
            continue
        await generate_one(cat, jobs)

    print(f"\nResumes written to: {OUTPUT_DIR}/")
    print("Edit the .typ files, then recompile:")
    print("  typst compile output/category_resumes/india_backend.typ")


if __name__ == "__main__":
    asyncio.run(main())
