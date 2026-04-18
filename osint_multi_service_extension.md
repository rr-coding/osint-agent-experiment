# OSINT Command Centre — Multi-Service Extension

## Overview

This prompt extends the existing OSINT Command Centre project (currently supporting Royal Navy) to also cover the British Army and the Royal Air Force. The existing Royal Navy agents and their output must not be modified. New Army and RAF agents are added alongside the Navy agent, following the same pattern. The frontend is extended to display units from all three services with service-based filtering and colour-coding.

This is an extension to an existing, working codebase. Do not rebuild what already exists. Read the existing code first, then make additive changes and targeted modifications only.

## What Already Exists (Do Not Rebuild)

The current project has this structure:

```
project_root/
├── rn_osint_agent/          # Royal Navy OSINT gathering agent
│   ├── agent.py
│   ├── tools.py
│   ├── models.py
│   ├── config.py
│   └── output/              # JSON output files
├── rn_analyst_agent/        # Royal Navy analyst agent
│   ├── analyst_agent.py
│   ├── tools.py
│   ├── models.py
│   ├── config.py
│   └── output/              # Enriched JSON output files
├── osint_frontend/
│   ├── server.py            # Flask backend
│   ├── index.html           # Web command centre
│   └── requirements.txt
└── docs/
    └── index.html           # GitHub Pages demo version
```

Before making any changes, read the existing files so you understand the current patterns. In particular, read `rn_osint_agent/agent.py`, `rn_osint_agent/tools.py`, `rn_osint_agent/config.py`, `rn_analyst_agent/analyst_agent.py`, `osint_frontend/server.py`, and `osint_frontend/index.html`. The new agents must mirror the existing agents' patterns closely.

## What Needs to Be Added

### 1. British Army OSINT Agent (`ba_osint_agent/`)

Create a new directory `ba_osint_agent/` containing an OSINT gathering agent for the British Army. The file structure and code pattern must match `rn_osint_agent/` exactly — same agent loop, same tool definitions, same Anthropic SDK usage with tool-use, same logging style using `rich`, same maximum iteration and termination logic.

**Differences from the Navy agent:**

- **Target**: The agent is tasked with identifying British Army units and their locations. Unit types include regiments, battalions, brigades, divisions, barracks, training establishments, and formations.
- **Seed URLs**:
  ```python
  SEED_URLS = [
      "https://www.army.mod.uk",
      "https://www.gov.uk/government/news?organisations%5B%5D=ministry-of-defence",
      "https://www.forces.net/army",
      "https://ukdefencejournal.org.uk",
      "https://www.janes.com",
  ]
  ```
- **Seed search terms**: The agent should run multiple narrow, focused queries rather than broad ones. Use these as a starting set, and allow the agent to generate further targeted queries:
  ```python
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
  ```
  Note that the regiment names are split into separate queries rather than combined with OR operators — this produces cleaner results. The agent should be instructed in its system prompt that when searching for units, it should rotate through regiment/battalion names one at a time rather than trying to list them all in one query.

- **Service identifier**: All output records must include `"service": "british_army"`.

- **Valid unit types** for the Army agent:
  - `regiment`
  - `battalion`
  - `brigade`
  - `division`
  - `barracks`
  - `training_establishment`
  - `headquarters`
  - `formation`
  - `other`

- **Configuration**:
  ```python
  MODEL = "claude-sonnet-4-20250514"
  MAX_ITERATIONS = 10
  TARGET_ASSETS_WITH_LOCATIONS = 5
  SERVICE = "british_army"
  OUTPUT_DIR = "output"
  ```

### 2. Royal Air Force OSINT Agent (`raf_osint_agent/`)

Create a parallel `raf_osint_agent/` directory, mirroring the same pattern.

- **Target**: RAF squadrons, stations, wings, groups, and associated units.
- **Seed URLs**:
  ```python
  SEED_URLS = [
      "https://www.raf.mod.uk",
      "https://www.gov.uk/government/news?organisations%5B%5D=ministry-of-defence",
      "https://www.forces.net/raf",
      "https://ukdefencejournal.org.uk",
      "https://www.key.aero",
  ]
  ```
- **Seed search terms**:
  ```python
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
  ```
- **Service identifier**: All output records must include `"service": "royal_air_force"`.
- **Valid unit types** for the RAF agent:
  - `squadron`
  - `station`
  - `wing`
  - `group`
  - `flight`
  - `training_unit`
  - `headquarters`
  - `other`

### 3. Updated Search Guidance for All Three OSINT Agents

The existing Navy agent's search behaviour is already working, but the new agents should implement improved search practices, and the Navy agent should also be updated to match. Apply the following guidance to all three OSINT agents' system prompts and tool implementations:

