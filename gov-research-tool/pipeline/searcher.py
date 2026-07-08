"""
Discovery step — finds candidate URLs on whitelisted government domains
related to a given service. Uses DuckDuckGo HTML search with site: operators
so no API key is required.
"""
import re
import time
import urllib.parse

import requests
from bs4 import BeautifulSoup

import config

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120 Mobile Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
}


def _ddg_search(query: str, max_results: int = 5) -> list[str]:
    """Search DuckDuckGo Lite (no JS, no API key needed) and return result URLs."""
    urls: list[str] = []
    try:
        params = {"q": query, "kl": "in-en"}
        r = requests.get(
            "https://duckduckgo.com/lite/",
            params=params,
            headers=_HEADERS,
            timeout=config.REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a.result-link"):
            href = a.get("href", "")
            if href.startswith("http"):
                urls.append(href)
                if len(urls) >= max_results:
                    break
        if not urls:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if href.startswith("http") and "duckduckgo" not in href:
                    urls.append(href)
                    if len(urls) >= max_results:
                        break
    except Exception as e:
        print(f"[searcher] DDG search error: {e}")
    return urls


def _is_whitelisted(url: str, domains: list[str]) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
        return any(host == d or host.endswith("." + d) for d in domains)
    except Exception:
        return False


def _direct_probe(service_name: str, domains: list[str]) -> list[str]:
    """
    Directly probe known URL patterns on each whitelisted domain by fetching
    the domain root and looking for links that mention the service.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", service_name.strip().lower()).strip("-")
    keywords = slug.replace("-", " ").split()
    found: list[str] = []
    for domain in domains:
        base = f"https://{domain}"
        try:
            r = requests.get(base, headers=_HEADERS, timeout=config.REQUEST_TIMEOUT)
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                text = (a.get_text() or "").lower()
                if any(kw in text for kw in keywords):
                    abs_url = urllib.parse.urljoin(base, href)
                    if _is_whitelisted(abs_url, domains):
                        found.append(abs_url)
        except Exception:
            pass
    return found


def discover(service_name: str, state: str, log=None) -> dict:
    """
    Returns:
      {
        "page_urls": [...],
        "pdf_urls":  [...],
      }
    Only URLs on whitelisted domains are included.
    """
    domains = list(config.WHITELIST.get(state, []))
    if not domains:
        return {"page_urls": [], "pdf_urls": []}

    if log:
        log("Searching official government sources...")

    page_urls: list[str] = []
    pdf_urls: list[str] = []
    seen: set[str] = set()

    search_queries = [
        f"{service_name} {state} apply documents eligibility",
        f"{service_name} {state} government portal fees timeline",
        f"{service_name} {state} application form photo signature specifications",
    ]
    if state == "Bihar":
        search_queries.append(f"{service_name} Bihar RTPS serviceonline")

    for q in search_queries:
        for domain in domains:
            query = f"site:{domain} {q}"
            results = _ddg_search(query, max_results=4)
            time.sleep(0.5)
            for url in results:
                if url in seen:
                    continue
                seen.add(url)
                if url.lower().endswith(".pdf"):
                    pdf_urls.append(url)
                elif _is_whitelisted(url, domains):
                    page_urls.append(url)

    probed = _direct_probe(service_name, domains)
    for url in probed:
        if url not in seen:
            seen.add(url)
            if url.lower().endswith(".pdf"):
                pdf_urls.append(url)
            else:
                page_urls.append(url)

    pdf_urls = pdf_urls[: config.MAX_PDFS]
    page_urls = page_urls[: config.MAX_PAGES_PER_DOMAIN * len(domains)]

    if log:
        log(f"Found {len(page_urls)} pages and {len(pdf_urls)} PDFs to analyse.")

    return {"page_urls": page_urls, "pdf_urls": pdf_urls}
