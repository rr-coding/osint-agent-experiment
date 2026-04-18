"""Tool definitions and implementations for the RAF Analyst Agent."""
import json
import requests
from typing import List
from datetime import datetime, timezone

import anthropic
from bs4 import BeautifulSoup
from rich.console import Console

import config

console = Console()

TOOL_SCHEMAS = [
    {
        "name": "web_search",
        "description": "Search the web for information about a RAF unit's current status or deployment.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "The search query"}},
            "required": ["query"],
        },
    },
    {
        "name": "fetch_page",
        "description": "Fetch and extract readable text from a URL.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "URL to fetch"}},
            "required": ["url"],
        },
    },
    {
        "name": "generate_operation_types",
        "description": (
            "Generate the master list of operation types relevant to this RAF dataset. "
            "Call this ONCE at the start."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "assets_summary": {"type": "string", "description": "Summary of all units"}
            },
            "required": ["assets_summary"],
        },
    },
    {
        "name": "assess_asset",
        "description": "Assess a single RAF unit and return full enrichment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "asset_name": {"type": "string"},
                "asset_class": {"type": "string"},
                "asset_type": {"type": "string"},
                "location_description": {"type": "string"},
                "gathered_context": {"type": "string"},
                "operation_types": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["asset_name", "gathered_context", "operation_types"],
        },
    },
    {
        "name": "task_complete",
        "description": "Signal that all units have been assessed.",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    },
]


def tool_web_search(query: str, searched_queries: list) -> dict:
    console.print(f"[cyan]  → Searching: '{query}'[/cyan]")
    if config.BRAVE_SEARCH_API_KEY:
        try:
            resp = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": 8},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": config.BRAVE_SEARCH_API_KEY,
                },
                timeout=config.REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            results = [
                {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("description", "")}
                for r in data.get("web", {}).get("results", [])
            ]
            console.print(f"[dim]    Brave: {len(results)} results[/dim]")
            searched_queries.append(query)
            return {"results": results, "query": query}
        except Exception as e:
            console.print(f"[yellow]    Brave failed: {e}[/yellow]")
    searched_queries.append(query)
    return {"results": [], "query": query, "error": "Search unavailable"}


def tool_fetch_page(url: str, fetched_urls: list) -> dict:
    if url in fetched_urls:
        return {"error": f"Already fetched: {url}", "url": url}
    console.print(f"[cyan]  → Fetching: {url}[/cyan]")
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
            timeout=config.REQUEST_TIMEOUT,
        )
        if resp.status_code in (403, 401):
            return {"error": f"HTTP {resp.status_code} — access denied", "url": url, "title": ""}
        if resp.status_code == 404:
            return {"error": "404 Not Found", "url": url, "title": ""}
        resp.raise_for_status()

        text = None
        try:
            import trafilatura
            text = trafilatura.extract(resp.text, include_comments=False, include_tables=False)
        except Exception:
            pass

        soup = BeautifulSoup(resp.text, "html.parser")
        title = (soup.find("title") or soup.new_tag("t")).get_text(strip=True)
        if not text:
            for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)

        text = (text or "")[:config.MAX_TEXT_PER_PAGE]
        fetched_urls.append(url)
        console.print(f"[dim]    Fetched {len(text)} chars[/dim]")
        return {"text": text, "title": title, "url": url}
    except requests.exceptions.Timeout:
        return {"error": "Timed out", "url": url, "title": ""}
    except Exception as e:
        return {"error": str(e), "url": url, "title": ""}


