import os

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-1.5-flash"

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")

DB_PATH = os.environ.get("DB_PATH", "research_tool.db")

WHITELIST = {
    "Bihar": [
        "serviceonline.bihar.gov.in",
        "state.bihar.gov.in",
        "bihar.gov.in",
        "rtps.bihar.gov.in",
    ],
    "Central": [
        "uidai.gov.in",
        "incometax.gov.in",
        "eci.gov.in",
        "nvsp.in",
        "passportindia.gov.in",
        "parivahan.gov.in",
        "epfindia.gov.in",
        "eshram.gov.in",
        "india.gov.in",
        "digitallocker.gov.in",
        "services.india.gov.in",
    ],
}

EXTRA_DOMAINS = os.environ.get("EXTRA_DOMAINS", "").strip()
if EXTRA_DOMAINS:
    for d in EXTRA_DOMAINS.split(","):
        d = d.strip()
        if d:
            WHITELIST.setdefault("Central", []).append(d)

REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "20"))
MAX_PAGES_PER_DOMAIN = int(os.environ.get("MAX_PAGES_PER_DOMAIN", "3"))
MAX_PDFS = int(os.environ.get("MAX_PDFS", "3"))

PLAYWRIGHT_ENABLED = os.environ.get("PLAYWRIGHT_ENABLED", "true").lower() == "true"

CATEGORIES = [
    "Certificates",
    "Identity",
    "Transport",
    "Land Records",
    "Welfare & Employment",
    "Welfare",
    "Travel",
    "Health",
    "Employment & Finance",
    "Business",
]
