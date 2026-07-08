# Gov Service Research Tool

Standalone research assistant for Bihar state + Central government services.
Given a service name + scope, it searches official government portals, crawls pages,
extracts PDFs (with OCR fallback), runs browser automation on the apply page,
then uses Gemini to normalize everything into a structured record ready for your
admin panel's Add/Edit Service form.

## How it works

1. You open the tool URL on your phone, enter "Ration Card" + "Bihar"
2. It searches official whitelisted domains, crawls pages, extracts PDFs, runs Playwright on the apply page
3. Gemini normalizes everything into the `service_knowledge` schema
4. You see a review screen with every field pre-filled, status-flagged (found / uncertain / not_found), and source-linked
5. You edit anything that needs fixing, click Approve
6. Record saves to the tool's own SQLite DB and is ready to export as JSON

Realistic timing: **1–3 minutes per service** on Render free tier.
Cold start (after idle): add 30–60s.

---

## Deploy to Render (free tier)

1. Push this folder as its own repo (or a subfolder of your monorepo)
2. Create a new **Web Service** on Render, point it at this repo
3. Render will auto-detect `render.yaml` and use its build/start commands
4. Set `GEMINI_API_KEY` in Render → Environment → Secret Files or Environment Variables
5. Done — open the URL on your phone

> **RAM note**: Playwright's Chromium + pdfplumber + Gemini can peak ~400MB.
> Render free tier has 512MB RAM. If you see OOM crashes, set `PLAYWRIGHT_ENABLED=false`
> as an env var — the browser step will be skipped and the tool still works well
> for most services (HTML + PDF extraction alone covers ~80% of fields).

---

## Run locally (if you have a laptop or Termux)

```bash
pip install -r requirements.txt
python -m playwright install --with-deps chromium
apt-get install tesseract-ocr poppler-utils  # or brew install on Mac

cp .env.example .env
# Edit .env and add your GEMINI_API_KEY

python app.py
# Open http://localhost:5050
```

---

## Adding more whitelisted domains

Edit `config.py` → `WHITELIST` dict, or set the `EXTRA_DOMAINS` env var on Render
as a comma-separated list:
```
EXTRA_DOMAINS=somestate.gov.in,anotherportal.gov.in
```

These domains will be added to the Central list automatically.

---

## Exporting to Onix

After approving a record:
- Single record: `GET /export/<service_key>` → downloads `{service_key}.json`
- All records:   `GET /export-all` → downloads `all_services.json`

The JSON shape matches your `service_knowledge` table exactly (minus `confidence_score`,
which your backend computes automatically from field completeness on save).

---

## Schema notes

- `confidence_score` is **not** output by this tool — your backend (`knowledge.py`) computes it
- `icon` is always empty — you pick that yourself in your admin panel
- `field_status` is a per-field signal (`found` / `uncertain` / `not_found`) for your review
- `manual_review_needed` is `true` if any of the key required fields came back empty

---

## File layout

```
gov-research-tool/
├── app.py                  Flask routes + background job runner
├── config.py               Whitelist domains, env-var settings
├── storage.py              Tool's own SQLite (research_tool.db) — NOT Onix's agent.db
├── pipeline/
│   ├── searcher.py         DuckDuckGo search within whitelisted domains
│   ├── crawler.py          HTML page crawler + table/list extraction
│   ├── pdf_handler.py      pdfplumber (text PDFs) + pytesseract OCR (scanned PDFs)
│   ├── browser.py          Playwright browser automation on apply pages
│   ├── merger.py           Gemini API normalization into schema
│   └── orchestrator.py     Pipeline runner (called in background thread)
├── templates/              Mobile-responsive Flask templates
├── requirements.txt
├── render.yaml             Render deployment config
└── .env.example
```
