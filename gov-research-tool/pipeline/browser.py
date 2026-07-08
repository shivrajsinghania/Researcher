"""
Browser automation step — uses Playwright Chromium to open the actual
"Apply Online" page (or portal home) and extract:
  - Visible form fields (tells us what documents/info is required)
  - Photo/signature dimension text in instructions
  - Step-by-step flow from breadcrumbs or numbered lists
  - Any PDF links not found by the plain crawler
"""
import asyncio
import re

import config


async def _run_browser(url: str, service_name: str) -> dict:
    from playwright.async_api import async_playwright

    result = {
        "url": url,
        "text": "",
        "form_fields": [],
        "photo_signature_text": "",
        "steps_text": "",
        "extra_pdf_links": [],
        "error": None,
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process",
            ],
        )
        try:
            page = await browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120 Mobile Safari/537.36"
                ),
                viewport={"width": 390, "height": 844},
            )
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            body_text = await page.evaluate("document.body.innerText")
            result["text"] = body_text[:6000]

            labels = await page.eval_on_selector_all(
                "label, .form-label, th, legend",
                "els => els.map(e => e.innerText.trim()).filter(t => t.length > 0 && t.length < 120)"
            )
            result["form_fields"] = labels[:40]

            photo_kw = re.compile(
                r"(photo|photograph|image|picture|signature|size|dimension|kb|pixel|px|cm|mm|jpeg|jpg)",
                re.I,
            )
            photo_hits = []
            for line in body_text.split("\n"):
                if photo_kw.search(line) and len(line.strip()) > 8:
                    photo_hits.append(line.strip())
            result["photo_signature_text"] = "\n".join(photo_hits[:20])

            numbered = await page.eval_on_selector_all(
                "ol li, .steps li, .step-item, [class*='step']",
                "els => els.map(e => e.innerText.trim()).filter(t => t.length > 5)"
            )
            result["steps_text"] = "\n".join(numbered[:20])

            pdf_links = await page.eval_on_selector_all(
                "a[href$='.pdf'], a[href*='.pdf']",
                "els => els.map(e => e.href)"
            )
            result["extra_pdf_links"] = [l for l in pdf_links if l][:5]

        except Exception as e:
            result["error"] = str(e)
        finally:
            await browser.close()

    return result


def automate(apply_url: str, service_name: str, log=None) -> dict:
    """
    Synchronous wrapper around the async Playwright step.
    Returns the result dict from _run_browser.
    """
    if not config.PLAYWRIGHT_ENABLED:
        return {
            "url": apply_url,
            "text": "",
            "form_fields": [],
            "photo_signature_text": "",
            "steps_text": "",
            "extra_pdf_links": [],
            "error": "playwright_disabled",
        }
    if log:
        log(f"Browser automation: opening {apply_url[:60]}...")
    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(_run_browser(apply_url, service_name))
        loop.close()
        return result
    except Exception as e:
        if log:
            log(f"Browser step failed: {e}")
        return {
            "url": apply_url,
            "text": "",
            "form_fields": [],
            "photo_signature_text": "",
            "steps_text": "",
            "extra_pdf_links": [],
            "error": str(e),
        }