def tool_generate_operation_types(client: anthropic.Anthropic, assets_summary: str) -> dict:
    prompt = f"""You are a Royal Air Force intelligence analyst. Examine the following list of RAF units and generate up to {config.MAX_OPERATION_TYPES} operation types that are relevant and meaningful for THIS specific set of units.

Units in the dataset:
{assets_summary}

Guidance: For the RAF, relevant operation categories include air policing and QRA, air superiority, close air support, strategic lift, air-to-air refuelling, ISR (intelligence surveillance reconnaissance), combat search and rescue, strategic bombing, humanitarian airlift, and training. Generate only the types that are genuinely applicable to the units present.

Rules:
- Only include operation types applicable to at least some units in the list
- Each operation type should be meaningfully distinct
- Use snake_case for IDs
- Up to {config.MAX_OPERATION_TYPES} types

Return ONLY valid JSON — a list of objects with "id", "name", "description":
[
  {{
    "id": "air_policing",
    "name": "Air Policing / QRA",
    "description": "Quick Reaction Alert scrambles to identify and intercept unknown aircraft in UK airspace"
  }}
]"""
    try:
        response = client.messages.create(
            model=config.ASSESS_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        start, end = text.find("["), text.rfind("]") + 1
        if start >= 0 and end > start:
            op_types = json.loads(text[start:end])
            return {
                "operation_types": op_types,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        return {"operation_types": [], "error": "Could not parse response"}
    except Exception as e:
        return {"operation_types": [], "error": str(e)}


def tool_assess_asset(
    client: anthropic.Anthropic,
    asset_name: str,
    asset_class: str,
    asset_type: str,
    location_description: str,
    gathered_context: str,
    operation_types: List[str],
) -> dict:
    op_types_str = ", ".join(operation_types)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    prompt = f"""You are a Royal Air Force intelligence analyst. Assess the following RAF unit and return a structured JSON enrichment.

Unit: {asset_name}
Aircraft/Class: {asset_class or 'Unknown'}
Type: {asset_type or 'Unknown'}
Last known location: {location_description or 'Unknown'}
Today's date: {today}

Gathered intelligence context:
---
{gathered_context[:3500] if gathered_context else 'No specific intelligence gathered. Use general knowledge about this unit type and aircraft.'}
---

Operation types to score: {op_types_str}

Return ONLY valid JSON with these exact fields:
{{
  "unit_category": "<descriptive category, e.g. 'Fighter/Bomber', 'Air Superiority', 'Strategic Lift', 'Tanker', 'ISR', 'Maritime Patrol', 'Rotary Wing', 'Training', 'Ground-Based Air Defence', 'Headquarters', etc.>",
  "operational_readiness": "<high, medium, or low>",
  "readiness_rationale": "<explain your reasoning, cite evidence or note when inferring>",
  "current_assignment": "<current operation/exercise/station, or 'No current assignment identified'>",
  "assignment_source": "<URL if available, otherwise null>",
  "capability_scores": {{
    "<operation_type_id>": <integer 0-5>,
    ...
  }},
  "capability_rationale": "<explain key factors in the scoring>",
  "aircraft_type": "<primary aircraft type if known, otherwise null>",
  "parent_wing": "<parent wing if known, otherwise null>",
  "squadron_number": "<squadron number if applicable, otherwise null>"
}}

Scoring guide: 0=not applicable, 1=minimal, 2=limited, 3=moderate, 4=strong, 5=primary role/optimised."""

    try:
        response = client.messages.create(
            model=config.ASSESS_MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        start, end = text.find("{"), text.rfind("}") + 1
        if start >= 0 and end > start:
            result = json.loads(text[start:end])
            result["input_tokens"] = response.usage.input_tokens
            result["output_tokens"] = response.usage.output_tokens
            return result
        return {"error": "Could not parse assessment response", "raw": text[:300]}
    except Exception as e:
        return {"error": str(e)}


def execute_tool(client: anthropic.Anthropic, tool_name: str, tool_input: dict, state: dict) -> str:
    try:
        if tool_name == "web_search":
            result = tool_web_search(tool_input["query"], state["searched_queries"])
        elif tool_name == "fetch_page":
            result = tool_fetch_page(tool_input["url"], state["fetched_urls"])
        elif tool_name == "generate_operation_types":
            result = tool_generate_operation_types(client, tool_input["assets_summary"])
            state["extra_tokens"]["input"] += result.get("input_tokens", 0)
            state["extra_tokens"]["output"] += result.get("output_tokens", 0)
        elif tool_name == "assess_asset":
            result = tool_assess_asset(
                client,
                asset_name=tool_input.get("asset_name", ""),
                asset_class=tool_input.get("asset_class", ""),
                asset_type=tool_input.get("asset_type", ""),
                location_description=tool_input.get("location_description", ""),
                gathered_context=tool_input.get("gathered_context", ""),
                operation_types=tool_input.get("operation_types", []),
            )
            state["extra_tokens"]["input"] += result.get("input_tokens", 0)
            state["extra_tokens"]["output"] += result.get("output_tokens", 0)
        elif tool_name == "task_complete":
            state["complete"] = True
            state["completion_summary"] = tool_input.get("summary", "")
            result = {"status": "complete", "summary": state["completion_summary"]}
        else:
            result = {"error": f"Unknown tool: {tool_name}"}
        return json.dumps(result)
    except Exception as e:
        console.print(f"[red]  Tool error ({tool_name}): {e}[/red]")
        return json.dumps({"error": str(e)})
