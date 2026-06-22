"""
One-time LinkedIn authentication setup.

Opens a visible local browser so you can log in to LinkedIn and complete
any security verification. Saves session cookies to output/linkedin_cookies.json
which are then injected into all future Browserbase sessions (no re-login needed).

Usage:
    uv run python scripts/linkedin_auth.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

COOKIE_FILE = Path("output/linkedin_cookies.json")


async def main():
    from playwright.async_api import async_playwright

    print("Opening LinkedIn login in a local browser window.")
    print("Log in, complete any verification, then press Enter here to save cookies.\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=100)
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await ctx.new_page()
        await page.goto("https://www.linkedin.com/login")

        print("Browser window opened. Log in and solve any checkpoint.")
        print("Press Enter here once you're on the LinkedIn feed...")
        await asyncio.get_event_loop().run_in_executor(None, input)

        url = page.url
        if "feed" not in url and "mynetwork" not in url:
            print(f"Warning: current URL is {url} — expected LinkedIn feed.")
            print("Saving cookies anyway. You may need to re-run if they are invalid.")

        cookies = await ctx.cookies()
        COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        COOKIE_FILE.write_text(json.dumps(cookies, indent=2))
        print(f"\nSaved {len(cookies)} cookies to {COOKIE_FILE}")
        print("LinkedIn authentication set up. Future runs will use these cookies.")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
