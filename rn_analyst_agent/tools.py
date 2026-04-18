"""Tool definitions and implementations for the RN Analyst Agent."""
import json
import requests
from typing import List
from datetime import datetime, timezone

import anthropic
from bs4 import BeautifulSoup
from rich.console import Console

import config

console = Console()

# ─── Tool schemas ──────────────────────────────────────────────────────────────

TOOL_SCHEMAS = [
    {
        "name": "web_search",
        "description": (
            "Search the web for information about a Royal Navy asset's current status, "
            "deployment, maintenance, or assignment. Use targeted queries like "
            "'HMS Diamond refit 2026' or 'HMS Anson Australia AUKUS'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_page",
        "description": (
            "Fetch and extract readable text from a URL. Use to read news articles or "
            "official announcements about Royal Navy assets found in search results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"}
            },
            "required": ["url"],
        },
    },
    {
        "name": "generate_operation_types",
        "description": (
            "Generate the master list of operation types relevant to this specific dataset. "
            "Call this ONCE at the start, passing a summary of all assets. "
            "Returns up to 10 operation type objects with id, name, and description."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "assets_summary": {
                    "type": "string",
                    "description": "A summary of all assets in the dataset: names, types, and classes",
                }
            },
            "required": ["assets_summary"],
        },
    },
    {
        "name": "assess_asset",
        "description": (
            "Assess a single Royal Navy asset and return the full enrichment: "
            "operational readiness, current assignment, unit category, capability scores, "
            "and rationales. Provide all gathered context from web searches."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "asset_name": {"type": "string", "description": "Full name of the asset"},
                "asset_class": {"type": "string", "description": "Class of the asset, if known"},
                "asset_type": {"type": "string", "description": "Type from OSINT data (ship, submarine, base, etc.)"},
                "location_description": {"type": "string", "description": "Last known location"},
                "gathered_context": {
                    "type": "string",
                    "description": "Concatenated relevant text from web searches about this asset",
                },
                "operation_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "The master list of operation type IDs to score against",
                },
            },
            "required": ["asset_name", "gathered_context", "operation_types"],
        },
    },
    {
        "name": "task_complete",
        "description": "Signal that all assets have been assessed and the task is complete.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Brief summary of what was accomplished"}
            },
            "required": ["summary"],
        },
    },
]


# ─── Tool implementations ──────────────────────────────────────────────────────

def tool_web_search(query: str, searched_queries: list) -> dict:
    console.print(f"[cyan]  → Searching: '{query}'[/cyan]")
    if config.BRAVE_SEARCH_API_KEY:
        result = _brave_search(query)
    else:
        result = _duckduckgo_search(query)
    searched_queries.append(query)
    return result


def _brave_search(query: str) -> dict:
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
        return {"results": results, "query": query}
    except Exception as e:
        console.print(f"[yellow]    Brave failed: {e} — falling back[/yellow]")
        return _duckduckgo_search(query)


def _duckduckgo_search(query: str) -> dict:
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for r in soup.select(".result")[:8]:
            title_el = r.select_one(".result__title a")
            snippet_el = r.select_one(".result__snippet")
            if title_el:
                href = title_el.get("href", "")
                if "uddg=" in href:
                    import urllib.parse
                    href = urllib.parse.unquote(href.split("uddg=")[1].split("&")[0])
                results.append({
                    "title": title_el.get_text(strip=True),
                    "url": href,
                    "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                })
        console.print(f"[dim]    DuckDuckGo: {len(results)} results[/dim]")
        return {"results": results, "query": query}
    except Exception as e:
        return {"results": [], "query": query, "error": str(e)}


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
    """LLM-powered: generate tailored operation type taxonomy for this dataset."""
    prompt = f"""You are a naval analyst. Examine the following list of Royal Navy assets and generate up to {config.MAX_OPERATION_TYPES} operation types that are relevant and meaningful for THIS specific set of assets.

Assets in the dataset:
{assets_summary}

Rules:
- Only include operation types that are genuinely applicable to at least some assets in the list
- Do not include "nuclear deterrent" unless there are ballistic missile submarines (SSBNs) present
- Do not include "carrier strike" unless there is an aircraft carrier or strike-capable ship present
- Each operation type should be meaningfully distinct
- Use snake_case for IDs

Return ONLY valid JSON — a list of objects with "id", "name", "description":
[
  {{
    "id": "air_defence",
    "name": "Air Defence",
    "description": "Protecting the fleet and shore from air and missile threats using organic sensors and weapons"
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
    """LLM-powered: produce full analytical enrichment for a single asset."""
    op_types_str = ", ".join(operation_types)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    prompt = f"""You are a naval intelligence analyst. Assess the following Royal Navy asset and return a structured JSON enrichment.

Asset: {asset_name}
Class: {asset_class or 'Unknown'}
Type: {asset_type or 'Unknown'}
Last known location: {location_description or 'Unknown'}
Today's date: {today}

Gathered intelligence context:
---
{gathered_context[:3500] if gathered_context else 'No specific intelligence gathered. Use general class knowledge.'}
---

Operation types to score: {op_types_str}

Return ONLY valid JSON with these exact fields:
{{
  "unit_category": "<one of: aircraft_carrier, destroyer, frigate, submarine_fleet, submarine_strategic, amphibious_assault, patrol_vessel, mine_countermeasures, auxiliary, naval_base, air_station, training_unit, other>",
  "operational_readiness": "<high, medium, or low>",
  "readiness_rationale": "<explain your reasoning, cite evidence from context or note when inferring>",
  "current_assignment": "<what it is currently doing, or 'No current assignment identified'>",
  "assignment_source": "<URL if you have one, otherwise null>",
  "capability_scores": {{
    "<operation_type_id>": <integer 0-5>,
    ...
  }},
  "capability_rationale": "<explain key factors in the scoring, referencing class systems and known roles>"
}}

Scoring guide: 0=not applicable, 1=minimal, 2=limited, 3=moderate, 4=strong, 5=primary role/optimised.
Be honest: if readiness is uncertain due to limited information, say so in the rationale and default to medium."""

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


def execute_tool(
    client: anthropic.Anthropic,
    tool_name: str,
    tool_input: dict,
    state: dict,
) -> str:
    """Dispatch a tool call and return the result as a JSON string."""
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
