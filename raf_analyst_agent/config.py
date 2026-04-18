import os

MODEL = "claude-sonnet-4-6"
ASSESS_MODEL = "claude-sonnet-4-6"
MAX_ITERATIONS = 10
MAX_TEXT_PER_PAGE = 4000
REQUEST_TIMEOUT = 10
MAX_OPERATION_TYPES = 10
SERVICE = "royal_air_force"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
BRAVE_SEARCH_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "")
