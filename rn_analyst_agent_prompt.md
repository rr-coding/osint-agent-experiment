# Royal Navy Analyst Agent — Claude Code Prompt

## Project Goal

Build a genuine AI agent that acts as a naval intelligence analyst. It takes the JSON dataset produced by the OSINT tracking agent (containing Royal Navy asset names, types, locations, and confidence scores) and enriches each entry with operational readiness assessments, current assignments, unit classifications, and capability profiles. The agent uses the Anthropic API with tool use to research each asset, make analytical judgments, and produce a new enriched JSON dataset.

This is not a data transformation script. The agent must use LLM reasoning to make judgment calls — for example, inferring that a ship recently reported as undergoing engine repairs has low operational readiness, or that a Type 45 destroyer's primary capability is air defence based on its class characteristics and known systems.

## Architecture

```
rn_analyst_agent/
├── analyst_agent.py    # Main agent loop and orchestration
├── tools.py            # Tool definitions and implementations
├── models.py           # Pydantic models for input and enriched output
├── config.py           # Configuration constants
├── output/             # Directory for enriched JSON output
└── requirements.txt
```

## Input

The agent reads a JSON file produced by the OSINT tracking agent. Each entry has this structure:

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

The input file path should be passed as a command-line argument: `python analyst_agent.py output/rn_assets_20260315.json`

If no file is provided, print usage instructions and exit.

## What the Agent Enriches

For each asset in the input dataset, the agent researches and adds the following fields:

### 1. Operational Readiness

A judgment of `high`, `medium`, or `low` based on what the agent can find about the asset's current state.

- **high**: Deployed, on active duty, recently completed exercises, no reported maintenance issues.
- **medium**: Alongside but available, recently returned from deployment (crew rest period), minor maintenance underway, generating readiness for upcoming deployment.
- **low**: In refit, major maintenance, reported mechanical or systems problems, decommissioning, or in reserve.

The agent must provide a `readiness_rationale` explaining its reasoning, citing what evidence it found or noting when it is inferring from limited information.

### 2. Current Assignment

A short text description of what the asset is currently doing or assigned to, for example:
- "Carrier Strike Group 2026 — Indo-Pacific deployment"
- "Standing NATO Maritime Group 1"
- "Fishery protection duties, UK waters"
- "Refit at Babcock, Devonport"
- "Home-ported, no current assignment identified"

If the agent cannot determine an assignment, it should say so honestly rather than fabricate one.

### 3. Unit Category

Refine the basic `type` field from the input into a more specific classification. Valid categories:

- `aircraft_carrier`
- `destroyer`
- `frigate`
- `submarine_fleet` (attack submarines)
- `submarine_strategic` (ballistic missile submarines)
- `amphibious_assault`
- `patrol_vessel`
- `mine_countermeasures`
- `auxiliary` (tankers, supply ships, survey vessels)
- `naval_base`
- `air_station`
- `training_unit`
- `other`

The agent should determine this from the asset's class name and its own knowledge of Royal Navy ship classes. For example, it knows that Daring-class are Type 45 destroyers, Queen Elizabeth-class are aircraft carriers, and Astute-class are fleet submarines.

### 4. Operation Types and Capability Scores

This is the most analytically demanding part. The agent must first generate a master list of up to 10 operation types that are relevant to the Royal Navy assets in the dataset. It does this once at the start, examining the full list of assets and deciding which operation types are meaningful given what's present.

The operation types should be drawn from categories such as (but the agent decides the final list based on the actual data):
- Carrier strike / power projection
- Air defence
- Anti-submarine warfare
- Anti-surface warfare
- Amphibious assault
- Humanitarian assistance / disaster relief
- Maritime security / protecting shipping
- Mine countermeasures
- Nuclear deterrent
- Intelligence, surveillance, and reconnaissance
- Evacuation operations (NEO)
- Training and exercises

For each asset, the agent then assigns a capability score of 0–5 for each operation type:
- **0**: Not applicable (e.g., a naval base cannot conduct anti-submarine warfare)
- **1**: Minimal or theoretical capability
- **2**: Limited capability
- **3**: Moderate capability
- **4**: Strong capability
- **5**: Primary role / optimised for this operation type

