# Gov Service Research Tool

Standalone research assistant for Bihar state + Central government services.
Given a service name + scope, searches official government portals, crawls pages,
extracts PDFs (with OCR fallback), runs browser automation on the apply page,
then uses Gemini to normalize everything into a `service_knowledge`-compatible record.

## Deploy to Render

1. Push this folder as its own Git repo
2. Create a new **Web Service** on Render → connect that repo
3. Set **Root Directory** to `gov-research-tool` if deploying from a monorepo
4. Render auto-detects `render.yaml` — build command installs Tesseract + Playwright
5. Add environment variable: `GEMINI_API_KEY` = your key
6. Open the URL on your phone

> **RAM note**: If you see OOM crashes, set `PLAYWRIGHT_ENABLED=false` in Render env vars.
> HTML + PDF extraction alone covers ~80% of fields without Playwright.

## Run locally

```bash
pip install -r requirements.txt
python -m playwright install --with-deps chromium
apt-get install tesseract-ocr poppler-utils   # Linux / WSL
# brew install tesseract poppler              # Mac

cp .env.example .env   # add your GEMINI_API_KEY
python app.py          # open http://localhost:5050
```

## Adding more whitelisted domains

Edit `config.py` → `WHITELIST`, or set on Render:
```
EXTRA_DOMAINS=somestate.gov.in,anotherportal.gov.in
```

## Exporting to Onix

- Single record: `GET /export/<service_key>` → `{service_key}.json`
- All records:   `GET /export-all`            → `all_services.json`

JSON shape matches your `service_knowledge` table exactly.
`confidence_score` is intentionally omitted — your `knowledge.py` computes it on save.

## File layout

```
gov-research-tool/
├── app.py                Flask routes + background job runner
├── config.py             Whitelist domains, env-var settings
├── storage.py            Tool's own SQLite (research_tool.db) — NOT Onix's agent.db
├── runtime.txt           Pins Python 3.12.7 for Render
├── pipeline/
│   ├── searcher.py       DuckDuckGo search within whitelisted domains
│   ├── crawler.py        HTML crawler + table/list extraction
│   ├── pdf_handler.py    pdfplumber (text PDFs) + pytesseract OCR (scanned)
│   ├── browser.py        Playwright on apply pages
│   ├── merger.py         Gemini normalization
│   └── orchestrator.py   Pipeline runner (background thread)
├── templates/            Mobile-responsive Flask templates
├── requirements.txt
├── render.yaml           Render config (includes PYTHON_VERSION: 3.12.7)
└── .env.example
```
