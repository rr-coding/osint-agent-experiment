# Royal Navy OSINT Tracking Agent — Claude Code Prompt

## Project Goal

Build a genuine AI agent (not a linear script) that performs open-source intelligence (OSINT) gathering to track Royal Navy ships, bases, and units. The agent uses the Anthropic API with tool use to dynamically decide what to search for, what pages to fetch, and how to interpret what it finds. It compiles results into a structured JSON dataset with geocoded locations and confidence scores.

## Architecture

Build this as a single Python project with the following file structure:

```
rn_osint_agent/
├── agent.py          # Main agent loop and orchestration
├── tools.py          # Tool definitions and implementations (web search, page fetch, entity extraction)
├── models.py         # Pydantic data models and JSON schema for the output dataset
├── geocoding.py      # Location resolution logic (fixed lookup table for known bases + LLM fallback)
├── config.py         # Configuration constants (model name, max iterations, API keys, seed data)
├── output/           # Directory for JSON output files
└── requirements.txt
```

## Core Agent Loop (agent.py)

Build the agent using the Anthropic Python SDK (`anthropic` package) with tool use (function calling). The agent follows this loop:

1. **Initialise state**: Create a state object that tracks discovered assets (name, type, location status), a list of URLs already fetched, search queries already run, and remaining gaps (assets found but missing location data, locations found but not geocoded, etc.).
2. **Construct the prompt**: On each iteration, send the LLM the current state — what has been found, what gaps remain — along with the available tools. The system prompt should instruct the agent to prioritise filling gaps (e.g., "you found HMS Diamond but have no location — search for its recent movements").
3. **LLM decides next action**: The LLM returns one or more tool calls. It chooses from the tools defined below.
4. **Execute tools**: The code executes the requested tool(s) and returns results to the LLM.
5. **LLM processes results**: The LLM interprets the tool output, updates its understanding, and either makes another tool call or returns a text summary of what it learned.
6. **Update state**: Parse the LLM's response to update the state object with any new assets, locations, or refined information. Two additional behaviours happen automatically in Python (not driven by the LLM):
   - **Auto-geocode on extract**: Immediately after each asset is upserted from an `extract_and_update` result, if the asset has a `location_description` but no coordinates, `resolve_location` is called in Python right away — without waiting for the LLM to decide to do it.
   - **End-of-round geocode sweep**: After all tool results in a round are processed, any remaining asset with a `location_description` but still no coordinates gets a geocoding attempt. This catches assets whose location description was updated via upsert.
   - **Confidence upgrade**: `upsert_asset` upgrades an existing asset's coordinates when a new observation has a higher confidence score than what is already stored.
7. **Check termination**: Stop if any of these conditions are met:
   - The agent has identified **at least `TARGET_ASSETS_WITH_LOCATIONS` Royal Navy assets with resolved locations** (not just names — they need coordinates too).
   - The maximum iteration count (`MAX_ITERATIONS`) has been reached.
   - The agent explicitly declares the task complete (returns a `task_complete` tool call).
8. **Repeat from step 2** if not terminated.

**Critical: This must be a genuine agent loop.** The LLM must choose its next action based on what it has learned so far. If you run the agent twice with different seed data, it should take different paths. Do not write a linear script that always does the same steps in the same order.

## Tool Definitions (tools.py)

Define these as Anthropic API tool-use schemas so the LLM can call them:

### web_search
- **Input**: `query` (string) — a search query
- **Implementation**: Use the Brave Search API exclusively.
  - Read the key from `BRAVE_SEARCH_API_KEY` environment variable via `os.environ.get('BRAVE_SEARCH_API_KEY')`.
  - Endpoint: `https://api.search.brave.com/res/v1/web/search` — pass `q` as a query parameter and the key in the `X-Subscription-Token` header.
  - If the key is not set, print a clear error message and exit rather than falling back to scraping.
  - There is no DuckDuckGo or other fallback.
- **Output**: Return a list of results, each with title, URL, and snippet text.
- **Error handling**: If the API call fails (network error, non-200 response), return an empty list with an error message. Do not crash.

### fetch_page
- **Input**: `url` (string) — a web page URL
- **Implementation**: Use `requests` to fetch the page, then use `BeautifulSoup` (or `trafilatura` if available) to extract the main readable text content, stripping navigation, ads, and boilerplate. Limit the extracted text to 4000 characters to stay within context limits.
- **Output**: Return the extracted text, the page title, and the URL.
- **Error handling**: Handle timeouts (10 second limit), HTTP errors, SSL errors, paywalls, and connection failures gracefully. Return an error message, not an exception.

### extract_and_update
- **Input**: `text` (string) — raw text content from a fetched page, `source_url` (string)
- **Implementation**: This is an **LLM-powered tool**. Send the text to Claude (using a separate API call with `claude-opus-4-6`) with a prompt asking it to identify any Royal Navy assets mentioned, along with their type, class, and any location information. The prompt should specify the exact JSON structure expected.
- **Output**: A list of extracted asset objects matching the schema in models.py.

### resolve_location
- **Input**: `asset_name` (string), `location_description` (string) — e.g., "deployed to the Indo-Pacific"
- **Implementation**: Two-stage resolution in `geocoding.py`:
  1. **Fixed lookup first**: Check the location_description against `KNOWN_FIXED_LOCATIONS` — a dict of ~20 named RN bases and stations (HMNB Portsmouth, Devonport, Clyde/Faslane, RNAS Culdrose, Yeovilton, Gibraltar, Bahrain, Cyprus, Falklands, etc.) with pre-set coordinates and confidence ≥ 0.90. If a match is found, return immediately without an API call.
  2. **LLM fallback**: If no fixed match, call Claude with a prompt that **mandates coordinates always be returned** — "A low-confidence estimate is better than no location." If the LLM returns null coordinates, re-check the fixed lookup as a last resort.