The agent must provide a brief `capability_rationale` for each asset explaining the key factors behind its scoring. This should reference the ship's class, known systems, and typical roles.

**Critical**: The operation type list must be generated by the agent based on its analysis of the dataset, not hardcoded. This is part of what makes it agentic — it examines the data, reasons about what categories are meaningful, and produces a tailored taxonomy. If the dataset contains only surface ships and bases, the agent should not include "nuclear deterrent" in the operation types. If the dataset includes a ballistic missile submarine, it should.

## Core Agent Loop (analyst_agent.py)

The agent uses the Anthropic Python SDK with tool use, following the same pattern as the OSINT agent. The loop:

1. **Load and assess the input dataset**: Read the JSON file. Use the LLM to examine the full list of assets and generate the master list of operation types. This is the agent's first analytical task.

2. **For each asset, decide what research is needed**: The agent looks at the asset's name, class, and existing data, then decides whether it has enough knowledge to make its assessments or whether it needs to search for more information. For well-known classes (like Queen Elizabeth-class carriers), the agent may already know enough about capabilities. For less familiar assets, or for current operational readiness and assignment, it will need to search.

3. **Research as needed**: The agent uses web search and page fetching tools to find recent information about each asset's status, maintenance, deployment, and assignment.

4. **Make analytical judgments**: After gathering information, the agent uses LLM reasoning to assign readiness levels, determine assignments, classify the unit, and score capabilities. It must explain its reasoning.

5. **Compile the enriched dataset**: Once all assets have been processed, output the enriched JSON.

The agent should process assets intelligently, not necessarily one at a time. For example, if it finds a news article about a carrier strike group deployment, that single article might provide assignment information for multiple ships. The agent should recognise this and update several assets from one source.

## Tool Definitions (tools.py)

### web_search
- **Input**: `query` (string)
- **Implementation**: Same as the OSINT agent — use Brave Search API if available, otherwise fall back to requests/BeautifulSoup.
- **Output**: List of results with title, URL, snippet.

### fetch_page
- **Input**: `url` (string)
- **Implementation**: Fetch and extract readable text. Limit to 4000 characters.
- **Output**: Extracted text, page title, URL.

### assess_asset
- **Input**: `asset_name` (string), `asset_class` (string), `gathered_context` (string — concatenated relevant text from searches), `operation_types` (list of strings — the master list)
- **Implementation**: LLM-powered tool. Send the asset details and gathered context to Claude and ask it to return the full enrichment: readiness, assignment, category, capability scores, and rationales.
- **Output**: The enrichment fields as structured JSON.

### generate_operation_types
- **Input**: `assets_summary` (string — a summary of all assets in the dataset including names, types, and classes)
- **Implementation**: LLM-powered tool. Ask Claude to examine the asset list and produce up to 10 relevant operation types, each with a short description. The agent should reason about which types are meaningful for this specific set of assets.
- **Output**: A list of operation type objects, each with `id` (snake_case), `name` (display name), and `description`.

### task_complete
- **Input**: `summary` (string)
- **Implementation**: Signals the agent loop to terminate.

## Agent System Prompt

"You are a naval intelligence analyst assessing the Royal Navy's current order of battle. You have been given a dataset of Royal Navy assets with their names, types, classes, and last known locations.

Your task is to enrich this dataset with your analytical assessments. For each asset, you will determine its operational readiness, current assignment, precise unit category, and its capability to support different types of naval operations.

You have access to web search tools to find current information about each asset's status. Use these when you need recent information — for example, whether a ship is in refit, or what task group it has been assigned to. For general knowledge about ship class capabilities and systems, you may rely on your training knowledge.

Be honest about uncertainty. If you cannot determine an asset's current assignment, say so. If your readiness assessment is based on limited information, note that in your rationale. Do not fabricate deployments or assignments.

Think about the assets as a fleet. When you research one ship and discover information about others in the same task group or at the same base, use that information to update multiple assets.

Process the assets efficiently. You do not need to run a separate search for every single asset — if you already know the capabilities of a Queen Elizabeth-class carrier, you can assess it directly and save your searches for readiness and assignment information that changes over time."

