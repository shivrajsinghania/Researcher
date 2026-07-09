"""
Main pipeline orchestrator — runs all steps in sequence in a background thread.
"""
import traceback

import storage
from pipeline import searcher, crawler, pdf_handler, browser, merger
import config


def run(job_id: str, service_name: str, state: str, existing_record: dict = None):
    def log(msg: str):
        storage.upsert_job(job_id, service_name, state, status="running", progress=msg)
        print(f"[{job_id}] {msg}")

    try:
        log("Starting research pipeline...")

        domains = list(config.WHITELIST.get(state, []))
        if not domains:
            raise ValueError(f"No whitelisted domains configured for scope: {state}")

        log("Step 1/4 — Discovering pages and PDFs on official sites...")
        discovered = searcher.discover(service_name, state, log=log)
        page_urls = discovered["page_urls"]
        pdf_urls = discovered["pdf_urls"]

        log(f"Step 2/4 — Crawling {len(page_urls)} page(s)...")
        pages = crawler.crawl_all(page_urls, state, log=log)

        extra_pdfs = []
        for p in pages:
            for pl in p.get("pdf_links", []):
                if pl not in pdf_urls:
                    extra_pdfs.append(pl)
        pdf_urls = (pdf_urls + extra_pdfs)[: config.MAX_PDFS]

        log(f"Step 3/4 — Extracting {len(pdf_urls)} PDF(s)...")
        pdfs = pdf_handler.extract_all(pdf_urls, log=log)

        apply_url = _guess_apply_url(service_name, state, pages)
        browser_result = None
        if apply_url and config.PLAYWRIGHT_ENABLED:
            log("Step 3b — Browser automation on apply page...")
            browser_result = browser.automate(apply_url, service_name, log=log)
            if browser_result.get("error"):
                log(f"Browser step error (non-fatal): {browser_result['error']}")
            for pl in browser_result.get("extra_pdf_links", []):
                if pl not in [p["url"] for p in pdfs] and len(pdfs) < config.MAX_PDFS:
                    pdfs.append(pdf_handler.extract_pdf(pl))
        else:
            log("Step 3b — Skipping browser automation (no apply URL or disabled).")

        log("Step 4/4 — Merging with Gemini...")
        raw = {"pages": pages, "pdfs": pdfs, "browser": browser_result}
        record = merger.merge(service_name, state, raw, log=log)

        if existing_record:
            record["_diff"] = _compute_diff(existing_record, record)
            record["_is_reverify"] = True
        else:
            record["_is_reverify"] = False

        log("Pipeline complete!")
        storage.upsert_job(job_id, service_name, state, status="done", result=record)

    except Exception as exc:
        print(f"[{job_id}] PIPELINE ERROR:\n{traceback.format_exc()}")
        storage.upsert_job(job_id, service_name, state, status="error", error=str(exc))


def _guess_apply_url(service_name: str, state: str, pages: list[dict]) -> str | None:
    import re
    apply_kw = re.compile(
        r"(apply\s*online|online\s*application|click\s*here\s*to\s*apply|register\s*now)",
        re.I,
    )
    for page in pages:
        if apply_kw.search(page.get("text", "")):
            return page["url"]
    domains = list(config.WHITELIST.get(state, []))
    return f"https://{domains[0]}" if domains else None


def _compute_diff(old: dict, new: dict) -> dict:
    diff = {}
    fields = [
        "department", "portal_name", "portal_url", "apply_url", "documents",
        "eligibility", "fees", "timeline", "photo_size", "signature_size",
        "upload_limits", "validity", "steps", "notes", "sources", "category",
    ]
    for f in fields:
        if str(old.get(f)) != str(new.get(f)):
            diff[f] = {"old": old.get(f), "new": new.get(f)}
    return diff
