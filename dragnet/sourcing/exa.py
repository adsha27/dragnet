"""
Exa-powered company discovery.
Finds AI/backend companies that are likely global-remote hirers.
Returns company names + domains for slug discovery.
"""

import logging
from dataclasses import dataclass

from exa_py import Exa

from dragnet.config import settings

logger = logging.getLogger(__name__)

DISCOVERY_QUERIES = [
    "AI startup hiring backend engineer remote worldwide 2026",
    "seed series A LLM infrastructure company hiring engineers globally Deel Remote.com",
    "developer tools startup hiring software engineer remote international",
    "open source backend infrastructure company hiring globally 2026",
    "YC company hiring backend engineer remote global",
    "AI agent platform startup hiring software engineer worldwide",
    "serverless infrastructure startup hiring globally employer of record",
]


@dataclass
class DiscoveredCompany:
    name: str
    domain: str
    url: str
    snippet: str


async def discover_companies(max_results_per_query: int = 10) -> list[DiscoveredCompany]:
    """Run discovery queries and return deduped company list."""
    client = Exa(api_key=settings.exa_api_key)
    seen_domains: set[str] = set()
    results: list[DiscoveredCompany] = []

    for query in DISCOVERY_QUERIES:
        try:
            response = client.search_and_contents(
                query,
                num_results=max_results_per_query,
                type="neural",
                use_autoprompt=True,
                text={"max_characters": 500},
            )
            for item in response.results:
                domain = _extract_domain(item.url)
                if domain and domain not in seen_domains:
                    seen_domains.add(domain)
                    results.append(DiscoveredCompany(
                        name=item.title or domain,
                        domain=domain,
                        url=item.url,
                        snippet=item.text or "",
                    ))
        except Exception as e:
            logger.error(f"Exa discovery failed for query '{query}': {e}")

    logger.info(f"Discovered {len(results)} unique companies via Exa")
    return results


async def find_career_page(company_name: str, domain: str) -> str | None:
    """Find the careers/jobs page for a company using Exa."""
    client = Exa(api_key=settings.exa_api_key)
    query = f"{company_name} careers jobs remote software engineer"
    try:
        response = client.search(
            query,
            num_results=3,
            include_domains=[domain],
        )
        for item in response.results:
            url_lower = item.url.lower()
            if any(kw in url_lower for kw in ["/careers", "/jobs", "/job", "greenhouse.io", "lever.co", "ashbyhq.com"]):
                return item.url
    except Exception as e:
        logger.error(f"Exa career page lookup failed for {company_name}: {e}")
    return None


def _extract_domain(url: str) -> str | None:
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain if domain else None
    except Exception:
        return None