## Output Data Model (models.py)

The enriched output extends the input schema. Each entry in the output JSON has all original fields plus:

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
  "last_updated": "2026-03-15T14:30:00Z",

  "unit_category": "aircraft_carrier",
  "operational_readiness": "high",
  "readiness_rationale": "Currently deployed with Carrier Strike Group on scheduled Indo-Pacific deployment. No reported mechanical issues. Air group embarked and conducting flight operations.",
  "current_assignment": "Carrier Strike Group 2026 — Indo-Pacific deployment",
  "assignment_source": "https://ukdefencejournal.org.uk/...",

  "capability_scores": {
    "carrier_strike": 5,
    "air_defence": 4,
    "anti_submarine_warfare": 2,
    "amphibious_operations": 1,
    "humanitarian_relief": 3,
    "maritime_security": 3,
    "anti_surface_warfare": 3,
    "isr": 4,
    "training_exercises": 4,
    "evacuation_operations": 2
  },
  "capability_rationale": "Queen Elizabeth-class is optimised for carrier strike and power projection with embarked F-35B and helicopter air group. Strong ISR capability through organic air assets. Moderate humanitarian and maritime security capability due to deck space and helicopter capacity. Limited ASW capability without dedicated sonar suite, reliant on escort screen and embarked Merlin HM2."
}
```

The output also includes a top-level metadata section:

```json
{
  "metadata": {
    "generated_at": "2026-03-15T15:00:00Z",
    "source_file": "rn_assets_20260315.json",
    "agent_model": "claude-opus-4-6",
    "total_assets_analysed": 5,
    "total_iterations": 7,
    "total_tokens_used": 45000,
    "operation_types": [
      {
        "id": "carrier_strike",
        "name": "Carrier Strike / Power Projection",
        "description": "Ability to project offensive air power from the sea using fixed-wing aircraft and cruise missiles"
      }
    ]
  },
  "assets": [ ... ]
}
```

## Configuration (config.py)

```python
MODEL = "claude-opus-4-6"
MAX_ITERATIONS = 15
MAX_TEXT_PER_PAGE = 4000
REQUEST_TIMEOUT = 10
MAX_OPERATION_TYPES = 10
```

## Logging and Observability

Use the `rich` library for coloured terminal output. Log:

- The generated operation types list (print the full list with descriptions at the start).
- For each asset: what the agent decided to research, what it found, and the final assessment.
- When the agent discovers information relevant to multiple assets from a single source, log this cross-referencing.
- A running count of assets enriched vs total.
- Cumulative token usage.
- A final summary table showing all assets with their readiness, assignment, and top capability.

## Error Handling

- If the input JSON file is malformed or missing required fields, print a clear error and exit.
- If web searches fail for a particular asset, the agent should still produce an assessment using its general knowledge about the ship class, but flag that the readiness and assignment fields are based on limited information.
- If the Anthropic API call fails, implement exponential backoff with a maximum of 3 retries.
- Wrap all tool executions in try/except. The agent must never crash — it should degrade gracefully and note limitations in its rationales.

## Output

At the end of the run:

1. Save the enriched dataset to `output/rn_enriched_TIMESTAMP.json`.
2. Print the complete enriched JSON to the terminal, formatted with indentation.
3. Print a summary table with columns: Name, Category, Readiness, Assignment, Top Capability.
4. Print the operation types list with descriptions.
5. Print total token usage and iteration count.

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

- Do not build any visualisation or map at this stage. This agent produces data only.
- Do not use LangChain, CrewAI, or any agent framework. Use the Anthropic SDK directly with tool use.
- Do not hardcode capability scores for ship classes. The agent must reason about each asset using its knowledge and any information it gathers. Two ships of the same class might get different readiness scores if one is in refit.
- Do not hardcode the operation types list. The agent generates it based on what assets are in the dataset.
- Do not use async/await. Keep it synchronous for readability.
- Do not skip the web search step and rely purely on the LLM's training knowledge for readiness and assignment. These change over time and must be researched. Capability scoring can use training knowledge for class characteristics, but current status requires search.
