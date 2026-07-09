"""
PDF extraction — text-based PDFs use pdfplumber; scanned/image PDFs fall
back to Tesseract OCR via pdf2image + pytesseract.
"""
import io

import requests

import config

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/120 Safari/537.36"
    )
}


def _fetch_pdf(url: str) -> bytes | None:
    try:
        r = requests.get(url, headers=_HEADERS, timeout=config.REQUEST_TIMEOUT,
                         stream=True)
        r.raise_for_status()
        data = b""
        for chunk in r.iter_content(8192):
            data += chunk
            if len(data) > 15 * 1024 * 1024:
                break
        return data
    except Exception as e:
        print(f"[pdf_handler] fetch error {url}: {e}")
        return None


def _extract_text_pdfplumber(data: bytes) -> str:
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages[:10]:
                t = page.extract_text()
                if t:
                    text_parts.append(t)
                tables = page.extract_tables()
                for table in tables:
                    for row in (table or []):
                        row_text = " | ".join(str(c or "").strip() for c in row)
                        if row_text.strip():
                            text_parts.append(row_text)
        return "\n".join(text_parts)[:8000]
    except Exception as e:
        print(f"[pdf_handler] pdfplumber error: {e}")
        return ""


def _ocr_pdf(data: bytes) -> str:
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
        images = convert_from_bytes(data, dpi=200, first_page=1, last_page=5)
        parts = []
        for img in images:
            text = pytesseract.image_to_string(img, lang="eng+hin")
            if text.strip():
                parts.append(text)
        return "\n".join(parts)[:8000]
    except Exception as e:
        print(f"[pdf_handler] OCR error: {e}")
        return ""


def extract_pdf(url: str) -> dict:
    result = {"url": url, "text": "", "method": "failed", "error": None}
    data = _fetch_pdf(url)
    if not data:
        result["error"] = "fetch_failed"
        return result

    text = _extract_text_pdfplumber(data)
    if text and len(text.strip()) > 100:
        result["text"] = text
        result["method"] = "pdfplumber"
        return result

    print(f"[pdf_handler] sparse text, trying OCR for {url}")
    text = _ocr_pdf(data)
    if text:
        result["text"] = text
        result["method"] = "ocr"
    else:
        result["error"] = "no_text_extracted"

    return result


def extract_all(pdf_urls: list[str], log=None) -> list[dict]:
    results = []
    for url in pdf_urls:
        if log:
            log(f"Extracting PDF: {url[:60]}...")
        results.append(extract_pdf(url))
    return results
