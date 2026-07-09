"""
Merge step — sends all extracted raw data to Gemini and normalizes it
into the service_knowledge schema.
"""
import json
import re
from datetime import date

import google.generativeai as genai

import config

_SCHEMA_DESCRIPTION = """
Output a single JSON object with EXACTLY these fields (no extras):
{
  "service_key":         string  (kebab-case slug, e.g. "ration-card"),
  "service_name":        string  (proper name, e.g. "Ration Card"),
  "state":               string  (exact value given: "Bihar" or "Central"),
  "jurisdiction_type":   string  ("state" if Bihar, "central" if Central),
  "category":            string  (one of: Certificates, Identity, Transport, Land Records, Welfare & Employment, Welfare, Travel, Health, Employment & Finance, Business),
  "icon":                string  (always empty string ""),
  "department":          string  (official department name, or ""),
  "portal_name":         string  (name of the official portal, or ""),
  "portal_url":          string  (primary official portal URL, or ""),
  "apply_url":           string  (direct apply URL if different, or ""),
  "documents":           array of strings (each required document as its own item),
  "eligibility":         string  (full eligibility text, or ""),
  "fees":                string  (exact fee and payment method, "No fee" if free, or ""),
  "timeline":            string  (processing time e.g. "15 working days", or ""),
  "photo_size":          string  (exact photo dimensions/specs e.g. "35mm x 45mm, white background, max 50KB, JPEG", or ""),
  "signature_size":      string  (exact signature specs if found, or ""),
  "upload_limits":       string  (file size/format upload limits, or ""),
  "validity":            string  (document validity e.g. "10 years", "Lifetime", or ""),
  "steps":               array of strings (ordered application steps),
  "notes":               string  (important caveats/conditions not captured above, or ""),
  "sources":             array of strings (all URLs from the input that were crawled),
  "manual_review_needed": boolean (true if ANY of these is empty: department, portal_url, eligibility, fees, timeline, documents, steps),
  "field_status":        object mapping each field name above to "found" / "not_found" / "uncertain",
  "last_verified":       string  (today's ISO date: {today})
}
Rules:
- Never invent information. If a field is not found, leave it "" or [] and mark "not_found".
- Do not add a confidence_score field.
- For photo_size and signature_size: be specific — dimensions, file format, file size limits.
- For sources: include ALL URLs provided in the input.
- field_status: "found" = confident, "uncertain" = partial/ambiguous, "not_found" = empty.
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
            sections.append("### Form fields visible\n" +
                            "\n".join(browser["form_fields"]) + "\n")
        if browser.get("photo_signature_text"):
            sections.append(f"### Photo/Signature lines\n{browser['photo_signature_text']}\n")
        if browser.get("steps_text"):
            sections.append(f"### Numbered steps\n{browser['steps_text']}\n")

    sections.append(
        "\nNow output ONLY the JSON object described above. "
        "No explanation, no markdown fences, no extra text — just raw JSON."
    )
    return "\n".join(sections)


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return json.loads(text.strip())


def merge(service_name: str, state: str, raw: dict, log=None) -> dict:
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it as an environment variable.")

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

    record = _extract_json(response.text)

    all_fields = [
        "service_key", "service_name", "state", "jurisdiction_type", "category",
        "department", "portal_name", "portal_url", "apply_url", "documents",
        "eligibility", "fees", "timeline", "photo_size", "signature_size",
        "upload_limits", "validity", "steps", "notes", "sources",
    ]
    if "field_status" not in record:
        record["field_status"] = {}
    for f in all_fields:
        if f not in record["field_status"]:
            val = record.get(f)
            if isinstance(val, list):
                record["field_status"][f] = "found" if val else "not_found"
            else:
                record["field_status"][f] = "found" if str(val or "").strip() else "not_found"

    record.pop("confidence_score", None)

    if log:
        log("Merge complete.")

    return record
