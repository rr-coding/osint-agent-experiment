import os

MODEL = "claude-sonnet-4-6"
EXTRACT_MODEL = "claude-sonnet-4-6"
MAX_ITERATIONS = 10
TARGET_ASSETS_WITH_LOCATIONS = 5
MAX_TEXT_PER_PAGE = 4000
REQUEST_TIMEOUT = 10
SERVICE = "royal_air_force"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
BRAVE_SEARCH_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "")

SEED_URLS = [
    "https://www.raf.mod.uk",
    "https://www.gov.uk/government/news?organisations%5B%5D=ministry-of-defence",
    "https://www.forces.net/raf",
    "https://ukdefencejournal.org.uk",
    "https://www.key.aero",
]

SEED_SEARCH_TERMS = [
    '"Royal Air Force" deployment',
    '"Exercise Cobra Warrior"',
    '"Exercise Red Flag"',
    '"Exercise Cope North"',
    '"Typhoon" QRA scramble',
    '"Op Shader"',
    '"Op Biloxi"',
    '"RAF" squadron deployed',
]
