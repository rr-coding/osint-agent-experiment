# OSINT Command Centre — Web Frontend Prompt for Claude Code

## Project Goal

Build a military-style OSINT command centre web application. It displays assets from the Royal Navy, British Army, and Royal Air Force on an interactive map, with a control panel for selecting agents, triggering data gathering, and viewing agent reasoning logs. The frontend reads real JSON data produced by the OSINT and analyst agents, and can trigger fresh agent runs via a lightweight backend server.

This is **deterministic frontend code with a thin Python backend** — no AI agent logic lives here. The agents are separate Python programs that this system invokes and monitors.

## Visual Reference

The target aesthetic is a military command and control centre: dark navy/black backgrounds, cyan accent lines, monospaced typography, flat rectangular controls with no rounded corners. Similar to the Shutterstock image "UI interface, earth globe, control center" (asset 1190802196) — a dark display with a central map, surrounding data panels, thin bright accent lines, and a HUD overlay feel.

## Technology

- **Frontend**: Single HTML file (`index.html`) with embedded CSS and JavaScript. No React, no npm, no build tools.
- **Backend**: Single Python file (`server.py`) using Flask. Serves the static frontend and provides API endpoints for data checking, data loading, and agent execution.
- **Map**: Leaflet.js from CDN (`https://unpkg.com/leaflet@1.9.4/dist/leaflet.js`). Dark tile layer: CartoDB Dark Matter (`https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png`).
- **Font**: `"Share Tech Mono"` from Google Fonts, falling back to `"Courier New", monospace`.

## File Structure

```
osint_frontend/
├── server.py           # Flask backend — serves frontend and API endpoints
├── index.html          # The single HTML file with all CSS and JS embedded
├── requirements.txt    # Flask, python-dotenv, and dependencies
└── README.md           # Instructions for running
```

The server expects agent output directories for all three services, relative to `osint_frontend/`. These paths are configured at the top of `server.py` in the `AGENTS` dict (see Backend section below).

### Environment Variables

API keys must be provided via a `.env` file in the project root (parent of `osint_frontend/`):

```
ANTHROPIC_API_KEY=your-anthropic-api-key-here
BRAVE_SEARCH_API_KEY=your-brave-search-api-key-here
```

Each Python entry point (`server.py`, every `agent.py`, every `analyst_agent.py`) must load this file at startup using `python-dotenv`:

```python
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
```

This ensures keys are available regardless of working directory or how the process was launched, including when launched as a subprocess by the Flask server. The `.env` file is listed in `.gitignore` and must never be committed. A `.env.example` with placeholder values is committed instead.

## Backend Server (server.py)

A minimal Flask application. Load `.env` at the top before any other imports using `python-dotenv` (see Environment Variables above). When launching agent subprocesses, pass `env={**os.environ}` so the loaded keys propagate to child processes.

### GET /
Serves `index.html`.

### GET /api/status
Returns JSON indicating what data files are available for all three services:
```json
{
  "services": {
    "royal_navy": {
      "osint_data_exists": true,
      "osint_data_file": "rn_assets_20260418_094416.json",
      "osint_data_modified": "2026-04-18T09:44:16Z",
      "enriched_data_exists": true,
      "enriched_data_file": "rn_enriched_20260418_094416.json",
      "enriched_data_modified": "2026-04-18T09:44:16Z"
    },
    "british_army": { "...same fields..." },
    "royal_air_force": { "...same fields..." }
  }
}
```
The server checks the respective output directories for the most recent JSON file (by modification time). If no files exist, the `_exists` fields are `false` and the other fields are `null`.

### GET /api/data
Merges enriched (or OSINT fallback) data from all three services into a single response. Each record is tagged with its `service` field. If one service has no data, skip it without failing. Returns:
```json
{
  "metadata": {
    "generated_at": "...",
    "services_loaded": ["royal_navy", "british_army", "royal_air_force"],
    "total_tokens_used": 123456,
    "operation_types": [...]
  },
  "assets": [...]
}
```
Returns 404 if no data exists at all.

### POST /api/gather
Triggers agent runs for the requested services. Accepts:
```json
{ "agents": ["royal_navy", "british_army", "royal_air_force"] }
```
For each service: launches OSINT agent, waits for completion, then launches analyst agent. Streams combined stdout/stderr as Server-Sent Events. Each log event includes a `source` field indicating which service and stage (`NAVY/OSINT`, `ARMY/ANALYST`, etc.).

Event types: `log` (agent output line), `status` (system message), `complete`, `error`.

