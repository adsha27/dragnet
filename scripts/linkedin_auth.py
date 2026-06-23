"""
One-time LinkedIn authentication setup.

Opens Chrome (automation-flag-stripped) so you can log in to LinkedIn and
complete any security verification. Saves session cookies to
output/linkedin_cookies.json which are then injected into all future
Browserbase sessions (no re-login needed).

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

    print("Opening LinkedIn login in Chrome.")
    print("IMPORTANT: Use email + password — do NOT click 'Sign in with Google'.")
    print("Complete any verification (phone/email code), then press Enter here.\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            channel="chrome",
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        await ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await ctx.new_page()
        await page.goto("https://www.linkedin.com/login")

        print("Waiting for you to log in... press Enter once you see the LinkedIn feed.")
        await asyncio.get_event_loop().run_in_executor(None, input)

        url = page.url
        if "feed" not in url and "mynetwork" not in url:
            print(f"Warning: current URL is {url}")
            print("Saving cookies anyway — re-run if they don't work.")

        cookies = await ctx.cookies()
        COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        COOKIE_FILE.write_text(json.dumps(cookies, indent=2))
        print(f"\nSaved {len(cookies)} cookies to {COOKIE_FILE}")
        print("Done. Future runs will use these cookies and skip login.")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
