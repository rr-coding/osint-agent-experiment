"""
Tool definitions and implementations for the RN OSINT agent.
"""
import json
import time
import requests
from typing import Optional
from datetime import datetime

import anthropic
from bs4 import BeautifulSoup
from rich.console import Console

import config
from geocoding import resolve_location as _resolve_location

console = Console()

# ─── Tool schemas for Anthropic API ────────────────────────────────────────────

TOOL_SCHEMAS = [
    {
        "name": "web_search",
        "description": (
            "Search the web for information about Royal Navy ships, deployments, and bases. "
            "Returns a list of search results with titles, URLs, and snippets. "
            "Keep queries narrow and focused — one piece of information per query. "
            "Use the site parameter to scope queries to authoritative domains. "
            "Use freshness='pm' (default) for recent content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query string. Keep narrow: one topic per query.",
                },
                "freshness": {
                    "type": "string",
                    "description": (
                        "Brave Search freshness filter. 'pd'=past day, 'pw'=past week, "
                        "'pm'=past month (default), 'py'=past year. Use 'py' only for "
                        "historical context; always use 'pm' or shorter for current status."
                    ),
                    "enum": ["pd", "pw", "pm", "py"],
                },
                "site": {
                    "type": "string",
                    "description": (
                        "Optional: restrict to a specific domain, e.g. 'royalnavy.mod.uk'. "
                        "Run the same query against each seed domain separately for better coverage."
                    ),
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_page",
        "description": (
            "Fetch and extract the main text content from a web page URL. "
            "Strips navigation and boilerplate. Returns extracted text, title, and URL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL of the web page to fetch",
                }
            },
            "required": ["url"],
        },
    },
    {
        "name": "extract_and_update",
        "description": (
            "Extract Royal Navy asset information from raw text content using AI. "
            "Identifies ships, submarines, bases, and units along with any location information. "
            "Call this after fetching a page to parse its content into structured data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Raw text content from a fetched page",
                },
                "source_url": {
                    "type": "string",
                    "description": "The URL the text was fetched from",
                },
            },
            "required": ["text", "source_url"],
        },
    },
    {
        "name": "resolve_location",
        "description": (
            "Resolve a vague location description for a Royal Navy asset into approximate "
            "coordinates and a confidence score. Use this when you have a location description "
            "but need geocoordinates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "asset_name": {
                    "type": "string",
                    "description": "Name of the Royal Navy asset (e.g., 'HMS Diamond')",
                },
                "location_description": {
                    "type": "string",
                    "description": "Location description to resolve (e.g., 'deployed to the Indo-Pacific')",
                },
            },
            "required": ["asset_name", "location_description"],
        },
    },
    {
        "name": "task_complete",
        "description": (
            "Signal that the intelligence gathering task is complete. Call this when you have "
            "identified at least 5 Royal Navy assets with resolved locations, or when no further "
            "productive searches are possible."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Brief summary of what was found and why the task is complete",
                }
            },
            "required": ["summary"],
        },
    },
]


# ─── Tool implementations ──────────────────────────────────────────────────────

def tool_web_search(query: str, freshness: str = "pm", site: Optional[str] = None) -> dict:
    """Search the web using the Brave Search API."""
    if site:
        query = f"{query} site:{site}"
    console.print(f"[cyan]  → Searching: '{query}'[/cyan]")
    try:
        params = {"q": query, "count": 8}
        if freshness:
            params["freshness"] = freshness
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            params=params,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": config.BRAVE_SEARCH_API_KEY,
            },
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("web", {}).get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("description", ""),
            })
        console.print(f"[dim]    Brave: {len(results)} results[/dim]")
        return {"results": results, "query": query}
    except Exception as e:
        console.print(f"[yellow]    Brave search error: {e}[/yellow]")
        return {"results": [], "query": query, "error": str(e)}