### Server configuration (top of server.py)
```python
AGENTS = {
    "royal_navy": {
        "osint_dir": "../rn_osint_agent",
        "analyst_dir": "../rn_analyst_agent",
        "osint_cmd": ["python", "agent.py"],
        "analyst_cmd": ["python", "analyst_agent.py"],
        "osint_glob": "rn_assets_*.json",
        "analyst_glob": "rn_enriched_*.json",
        "label": "NAVY",
    },
    "british_army": {
        "osint_dir": "../ba_osint_agent",
        "analyst_dir": "../ba_analyst_agent",
        "osint_glob": "ba_assets_*.json",
        "analyst_glob": "ba_enriched_*.json",
        "label": "ARMY",
    },
    "royal_air_force": {
        "osint_dir": "../raf_osint_agent",
        "analyst_dir": "../raf_analyst_agent",
        "osint_glob": "raf_assets_*.json",
        "analyst_glob": "raf_enriched_*.json",
        "label": "RAF",
    },
}
HOST = "127.0.0.1"
PORT = 8080
```

## Page Layout

Single full-viewport layout, no scrolling on the main page, no subpages.

```
┌──────────────────────────────────────────────────────────────────────┐
│  HEADER BAR — "OSINT COMMAND CENTRE" + status + UTC clock           │
├───────────────┬──────────────────────────────────────────────────────┤
│               │                                                      │
│  LEFT PANEL   │                                                      │
│  (320px)      │              MAP AREA                                │
│               │              (fills remaining space)                  │
│  - Agent      │                                                      │
│    toggles    │                                                      │
│  - Data       │                                                      │
│    source     │                                                      │
│  - Operations │                                                      │
│  - Agent log  │                                                      │
│  - Map        │                                                      │
│    controls   │                                                      │
│  - Legend      │                                                      │
│               │                                                      │
├───────────────┴──────────────────────────────────────────────────────┤
│  FOOTER BAR — stats, token count, last updated                      │
└──────────────────────────────────────────────────────────────────────┘
```

## Header Bar

- Title: 🌐 followed by "OSINT COMMAND CENTRE" in `Share Tech Mono`, uppercase, letter-spacing 3px. Use the globe emoji (🌐), not an anchor.
- Centre: three flat rectangular theme toggle buttons — **DEFAULT**, **HIGHCON**, **NIGHTVIS** — described in the Design System section below. The active button is filled with `--border-accent`. These sit between the title and the right-side status area.
- Right side: status indicator showing "SYSTEM READY" (green pulsing dot), "GATHERING INTEL..." (amber pulsing dot), or "NO DATA" (red static dot).
- UTC clock updating every second, format: `22 MAR 2026 14:32:07Z`.
- 1px horizontal line in `--border-accent` colour below the header.

## Left Panel Sections

Width: 320px fixed. Dark background (`--bg-panel`), separated from map by 1px cyan vertical line. Sections divided by section headers in 11px uppercase monospaced text with letter-spacing 2px.

From top to bottom:

### Section 1: INTELLIGENCE SOURCES

Three toggle switches for agent types — all functional, multi-select (not radio), listed in this order:
- **⚓ Royal Navy** — on by default.
- **⚔ British Army** — on by default.
- **✈ Royal Air Force** — on by default.

These toggles control only which services' agents are invoked when "Gather Fresh OSINT" is executed. They do **not** filter the map display — that is controlled by the Filter by Service section below. Changing a toggle calls `updateExecuteBtn()` only.

Toggle label text colour is driven by `GET /api/status`: `var(--text-primary)` if that service has data, `var(--text-dim)` if not. This means the colour automatically follows the active theme and changes when the view mode is switched.

### Section 2: DATA SOURCE

Two mutually exclusive options, styled as rectangular toggle buttons (only one active at a time):

**"USE EXISTING DATA"**
- On page load, the frontend calls `GET /api/status` to check if data files exist across all three services.
- If any data exists: this button is illuminated (accent border, bright text), and below it shows the most recently modified file name and date.
- If no data exists: this button is greyed out and disabled.
- **On page load, if data exists, the frontend automatically selects "Use Existing Data" and calls `GET /api/data`, populating the map without requiring the user to click EXECUTE.**

**"GATHER FRESH OSINT"**
- Available when at least one Intelligence Sources toggle is on.
- When selected and the user clicks EXECUTE, calls `POST /api/gather` with the list of currently-enabled services.

### Section 3: OPERATIONS

A single large button: **"EXECUTE"**. Disabled when no datasource is selected or no intelligence source is on. Running state: amber border, pulsing animation, text "EXECUTING...".

### Section 4: AGENT LOG

Scrollable text box (~280px tall), dark inset background. Monospaced, 11px.

- Colour-coded lines: cyan `[DECISION]`/`[SEARCH]`, green `[FOUND]`/`[ANALYSIS]`, amber `[WARNING]`/`[RETRY]`, red `[ERROR]`, white everything else.
- When receiving SSE events from a live agent run, each log line is prefixed with a coloured `[SERVICE/STAGE]` tag (e.g. `[NAVY/OSINT]`, `[ARMY/ANALYST]`). The tag is coloured with the service colour.
- Auto-scrolls to bottom. Small "CLEAR" button in top-right corner.

