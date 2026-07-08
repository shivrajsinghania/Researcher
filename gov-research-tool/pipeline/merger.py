"""
Merge step — sends all extracted raw data to Gemini and gets back a
structured record matching the service_knowledge schema exactly.
"""
import json
import re
from datetime import date

import google.generativeai as genai

import config

_SCHEMA_DESCRIPTION = """
Output a single JSON object with EXACTLY these fields (no extras, no nesting beyond what is specified):
{
  "service_key":         string  (kebab-case slug of the service name, e.g. "ration-card"),
  "service_name":        string  (proper name, e.g. "Ration Card"),
  "state":               string  (exact value given: "Bihar" or "Central"),
  "jurisdiction_type":   string  ("state" if Bihar, "central" if Central),
  "category":            string  (one of: Certificates, Identity, Transport, Land Records, Welfare & Employment, Welfare, Travel, Health, Employment & Finance, Business — pick the best fit),
  "icon":                string  (leave as empty string ""),
  "department":          string  (official department name, or "" if not found),
  "portal_name":         string  (name of the official portal, or ""),
  "portal_url":          string  (primary official portal URL, or ""),
  "apply_url":           string  (direct "Apply Online" URL if different from portal_url, or ""),
  "documents":           array of strings (each document on its own line, include any requirement notes in parentheses),
  "eligibility":         string  (who can apply, residency/age/income conditions — full text, or ""),
  "fees":                string  (exact fee amount and payment method, or "No fee" if free, or "" if not found),
  "timeline":            string  (processing time e.g. "15 working days", or ""),
  "photo_size":          string  (exact photo dimensions/specs found e.g. "35mm x 45mm, white background, max 50KB, JPEG", or ""),
  "signature_size":      string  (exact signature specs if found, or ""),
  "upload_limits":       string  (file size/format limits for uploads, or ""),
  "validity":            string  (how long the document is valid e.g. "10 years", "Lifetime", or ""),
  "steps":               array of strings (ordered application steps, each step as a plain string),
  "notes":               string  (anything important that doesn't fit above — conditions, caveats, tips — or ""),
  "sources":             array of strings (URLs actually used to find information — include all URLs from input),
  "manual_review_needed": boolean (true if ANY of these is empty/uncertain: department, portal_url, eligibility, fees, timeline, documents array, steps array),
  "field_status":        object mapping each field name above to one of "found" / "not_found" / "uncertain",
  "last_verified":       string  (today's ISO date: {today})
}

Rules:
- Never invent information. If a field cannot be found in the provided content, leave it as "" or [] and mark it "not_found" in field_status.
- Do not add a confidence_score field — it is computed separately.
- For documents: extract every required document mentioned anywhere in the content.
- For steps: extract ordered application steps. If the page shows a numbered process, preserve that order.
- For photo_size and signature_size: be very specific — dimensions, file format, file size limits if stated.
- For fees: include the exact amount. If the fee varies, list all variants.
- For eligibility: include age, income, residency, caste, or any other eligibility criteria mentioned.
- For sources: include ALL URLs from the input (page URLs, PDF URLs) that were actually crawled.
- field_status values: "found" = content present and confident, "uncertain" = partial/ambiguous, "not_found" = empty.
"""


def _build_prompt(service_name: str, state: str, raw: dict) -> str:
    today = date.today().isoformat()
    schema = _SCHEMA_DESCRIPTION.replace("{today}", today)

    sections = [
        f"# Research Task\nService: {service_name}\nScope: {state}\n",
        schema,
        "\n# Raw Extracted Content\n",
    ]

    for page in raw.get("pages", []):
        if page.get("error") and page["error"] != "is_pdf":
            continue
        sections.append(f"## Page: {page['url']}\nTitle: {page.get('title','')}\n")
        if page.get("text"):
            sections.append(f"### Body text\n{page['text'][:3000]}\n")
        if page.get("tables"):
            sections.append(f"### Tables\n{page['tables'][:1500]}\n")
        if page.get("lists"):
            sections.append(f"### Lists\n{page['lists'][:1000]}\n")

    for pdf in raw.get("pdfs", []):
        if not pdf.get("text"):
            continue
        sections.append(f"## PDF ({pdf['method']}): {pdf['url']}\n{pdf['text'][:3000]}\n")

    browser = raw.get("browser")
    if browser and not browser.get("error"):
        sections.append(f"## Browser automation: {browser['url']}\n")
        if browser.get("text"):
            sections.append(f"### Page text\n{browser['text'][:2000]}\n")
        if browser.get("form_fields"):
            sections.append(f"### Form fields visible\n" +
                            "\n".join(browser["form_fields"]) + "\n")
        if browser.get("photo_signature_text"):
            sections.append(f"### Photo/Signature lines\n{browser['photo_signature_text']}\n")
        if browser.get("steps_text"):
            sections.append(f"### Numbered steps\n{browser['steps_text']}\n")

    sections.append(
        "\nNow output ONLY the JSON object described in the schema above. "
        "No explanation, no markdown code fences, no extra text — just the raw JSON."
    )
    return "\n".join(sections)


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    text = text.strip()
    return json.loads(text)


def merge(service_name: str, state: str, raw: dict, log=None) -> dict:
    """
    Calls Gemini to normalize raw extracted data into the service_knowledge schema.
    Returns the structured dict on success, raises on failure.
    """
    if not config.GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it as an environment variable."
        )

    genai.configure(api_key=config.GEMINI_API_KEY)
    model = genai.GenerativeModel(config.GEMINI_MODEL)

    if log:
        log("Sending to Gemini for normalization...")

    prompt = _build_prompt(service_name, state, raw)

    response = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(
            temperature=0.1,
            max_output_tokens=4096,
        ),
    )

    result_text = response.text
    record = _extract_json(result_text)

    if "field_status" not in record:
        record["field_status"] = {}

    all_fields = [
        "service_key", "service_name", "state", "jurisdiction_type", "category",
        "department", "portal_name", "portal_url", "apply_url", "documents",
        "eligibility", "fees", "timeline", "photo_size", "signature_size",
        "upload_limits", "validity", "steps", "notes", "sources",
    ]
    for f in all_fields:
        if f not in record["field_status"]:
            val = record.get(f)
            if isinstance(val, list):
                status = "found" if val else "not_found"
            else:
                status = "found" if str(val or "").strip() else "not_found"
            record["field_status"][f] = status

    record.pop("confidence_score", None)

    if log:
        log("Merge complete.")

    return record
