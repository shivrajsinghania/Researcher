"""
Main pipeline orchestrator — runs all steps in sequence, updating job
progress in storage at each step. Designed to run in a background thread.
"""
import traceback
from datetime import datetime

import storage
from pipeline import searcher, crawler, pdf_handler, browser, merger
import config


def run(job_id: str, service_name: str, state: str,
        existing_record: dict = None):
    """
    Full research pipeline. Runs blocking — call from a thread.
    existing_record is passed in re-verify mode; it's used by the merger
    to compute a diff but the pipeline logic itself is the same.
    """

    def log(msg: str):
        storage.upsert_job(job_id, service_name, state,
                           status="running", progress=msg)
        print(f"[{job_id}] {msg}")

    try:
        log("Starting research pipeline...")

        domains = list(config.WHITELIST.get(state, []))
        if not domains:
            raise ValueError(f"No whitelisted domains configured for scope: {state}")

        # ── Step 1: Discovery ────────────────────────────────────────
        log("Step 1/4 — Discovering pages and PDFs on official sites...")
        discovered = searcher.discover(service_name, state, log=log)
        page_urls = discovered["page_urls"]
        pdf_urls = discovered["pdf_urls"]

        if not page_urls and not pdf_urls:
            log("Warning: no pages or PDFs found via search. Trying direct domain probe...")

        # ── Step 2: HTML Crawl ───────────────────────────────────────
        log(f"Step 2/4 — Crawling {len(page_urls)} page(s)...")
        pages = crawler.crawl_all(page_urls, state, log=log)

        extra_pdfs = []
        for p in pages:
            for pl in p.get("pdf_links", []):
                if pl not in pdf_urls:
                    extra_pdfs.append(pl)
        pdf_urls = (pdf_urls + extra_pdfs)[:config.MAX_PDFS]

        # ── Step 3: PDF Extraction ───────────────────────────────────
        log(f"Step 3/4 — Extracting {len(pdf_urls)} PDF(s)...")
        pdfs = pdf_handler.extract_all(pdf_urls, log=log)

        # ── Step 3b: Browser automation ─────────────────────────────
        apply_url = _guess_apply_url(service_name, state, pages)
        browser_result = None
        if apply_url and config.PLAYWRIGHT_ENABLED:
            log("Step 3b — Browser automation on apply page...")
            browser_result = browser.automate(apply_url, service_name, log=log)
            if browser_result.get("error"):
                log(f"Browser step error (non-fatal): {browser_result['error']}")
            extra_from_browser = browser_result.get("extra_pdf_links", [])
            for pl in extra_from_browser:
                if pl not in pdf_urls and len(pdfs) < config.MAX_PDFS:
                    new_pdf = pdf_handler.extract_pdf(pl)
                    pdfs.append(new_pdf)
        else:
            log("Step 3b — Skipping browser automation (no apply URL found or disabled).")

        # ── Step 4: Merge via Gemini ─────────────────────────────────
        log("Step 4/4 — Merging with Gemini...")
        raw = {
            "pages": pages,
            "pdfs": pdfs,
            "browser": browser_result,
        }
        record = merger.merge(service_name, state, raw, log=log)

        # In re-verify mode, annotate the record with what changed
        if existing_record:
            record["_diff"] = _compute_diff(existing_record, record)
            record["_is_reverify"] = True
        else:
            record["_is_reverify"] = False

        log("Pipeline complete!")
        storage.upsert_job(job_id, service_name, state,
                           status="done", result=record)

    except Exception as exc:
        err = traceback.format_exc()
        print(f"[{job_id}] PIPELINE ERROR:\n{err}")
        storage.upsert_job(job_id, service_name, state,
                           status="error", error=str(exc))


def _guess_apply_url(service_name: str, state: str, pages: list[dict]) -> str | None:
    """
    Look for an "Apply Online" link across all crawled pages.
    Falls back to the known portal root.
    """
    import re
    keywords = re.compile(r"apply|application|online|register|form", re.I)
    for page in pages:
        from bs4 import BeautifulSoup
        import requests

        if not page.get("url"):
            continue
        apply_kw = re.compile(
            r"(apply\s*online|online\s*application|click\s*here\s*to\s*apply|register\s*now)",
            re.I,
        )
        if apply_kw.search(page.get("text", "")):
            return page["url"]

    domains = list(config.WHITELIST.get(state, []))
    if state == "Bihar" and domains:
        return f"https://{domains[0]}"
    if domains:
        return f"https://{domains[0]}"
    return None


def _compute_diff(old: dict, new: dict) -> dict:
    """
    Returns {field: {old: ..., new: ...}} for fields that changed.
    Only compares the top-level schema fields (not internal ones starting with _).
    """
    diff = {}
    all_fields = [
        "department", "portal_name", "portal_url", "apply_url", "documents",
        "eligibility", "fees", "timeline", "photo_size", "signature_size",
        "upload_limits", "validity", "steps", "notes", "sources", "category",
    ]
    for f in all_fields:
        o = old.get(f)
        n = new.get(f)
        if str(o) != str(n):
            diff[f] = {"old": o, "new": n}
    return diff