### Section 5: MAP CONTROLS

**Colour markers by** (drop-down, 2 options):
- **Service** (default) — fill colour = service colour
- **Readiness** — fill colour = readiness colour (high=green, medium=amber, low=red)

**Asset labels** checkbox (default: on) — show asset name next to each marker.

Changing any control immediately updates the map without reloading data.

### Section 6: FILTER BY SERVICE

Four checkboxes, all checked by default:
- ⚓ Royal Navy
- ⚔ British Army
- ✈ Royal Air Force
- ◆ Joint / Other

When a checkbox is unchecked, units belonging to that service disappear from the map. Unchecked units are counted in the footer HIDDEN stat.

### Section 7: FILTER BY READINESS

Three checkboxes, all checked by default: High, Medium, Low.

Both filter groups apply simultaneously. A unit is visible only if both its service checkbox and readiness checkbox are checked.

### Section 8: LEGEND

Two subsections:

**Marker Shape** (static):
- Small filled square → Fixed installation (base / station / barracks)
- Small filled circle → Mobile unit

**Colour Key** (dynamic, updates when "Colour markers by" changes):
- When **Service**: four coloured swatches (Royal Navy, British Army, Royal Air Force, Joint / Other)
- When **Readiness**: three coloured swatches (High, Medium, Low)

## Map Area

Fills all remaining space to the right of the left panel.

### Map Configuration
- Leaflet.js. All themes use CartoDB Dark Matter tiles (`dark_all`) as the base URL.
- Default view: centred on UK (54°N, 2°W), zoom level 5.
- Override Leaflet default control CSS to match the dark theme.
- Attribution text styled to be dim and unobtrusive.
- **HIGHCON basemap**: A CSS filter (`invert(1) grayscale(1) brightness(0.45) contrast(2)`) is applied to Leaflet's tile pane element when HIGHCON is active, giving lighter grey sea and darker grey land. This affects only the tile pane — markers, labels, and UI are unaffected. The filter is removed when switching to DEFAULT or NIGHTVIS.

### Markers

**Shape encodes mobility:**
- **Fixed installations** — `divIcon` square, 14×14px. Applies to: `naval_base`, `base`, `air_station`, `station`, `barracks`, `training_establishment`, `headquarters`.
- **Mobile units** — `circleMarker`, 8px radius. Applies to everything else (ships, submarines, squadrons, regiments, brigades, etc.).

**Fill colour** is determined by the "Colour markers by" dropdown:
- **Service** (default): Royal Navy `#1a237e`, British Army `#c62828`, Royal Air Force `#4fc3f7`, Joint `#8e24aa`
- **Readiness**: High `#00e676`, Medium `#ffab00`, Low `#ff1744`

**Border**: thin 1px dark outline `#1a1a2e` on all markers. The border does not encode any data dimension — it is purely for contrast against the dark map tiles.

Markers fade in with a 0.3s CSS opacity transition when data loads.

Asset labels (when enabled) are Leaflet tooltips anchored to the right of each marker. The Leaflet default tooltip styling (white border and background) is fully stripped via a custom CSS class (`osint-label`). All visual styling is applied through an inner `<span>`:
- Text colour: uniform `#c8d6e5` regardless of service or colour mode.
- Background and border: theme-aware, computed by `getLabelStyles()`:
  - **DEFAULT**: `rgba(10,14,23,0.75)` bg, `rgba(200,214,229,0.45)` border
  - **HIGHCON**: `rgba(0,0,0,0.85)` bg, `rgba(255,255,255,0.7)` border
  - **NIGHTVIS**: `rgba(20,0,0,0.75)` bg, `rgba(180,0,0,0.8)` border (deep red)
- Padding: `1px 3px`.
- Labels redraw immediately when the theme changes (via `setTheme()` calling `updateMap()`).

### Marker Popups
Styled dark popups (override Leaflet `.leaflet-popup-content-wrapper` CSS). Min-width 350px. Contains:

- Service badge at top (coloured pill: NAVY / ARMY / RAF / JOINT).
- Asset name (bold, `--text-bright`).
- Class / type, unit category.
- Operational readiness — colour-coded text (green/amber/red) + readiness rationale in small dim text.
- Current assignment.
- Location description and coordinates.
- Confidence score as percentage with a thin horizontal bar.
- Service-specific optional fields when present: hull number, home port (Navy); aircraft type, parent wing, squadron number (RAF); parent brigade, regimental identity, vehicle fleet (Army).
- Source URLs as clickable links (cyan, opening in new tab).

## Footer Bar