**Date-bound queries.** The Brave Search API supports a `freshness` parameter. Add this to the `web_search` tool implementation in all three agents. Use `freshness="pm"` (past month) by default. The agent should be allowed to override this parameter for searches where it specifically wants historical results (e.g., researching a unit's formation history), but the default must be recent content only. Add a new optional parameter to the `web_search` tool definition so the LLM can specify freshness per query — valid values: `"pd"` (past day), `"pw"` (past week), `"pm"` (past month), `"py"` (past year), `None` (no filter).

**Site filters over model judgment.** Add an optional `site` parameter to the `web_search` tool. When provided, the implementation should append `site:<domain>` to the query string before sending to Brave. Instruct each agent in its system prompt that for authoritative sources, it should run the same query scoped to each seed domain individually rather than one broad unscoped query. Example: instead of `"British Army exercise"`, the agent should run `"British Army exercise" site:army.mod.uk`, then `"British Army exercise" site:forces.net`, then `"British Army exercise" site:gov.uk`, and deduplicate the results.

**Keep queries narrow.** Update the system prompt for each agent with explicit guidance: *"Do not write long compound queries. A query like 'British Army exercise deployment training operations Estonia Poland' will perform worse than three separate queries. Fan out across many narrow queries and deduplicate the results rather than trying to write one clever query. Each query should target one piece of information you want to find."*

**Follow links for full content.** The existing `fetch_page` tool already handles this, but reinforce in the system prompt: *"Search API results give you titles, snippets, and URLs — not full article text. When a search result looks relevant, use `fetch_page` to pull the actual content before reasoning over it. Do not rely on snippets alone for extraction."*

Apply these changes to `rn_osint_agent/tools.py`, `rn_osint_agent/agent.py`, `ba_osint_agent/tools.py`, `ba_osint_agent/agent.py`, `raf_osint_agent/tools.py`, and `raf_osint_agent/agent.py`.

### 4. British Army Analyst Agent (`ba_analyst_agent/`)

Create a new directory mirroring `rn_analyst_agent/`. The agent enriches Army OSINT data with the same analytical dimensions: operational readiness, current assignment, unit category, and capability scores against operation types.

Key differences:

- **Input**: Reads from `ba_osint_agent/output/` instead of Navy output.
- **Output**: Writes to `ba_analyst_agent/output/`.
- **Operation type generation**: The operation type list is still generated dynamically by the LLM based on the actual units present, but the agent should be guided in its system prompt to consider Army-relevant operation categories such as: armoured warfare, infantry operations, artillery support, combat engineering, reconnaissance, peacekeeping and stabilisation, training and mentoring of partner forces, counter-terrorism, humanitarian assistance, and logistics/sustainment. The final list is up to the agent based on the input data — up to 10 types.
- **Unit category mapping**: The analyst agent may need to refine raw unit types into analytical categories (e.g., light infantry vs armoured infantry vs mechanised infantry). Allow the agent latitude to determine these categorisations.
- **Service identifier preserved**: The enriched output must include `"service": "british_army"` for every record.

### 5. Royal Air Force Analyst Agent (`raf_analyst_agent/`)

Parallel structure to the Army analyst.

- **Input**: `raf_osint_agent/output/`
- **Output**: `raf_analyst_agent/output/`
- **Operation type guidance**: For the RAF, relevant operation categories include air policing and QRA, air superiority, close air support, strategic lift, air-to-air refuelling, ISR, combat search and rescue, strategic bombing, humanitarian airlift, and training. Again, the agent generates the actual list from the input data.
- **Service identifier**: `"service": "royal_air_force"`.

### 6. Unified Data Schema

All three analyst agents must output records conforming to a single unified schema with optional service-specific fields. Every record must include:

**Core fields (all services):**
```json
{
  "service": "royal_navy | british_army | royal_air_force | joint",
  "name": "string",
  "unit_category": "string (service-specific valid values)",
  "class_or_type": "string (e.g. 'Queen Elizabeth-class' or 'Light Cavalry' or 'Typhoon FGR4')",
  "location_description": "string",
  "latitude": "number",
  "longitude": "number",
  "confidence_score": "number 0-1",
  "confidence_rationale": "string",
  "source_urls": ["list of strings"],
  "date_observed": "ISO date",
  "last_updated": "ISO datetime",
  "operational_readiness": "high | medium | low",
  "readiness_rationale": "string",
  "current_assignment": "string",
  "assignment_source": "string (URL or null)",
  "capability_scores": { "operation_type_id": "number 0-5", ... },
  "capability_rationale": "string"
}
```

**Optional service-specific fields:**
- Navy records may include: `hull_number`, `home_port`, `ship_class_details`
- Army records may include: `parent_brigade`, `regimental_identity`, `vehicle_fleet`
- RAF records may include: `aircraft_type`, `parent_wing`, `squadron_number`

These optional fields are included when the agent can identify them, and omitted otherwise. The frontend should display them in popups when present.

Each service's analyst agent should populate its own optional fields as appropriate.

### 7. Frontend Updates (`osint_frontend/`)

Modify `index.html` and `server.py` to support all three services. Do not rebuild the frontend from scratch — make additive changes.

**Changes to `server.py`:**

- The `/api/status` endpoint must now check for data files from all three services. Return a structure like:
  ```json
  {
    "services": {
      "royal_navy": {
        "osint_data_exists": true,
        "osint_data_file": "rn_assets_20260315_143022.json",
        "osint_data_modified": "2026-03-15T14:30:22Z",
        "enriched_data_exists": true,
        "enriched_data_file": "rn_enriched_20260315_150000.json",
        "enriched_data_modified": "2026-03-15T15:00:00Z"
      },
      "british_army": { ... same fields ... },
      "royal_air_force": { ... same fields ... }
    }
  }
  ```

- The `/api/data` endpoint must merge data from all three services into a single response, with each record tagged by its `service` field. If one service has no data, skip it without failing.

- The `/api/gather` endpoint now accepts an array of services to run:
  ```json
  { "agents": ["royal_navy", "british_army", "royal_air_force"] }
  ```
  The server launches the appropriate OSINT and analyst agent subprocesses for each requested service, streaming their combined output. Include a `source` field in log events indicating which service and which stage (OSINT vs analyst) the line came from.

- Add configuration variables at the top of `server.py` for the new agent directories:
  ```python
  AGENTS = {
      "royal_navy": {
          "osint_dir": "../rn_osint_agent",
          "analyst_dir": "../rn_analyst_agent",
          "osint_cmd": ["python", "agent.py"],
          "analyst_cmd": ["python", "analyst_agent.py"],
      },
      "british_army": {
          "osint_dir": "../ba_osint_agent",
          "analyst_dir": "../ba_analyst_agent",
          "osint_cmd": ["python", "agent.py"],
          "analyst_cmd": ["python", "analyst_agent.py"],
      },
      "royal_air_force": {
          "osint_dir": "../raf_osint_agent",
          "analyst_dir": "../raf_analyst_agent",
          "osint_cmd": ["python", "agent.py"],
          "analyst_cmd": ["python", "analyst_agent.py"],
      },
  }
  ```

**Changes to `index.html`:**

- **Intelligence Sources section**: All three toggles (Royal Navy, British Army, Royal Air Force — in that order) are functional and all on by default. Multi-select: any combination can be enabled. These toggles control which services' agents get run when "Gather Fresh OSINT" is executed — they do **not** filter the map display (that is handled by the separate Filter by Service section). Toggle label text colour is driven by `/api/status`: `var(--text-primary)` if that service has data, `var(--text-dim)` if not — changes automatically with the active theme.

- **Colour markers by dropdown**: Replace existing options with exactly two:
  - **Service** (default, selected on load) — fill = service colour
  - **Readiness** — fill = readiness colour (High `#00e676`, Medium `#ffab00`, Low `#ff1744`)
  Remove any other options (category, capability). The dropdown has exactly two options.

- **Marker design** — fill encodes the selected dimension; border is purely decorative:
  - Fill colour = "Colour markers by" selection (service or readiness). Service colours: Royal Navy `#1a237e`, British Army `#c62828`, Royal Air Force `#4fc3f7`, Joint `#8e24aa`.
  - Border: thin 1px dark outline `#1a1a2e` on all markers. No service-colour border. The border does not encode any data dimension.
  - Shape: **square** (`divIcon`, 14×14px) for fixed installations (`naval_base`, `base`, `air_station`, `station`, `barracks`, `training_establishment`, `headquarters`). **Circle** (`circleMarker`, 8px radius) for all mobile units. Both shapes use the same fill/border rules.

- **Asset labels**: Leaflet tooltip default styling (white border/background) is stripped via a custom CSS class `osint-label`. Label text is uniform `#c8d6e5` regardless of service. Background and border are theme-aware via `getLabelStyles()`: DEFAULT = dark navy bg + faint blue-grey border; HIGHCON = black bg + white border; NIGHTVIS = dark red bg + deep red border. Padding `1px 3px`. Labels redraw on theme change.

- **HIGHCON basemap**: All themes use CartoDB `dark_all`. When HIGHCON is active, a CSS filter (`invert(1) grayscale(1) brightness(0.45) contrast(2)`) is applied to Leaflet's tile pane, producing lighter grey sea and darker grey land. Applied via `map.getPanes().tilePane.style.filter` in `setTheme()`.

- **Show on map toggles**: Keep **Asset labels** toggle only (default: on). Remove Confidence radius and Capability overlay toggles.

- **Filter by Service section** (new, separate from Intelligence Sources): Four checkboxes, all checked by default — Royal Navy, British Army, Royal Air Force, Joint/Other. When unchecked, that service's units disappear from the map. Footer HIDDEN count reflects units filtered by these checkboxes.

- **Filter by Readiness section** (new, separate from Map Controls): Three checkboxes — High, Medium, Low (all checked by default). Both filter groups apply simultaneously.

- **"Gather Fresh OSINT" execution**: Only runs agents for the currently-enabled Intelligence Sources toggles. Update the UI to collect which services to run and send them in the POST body.

- **Agent log panel**: Prefix each SSE log line with a `[SERVICE/STAGE]` tag (e.g. `[NAVY/OSINT]`, `[ARMY/ANALYST]`). Colour the tag with the service's fill colour.

- **Legend**: Two subsections:
  - **Marker Shape** (static): square = fixed installation, circle = mobile unit.
  - **Colour Key** (dynamic): when Service selected, show four service colour swatches; when Readiness selected, show three readiness colour swatches. No "services as border" subsection — colour key covers the service dimension when dropdown = Service.

- **Marker popups**: Service badge at the top (coloured pill). Followed by existing fields. Service-specific optional fields displayed in a unit details table when present (hull_number, home_port for Navy; aircraft_type, parent_wing, squadron_number for RAF; parent_brigade, regimental_identity, vehicle_fleet for Army). No capability bar chart in popups.

### 8. GitHub Pages Demo Version (`docs/index.html`)

Regenerate the GitHub Pages demo version after the frontend changes are complete. Embed the merged JSON from all three services into the demo HTML. The demo should show units from whichever services have data available at the time of generation — if only Navy data exists, the demo shows only Navy units but still displays all three service toggles (Army and RAF will simply show no units when toggled on).

The demo's "Gather fresh OSINT" and "Execute" buttons remain clickable but non-functional, displaying the same `[STATUS] Live agent execution not available in demo mode` message as before.

## Order of Implementation

Do the work in this order to avoid breaking the existing system:

1. Read all existing files to understand the current patterns.
2. Update `rn_osint_agent/tools.py` and `rn_osint_agent/agent.py` with the new search guidance (date-bounding, site filters, narrow queries, link-following). Test that the Navy agent still runs.
3. Create `ba_osint_agent/` by copying the updated Navy agent and adapting it. Test it runs end-to-end.
4. Create `raf_osint_agent/` the same way. Test it runs end-to-end.
5. Create `ba_analyst_agent/` by copying and adapting the Navy analyst. Test it runs.
6. Create `raf_analyst_agent/` the same way. Test it runs.
7. Update `server.py` to handle all three services in the `/api/status`, `/api/data`, and `/api/gather` endpoints.
8. Update `index.html` with the multi-service toggles, service-coloured borders, updated footer stats, and legend changes.
9. Test the full system end-to-end with at least one service's data loaded.
10. Regenerate `docs/index.html` with embedded data from all available services.

## Environment Variables and .env Support

All six agent entry points (`agent.py` ×3, `analyst_agent.py` ×3) and `server.py` must load API keys from a `.env` file in the project root. Add `python-dotenv` to every `requirements.txt` (all six agent directories and the frontend). At the very top of each entry point, after the module docstring:

```python
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
```

This path (`__file__ / .. / .. / .env`) correctly resolves to the project root regardless of working directory or how the process was launched (including as a Flask subprocess).

In `server.py`, when launching subprocesses pass `env={**os.environ}` to `subprocess.Popen` so the loaded environment variables propagate to child processes.

Create two files in the project root:
- `.env` — real keys (add to `.gitignore`, never commit)
- `.env.example` — placeholder values, committed to the repo

Required keys:
```
ANTHROPIC_API_KEY=your-anthropic-api-key-here
BRAVE_SEARCH_API_KEY=your-brave-search-api-key-here
```

## What NOT To Do

- Do not modify the core agent loop logic in ways that change the behaviour of the existing Navy agent beyond the search improvements described.
- Do not rename or restructure the existing `rn_osint_agent/` or `rn_analyst_agent/` directories.
- Do not change the existing JSON output schema in ways that break backward compatibility — only add optional fields.
- Do not rebuild the frontend from scratch. Make additive and targeted changes.
- Do not introduce new dependencies beyond what's already in use (`anthropic`, `requests`, `beautifulsoup4`, `pydantic`, `rich`, `trafilatura`, `flask`, `python-dotenv`).
- Do not combine the three OSINT agents into a single shared module. Each service has its own agent codebase, even though they follow the same pattern.
- Do not encode service as a border/outline on markers. Service is encoded as fill colour (when the dropdown is set to Service). The marker border is always a thin dark outline `#1a1a2e` for contrast only.
