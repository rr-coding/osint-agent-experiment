import os

MODEL = "claude-sonnet-4-6"
EXTRACT_MODEL = "claude-sonnet-4-6"
MAX_ITERATIONS = 10
TARGET_ASSETS_WITH_LOCATIONS = 5
MAX_TEXT_PER_PAGE = 4000
REQUEST_TIMEOUT = 10
SERVICE = "british_army"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
BRAVE_SEARCH_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "")

SEED_URLS = [
    "https://www.army.mod.uk",
    "https://www.gov.uk/government/news?organisations%5B%5D=ministry-of-defence",
    "https://www.forces.net/army",
    "https://ukdefencejournal.org.uk",
    "https://www.janes.com",
]

SEED_SEARCH_TERMS = [
    '"British Army" exercise',
    '"British Army" deployment',
    '"British Army" homecoming',
    '"Op Cabrit"',
    '"Op Interflex"',
    '"Op Newcombe"',
    '"Light Dragoons"',
    '"Royal Welsh"',
    '"Royal Anglian"',
]