- Left: `TOKENS: N | UPDATED: DD MMM YYYY HH:MMZ` (from JSON metadata).
- Centre: per-service counts + located + hidden + avg confidence, e.g. `NAVY: 17 | ARMY: 8 | RAF: 8 | LOCATED: 25 | HIDDEN: 2 | AVG CONF: 84%`. Only services with data appear. Hidden = units filtered out by the Filter by Service checkboxes.
- Right: empty (reserved).
- If no data is loaded, show: `NO DATA LOADED` centred.
- 1px cyan line above the footer.

## Design System

### Colour Themes

The page supports three selectable view modes, toggled via buttons in the header. Switching themes changes only the colour scheme — layout, controls, and map data are unaffected. Implement as CSS variable overrides on `body` using classes `theme-highcon` and `theme-nightvis` (default has no extra class).

**DEFAULT** — cyan on dark grey (the base theme):
```css
--bg-primary: #0a0e17;  --bg-panel: #0f1520;  --bg-inset: #070b12;
--border-accent: #00e5ff;
--text-primary: #c8d6e5;  --text-bright: #e8f0f8;  --text-dim: #4a5568;
--status-high: #00e676;  --status-medium: #ffab00;  --status-low: #ff1744;
--accent-glow: rgba(0,229,255,0.3);
```

**HIGHCON** — yellow/white on pure black (`body.theme-highcon`):
```css
--bg-primary: #000000;  --bg-panel: #0c0c0c;  --bg-inset: #000000;
--border-accent: #ffe600;
--text-primary: #ffffff;  --text-bright: #ffffff;  --text-dim: #888888;
--status-high: #00ff88;  --status-medium: #ffe600;  --status-low: #ff2222;
--accent-glow: rgba(255,230,0,0.35);
```

**NIGHTVIS** — red on very dark (`body.theme-nightvis`):
```css
--bg-primary: #070305;  --bg-panel: #0c0608;  --bg-inset: #040204;
--border-accent: #ff2200;
--text-primary: #cc8880;  --text-bright: #ffbbaa;  --text-dim: #553333;
--status-high: #ff6600;  --status-medium: #cc3300;  --status-low: #880011;
--accent-glow: rgba(255,34,0,0.30);
```

All hardcoded accent colour values in CSS (e.g. border rgba values, toggle backgrounds) must use derived CSS variables (`--border-subtle`, `--border-mid`, `--border-faint`, `--toggle-bg-on`) that are also overridden per theme — not hardcoded `rgba(0,229,255,...)` values that only work for DEFAULT.

### Typography
- All text: `"Share Tech Mono", "Courier New", monospace` from Google Fonts.
- Section headers: 11px, uppercase, letter-spacing 2px, `--text-dim`, thin underline.
- Data values: 13px, `--text-primary`.
- `text-rendering: optimizeLegibility; -webkit-font-smoothing: antialiased;`

### UI Controls
- **All controls: `border-radius: 0` everywhere. No rounded corners. No shadows. No gradients. No skeuomorphism.**
- Buttons: 1px solid `--border-accent`, transparent background, cyan text. Hover: filled cyan background, dark text.
- Drop-downs: dark background, 1px cyan border, custom flat caret.
- Toggles: rectangular track, square handle. Active: `--border-accent` fill. Inactive: `--text-dim` border.
- Checkboxes: square, 1px cyan border when checked, filled cyan when active.

### Animations
- Subtle and purposeful only. No playful or bouncy effects.
- Status dot pulse: 2s ease-in-out, opacity 0.4–1.0.
- Execute button running state: 1.5s border-colour pulse, cyan to amber.
- Map marker fade-in: 0.3s opacity transition.
- Log lines: appear instantly (they're streaming in real time from SSE, no artificial delay needed).

## Dependencies

### Frontend
- Leaflet.js 1.9.4 (CDN)
- Share Tech Mono font (Google Fonts CDN)
- No other dependencies

### Backend (requirements.txt)
```
flask
python-dotenv
```

## Running the Application

```bash
# Create .env in project root with API keys (see .env.example)
cd osint_frontend
pip install flask python-dotenv
python server.py
```

Then open `http://127.0.0.1:8080` in a browser. The README should include these instructions plus notes on the expected directory layout for the agent output folders.

## What NOT To Build

- No React, Vue, or any framework. Vanilla HTML, CSS, and JavaScript only for the frontend.
- No npm, no build step, no bundler.
- No subpages, routing, or navigation. Single page only.
- No rounded corners or skeuomorphic elements anywhere.
- No authentication or user accounts.
- No database. The server reads JSON files from disk.
- No fake or sample data. The page works with real agent output or shows "No data available" if none exists.
- Do not embed agent logic in the server. The server launches agents as subprocesses and streams their output. It does not contain any OSINT or analysis logic itself.