- **Key principle**: A location with low confidence is always better than no location.
- **Output**: latitude, longitude, confidence_score, resolution_rationale.

### task_complete
- **Input**: `summary` (string) — a brief summary of what was found
- **Implementation**: Signals the agent loop to terminate.
- **Output**: None (triggers termination).

## Data Model (models.py)

Use Pydantic models. The output dataset is a list of objects with this schema:

```json
{
  "name": "HMS Queen Elizabeth",
  "type": "ship",
  "class": "Queen Elizabeth-class",
  "location_description": "HMNB Portsmouth",
  "latitude": 50.7989,
  "longitude": -1.1086,
  "confidence_score": 0.95,
  "confidence_rationale": "Well-known home port, confirmed by official source",
  "source_urls": ["https://www.royalnavy.mod.uk/..."],
  "date_observed": "2026-03-10",
  "last_updated": "2026-03-15T14:30:00Z"
}
```

Valid values for `type`: ship, submarine, base, air_station, unit, auxiliary.

## Agent System Prompt

The system prompt for the main agent LLM should include:

- Its role: "You are an OSINT analyst specialising in Royal Navy order of battle and fleet disposition."
- Its goal: Identify Royal Navy assets and their current or most recently reported locations from publicly available sources.
- Its strategy: Start with seed sources and searches, identify assets, then run targeted searches to fill in missing locations. **Location is the primary gap to fill.** A location with LOW confidence is better than NO location — always attempt to geocode every asset that has a `location_description`.
- LOCATION PRIORITY RULES the agent must follow:
  - Ships at named bases (Portsmouth, Devonport, Faslane): use the fixed coordinates for that base.
  - Ships in refit or under maintenance: geocode to the most likely refit yard (Cammell Laird, Babcock Devonport, etc.).
  - Ships at sea with a named area (e.g., "Eastern Mediterranean", "GIUK Gap"): place at the centre of that area with moderate confidence.
  - Ships with vague descriptions ("home waters", "patrol duties"): place at most likely home port with low confidence.
  - Only leave coordinates null if there is truly no location information at all.
- Its constraints: Only use publicly available information. Note when information is dated or uncertain. Never fabricate data.
- A reminder to use the tools dynamically: "Decide your next action based on what gaps remain in your knowledge. Do not follow a fixed sequence."

## Configuration (config.py)

```python
MODEL = "claude-opus-4-6"
MAX_ITERATIONS = 20
TARGET_ASSETS_WITH_LOCATIONS = 15
MAX_TEXT_PER_PAGE = 4000
REQUEST_TIMEOUT = 10

SEED_URLS = [
    "https://www.royalnavy.mod.uk/news",
    "https://ukdefencejournal.org.uk",
    "https://www.navylookout.com",
    "https://x.com/UKForcesTracker",
]

SEED_SEARCH_TERMS = [
    "Royal Navy deployments 2026",
    "HMS Queen Elizabeth current location 2026",
    "Royal Navy warship arrives port 2026",
    "Royal Navy carrier strike group deployment",
    "Type 45 destroyer current deployment",
]
```
Both API keys are read from environment variables and are required:
- `ANTHROPIC_API_KEY` — read via `os.environ.get('ANTHROPIC_API_KEY')`. If not set, print a clear error and exit.
- `BRAVE_SEARCH_API_KEY` — read via `os.environ.get('BRAVE_SEARCH_API_KEY')`. If not set, print a clear error and exit. There is no search fallback.

## Logging and Observability

This is essential for both debugging and demo purposes. Implement structured logging that shows:

- **Each iteration**: Print the iteration number, current state summary (how many assets found, how many have locations, how many gaps remain).
- **LLM decisions**: Print what tool the LLM chose to call and why (extract the reasoning from the LLM's response text).
- **Tool results**: Print a brief summary of what each tool returned (not the full text — just "fetched 3200 chars from navylookout.com" or "search returned 8 results for 'HMS Diamond deployment'").
- **State changes**: Print when a new asset is added or an existing asset gets a location update.
- **Token tracking**: Track and display cumulative input and output tokens used across all API calls.

Use coloured terminal output (e.g., with the `rich` library) to make the demo visually engaging. Use different colours for decisions, tool calls, discoveries, and warnings.

## Error Handling

- Wrap every tool execution in try/except. Log the error and return a structured error message to the LLM so it can decide what to do next.
- If a page is behind a paywall or returns a 403, the agent should note this and move on — not retry endlessly.
- If the search API returns no results for a query, the agent should try a reformulated query, not the same one again.
- If the Anthropic API call fails (rate limit, server error), implement exponential backoff with a maximum of 3 retries.

## Output

At the end of the run:

1. Print the complete JSON dataset to the terminal, formatted with indentation.
2. Save the dataset to `output/rn_assets_TIMESTAMP.json`.
3. Print a summary table showing: asset name, type, location, confidence score.
4. Print total token usage and number of iterations used.

## Dependencies (requirements.txt)

```
anthropic
requests
beautifulsoup4
pydantic
rich
trafilatura
```

## What NOT To Build

- Do not build a web UI at this stage — this is the data-gathering agent only.
- Do not use LangChain, CrewAI, or any agent framework. Use the Anthropic SDK directly with tool use. This keeps the code transparent and understandable for demo purposes.
- Do not hardcode a sequence of steps. The whole point is that the LLM decides what to do next.
- Do not use async/await — keep it synchronous for simplicity and readability.
