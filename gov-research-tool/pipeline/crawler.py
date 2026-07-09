"""
HTML crawling step — fetches whitelisted pages, extracts text, tables, and
any PDF links found in the page body.
"""
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


def _is_whitelisted(url: str, domains: list[str]) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
        return any(host == d or host.endswith("." + d) for d in domains)
    except Exception:
        return False


def _extract_tables(soup: BeautifulSoup) -> str:
    parts = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if cells:
                rows.append(" | ".join(cells))
        if rows:
            parts.append("\n".join(rows))
    return "\n\n".join(parts)


def _extract_lists(soup: BeautifulSoup) -> str:
    parts = []
    for lst in soup.find_all(["ul", "ol"]):
        items = [li.get_text(" ", strip=True) for li in lst.find_all("li")]
        if items:
            parts.append("\n".join(f"- {i}" for i in items if i))
    return "\n\n".join(parts)


def crawl_page(url: str, domains: list[str]) -> dict:
    result = {
        "url": url,
        "title": "",
        "text": "",
        "tables": "",
        "lists": "",
        "pdf_links": [],
        "error": None,
    }
    try:
        r = requests.get(url, headers=_HEADERS, timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        content_type = r.headers.get("Content-Type", "")
        if "pdf" in content_type.lower():
            result["error"] = "is_pdf"
            return result

        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "nav", "footer",
                          "header", "aside", "iframe"]):
            tag.decompose()

        title = soup.find("title")
        result["title"] = title.get_text(strip=True) if title else ""

        main = (
            soup.find("main")
            or soup.find(id="content")
            or soup.find(class_="content")
            or soup.body
        )
        if main:
            result["text"] = main.get_text(" ", strip=True)[:6000]
        result["tables"] = _extract_tables(soup)[:3000]
        result["lists"] = _extract_lists(soup)[:2000]

        for a in soup.find_all("a", href=True):
            href = urllib.parse.urljoin(url, a["href"])
            if href.lower().endswith(".pdf") and _is_whitelisted(href, domains):
                result["pdf_links"].append(href)

    except Exception as e:
        result["error"] = str(e)

    return result


def crawl_all(page_urls: list[str], state: str, log=None) -> list[dict]:
    domains = list(config.WHITELIST.get(state, []))
    results = []
    for url in page_urls:
        if log:
            log(f"Crawling: {url[:60]}...")
        page = crawl_page(url, domains)
        results.append(page)
    return results