def tool_fetch_page(url: str, already_fetched: list) -> dict:
    """Fetch and extract text from a web page."""
    if url in already_fetched:
        return {"error": f"Already fetched: {url}", "url": url}

    console.print(f"[cyan]  → Fetching: {url}[/cyan]")
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=config.REQUEST_TIMEOUT)

        if resp.status_code == 403:
            return {"error": "403 Forbidden (paywall or bot protection)", "url": url, "title": ""}
        if resp.status_code == 404:
            return {"error": "404 Not Found", "url": url, "title": ""}
        resp.raise_for_status()

        # Try trafilatura first for clean extraction
        text = None
        title = ""
        try:
            import trafilatura
            text = trafilatura.extract(resp.text, include_comments=False, include_tables=False)
        except Exception:
            pass

        # Fall back to BeautifulSoup
        if not text:
            soup = BeautifulSoup(resp.text, "html.parser")
            # Get title
            title_tag = soup.find("title")
            title = title_tag.get_text(strip=True) if title_tag else ""
            # Remove navigation, scripts, styles
            for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
        else:
            soup = BeautifulSoup(resp.text, "html.parser")
            title_tag = soup.find("title")
            title = title_tag.get_text(strip=True) if title_tag else ""

        # Truncate
        text = text[:config.MAX_TEXT_PER_PAGE] if text else ""
        char_count = len(text)
        console.print(f"[dim]    Fetched {char_count} chars from {url}[/dim]")

        return {"text": text, "title": title, "url": url}

    except requests.exceptions.Timeout:
        return {"error": "Request timed out after 10s", "url": url, "title": ""}
    except requests.exceptions.SSLError as e:
        return {"error": f"SSL error: {e}", "url": url, "title": ""}
    except requests.exceptions.ConnectionError as e:
        return {"error": f"Connection error: {e}", "url": url, "title": ""}
    except Exception as e:
        return {"error": f"Unexpected error: {e}", "url": url, "title": ""}


def tool_extract_and_update(client: anthropic.Anthropic, text: str, source_url: str) -> dict:
    """Use Claude to extract Royal Navy assets from text."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    prompt = f"""You are an OSINT analyst specialising in Royal Navy order of battle.

Extract ALL Royal Navy assets mentioned in the following text. For each asset, identify:
- name: the full name (e.g., "HMS Queen Elizabeth", "HMNB Portsmouth", "45 Commando")
- type: one of ship, submarine, base, air_station, unit, auxiliary
- class: the class/type if mentioned (e.g., "Queen Elizabeth-class", "Type 45", "Astute-class")
- location_description: any location information mentioned (port, sea area, country, exercise name, etc.)
- date_observed: the date this information relates to (YYYY-MM-DD format, estimate from context if not explicit, use {today} if current)

Only include CONFIRMED Royal Navy (not RAF, Army, allied) assets.
If no Royal Navy assets are found, return an empty list.

Source URL: {source_url}

Text to analyse:
---
{text[:3000]}
---

Respond ONLY with valid JSON — a list of asset objects. Example format:
[
  {{
    "name": "HMS Diamond",
    "type": "ship",
    "class": "Type 45 destroyer",
    "location_description": "Portsmouth",
    "date_observed": "2026-03-10"
  }}
]

If no assets found: []"""

    try:
        response = client.messages.create(
            model=config.EXTRACT_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text_out = response.content[0].text.strip()
        start = text_out.find("[")
        end = text_out.rfind("]") + 1
        if start >= 0 and end > start:
            assets_raw = json.loads(text_out[start:end])
            console.print(f"[dim]    Extracted {len(assets_raw)} asset(s) from text[/dim]")
            return {
                "assets": assets_raw,
                "source_url": source_url,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        return {"assets": [], "source_url": source_url}
    except Exception as e:
        console.print(f"[yellow]    Extraction error: {e}[/yellow]")
        return {"assets": [], "source_url": source_url, "error": str(e)}


def tool_resolve_location(client: anthropic.Anthropic, asset_name: str, location_description: str) -> dict:
    """Resolve a location description to coordinates."""
    console.print(f"[cyan]  → Geocoding '{asset_name}': {location_description}[/cyan]")
    result = _resolve_location(client, asset_name, location_description)
    console.print(
        f"[dim]    → lat={result.get('latitude')}, lon={result.get('longitude')}, "
        f"confidence={result.get('confidence_score')}[/dim]"
    )
    return result


def execute_tool(
    client: anthropic.Anthropic,
    tool_name: str,
    tool_input: dict,
    state,  # AgentState
) -> str:
    """Execute a tool and return the result as a JSON string."""
    try:
        if tool_name == "web_search":
            result = tool_web_search(
                tool_input["query"],
                freshness=tool_input.get("freshness", "pm"),
                site=tool_input.get("site"),
            )
            state.searched_queries.append(tool_input["query"])

        elif tool_name == "fetch_page":
            result = tool_fetch_page(tool_input["url"], state.fetched_urls)
            if "error" not in result:
                state.fetched_urls.append(tool_input["url"])

        elif tool_name == "extract_and_update":
            result = tool_extract_and_update(client, tool_input["text"], tool_input["source_url"])

        elif tool_name == "resolve_location":
            result = tool_resolve_location(client, tool_input["asset_name"], tool_input["location_description"])

        elif tool_name == "task_complete":
            state.complete = True
            state.completion_summary = tool_input["summary"]
            result = {"status": "complete", "summary": tool_input["summary"]}

        else:
            result = {"error": f"Unknown tool: {tool_name}"}

        return json.dumps(result)

    except Exception as e:
        console.print(f"[red]    Tool execution error ({tool_name}): {e}[/red]")
        return json.dumps({"error": f"Tool execution failed: {str(e)}"})
