import os

MODEL = "claude-opus-4-6"
EXTRACT_MODEL = "claude-opus-4-6"  # Used for LLM-powered tools
MAX_ITERATIONS = 15
TARGET_ASSETS_WITH_LOCATIONS = 15
MAX_TEXT_PER_PAGE = 4000
REQUEST_TIMEOUT = 10

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
BRAVE_SEARCH_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "")

SEED_URLS = [
    "https://www.royalnavy.mod.uk/news",
    "https://ukdefencejournal.org.uk",
    "https://www.navylookout.com",
    "https://x.com/UKForcesTracker",
    "https://en.wikipedia.org/wiki/List_of_active_Royal_Navy_ships",
    "https://www.cruisingearth.com/ship-tracker/royal-navy/",
    "https://www.marinevesseltraffic.com/nato-navy-warships/United%20Kingdom",
]

SEED_SEARCH_TERMS = [
    "Royal Navy deployments 2026",
    "HMS Queen Elizabeth current location 2026",
    "HMS Prince of Wales current location 2026",
    "Royal Navy warship arrives port 2026",
    "Royal Navy carrier strike group deployment",
    "Royal Navy ship stationed",
    "Type 45 destroyer current deployment",
]
