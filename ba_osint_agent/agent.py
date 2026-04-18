"""
British Army OSINT Tracking Agent
==================================
A genuine AI agent that uses the Anthropic API with tool use to dynamically
gather open-source intelligence about British Army units, garrisons, and formations.
"""
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import json
import time
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import anthropic
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

import config
from models import AgentState, ArmyAsset
from tools import TOOL_SCHEMAS, execute_tool
from geocoding import resolve_location

console = Console()

SYSTEM_PROMPT = """You are an OSINT analyst specialising in British Army order of battle and unit dispositions.

Your GOAL is to identify British Army units (regiments, battalions, brigades, garrisons, formations) and their current or most recently reported locations from publicly available open sources.

STRATEGY:
1. Search for recent British Army news, exercises, deployments, and homecomings
2. Fetch promising pages and extract unit information using the extract_and_update tool
3. For every unit discovered, immediately call resolve_location — even if the location description is vague
4. A location with LOW confidence is better than NO location. Always attempt to geocode.
5. For units with no location description, search specifically for their current garrison or deployment
6. Fixed locations (garrisons, barracks) should be resolved immediately from the name alone
7. Keep searching until all known units have at least an approximate location

UNIT SEARCH GUIDANCE:
- Search for units one at a time with narrow, focused queries: '"1st Battalion Royal Welsh" location' not '"Royal Welsh" OR "Royal Anglian" OR "Light Dragoons" 2026'
- For each unit found without a location, search specifically: '"1 LANCS" garrison 2026'
- Named operations (Op Cabrit, Op Interflex, Op Newcombe) are good location indicators
- Homecoming parades are excellent location confirmations
- Rotate through regiment/battalion names one at a time

LOCATION PRIORITY RULES:
- Units at named garrisons (Aldershot, Catterick, Tidworth, Colchester, Bulford): use fixed garrison coordinates
- Units "at Tapa" or "Op Cabrit": Estonia coordinates
- Units "in Kenya" or "BATUK": Kenya coordinates
- Units "at BATUS" or "Suffield": Canada coordinates
- Units "in Estonia", "in Poland", or NATO eFP: use the NATO deployment area
- Only leave coordinates null if there is truly no location information at all

CONSTRAINTS:
- Only use publicly available information
- Note when information is dated or uncertain
- Never fabricate data — use low confidence scores to flag uncertainty
- Decide your NEXT ACTION based on what gaps remain in your knowledge
- Do not follow a fixed sequence — adapt dynamically to what you find

SEARCH BEST PRACTICES:
- Keep queries NARROW: '"1 SCOTS" Catterick 2026' beats '"1 SCOTS" exercise deployment operations training base 2026'.
- Fan out: run many focused queries and deduplicate rather than one clever compound query.
- Use the site parameter for authoritative sources — scope the same query to each seed domain in turn.
- Search results give only titles, URLs and snippets. When a result looks relevant, call fetch_page to read the full article before reasoning over it.
- Freshness defaults to past month ('pm'). Use 'py' only for historical context.

TERMINATION: Call task_complete when you have reached the target number of units with resolved locations, or when no further productive searches are possible.

TODAY'S DATE: """ + datetime.now(timezone.utc).strftime("%Y-%m-%d")


class TokenTracker:
    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0

    def add(self, usage):
        if hasattr(usage, "input_tokens"):
            self.input_tokens += usage.input_tokens
            self.output_tokens += usage.output_tokens

    def summary(self) -> str:
        return f"Tokens used: {self.input_tokens:,} input / {self.output_tokens:,} output"


def build_state_context(state: AgentState) -> str:
    lines = [
        f"=== CURRENT STATE (Iteration {state.iteration}) ===",
        state.summary(),
        "",
    ]

    if state.assets_with_locations():
        lines.append("UNITS WITH LOCATIONS:")
        for a in state.assets_with_locations():
            lines.append(
                f"  ✓ {a.name} ({a.type}) — {a.location_description} "
                f"[{a.latitude:.2f}, {a.longitude:.2f}] conf={a.confidence_score:.2f}"
            )
        lines.append("")

    if state.assets_without_locations():
        lines.append("UNITS MISSING LOCATIONS (PRIORITY — find their locations):")
        for a in state.assets_without_locations():
            lines.append(f"  ✗ {a.name} ({a.type}) — {a.location_description or 'no location info'}")
        lines.append("")

    if state.searched_queries:
        lines.append(f"SEARCHES ALREADY RUN: {', '.join(repr(q) for q in state.searched_queries[-5:])}")

    if state.fetched_urls:
        lines.append(f"URLS ALREADY FETCHED ({len(state.fetched_urls)} total, last 3):")
        for url in state.fetched_urls[-3:]:
            lines.append(f"  {url}")

    lines.append("")
    lines.append(
        f"TARGET: {config.TARGET_ASSETS_WITH_LOCATIONS} units with locations "
        f"(currently have {len(state.assets_with_locations())})"
    )

    return "\n".join(lines)


def parse_tool_results_and_update_state(
    client: anthropic.Anthropic,
    tool_results: list,
    state: AgentState,
    tokens: TokenTracker,
):
    for result_json, tool_name, tool_input in tool_results:
        try:
            result = json.loads(result_json)
        except json.JSONDecodeError:
            continue

        if tool_name == "extract_and_update" and "assets" in result:
            for asset_raw in result.get("assets", []):
                try:
                    asset = ArmyAsset(
                        name=asset_raw.get("name", "Unknown"),
                        type=asset_raw.get("type", "regiment"),
                        **{"class": asset_raw.get("class")},
                        location_description=asset_raw.get("location_description"),
                        source_urls=[result.get("source_url", "")],
                        date_observed=asset_raw.get("date_observed"),
                        last_updated=datetime.now(timezone.utc).isoformat() + "Z",
                    )
                    is_new = state.upsert_asset(asset)
                    if is_new:
                        console.print(
                            f"[green]  ★ NEW UNIT: {asset.name} ({asset.type})"
                            f"{' — ' + asset.location_description if asset.location_description else ''}[/green]"
                        )
                    else:
                        console.print(f"[blue]  ↻ Updated: {asset.name}[/blue]")

                    live_asset = state.get_asset_by_name(asset.name)
                    if live_asset and live_asset.location_description and live_asset.latitude is None:
                        console.print(
                            f"[dim]  Auto-geocoding: {live_asset.name} — '{live_asset.location_description}'[/dim]"
                        )
                        try:
                            geo = resolve_location(client, live_asset.name, live_asset.location_description)
                            lat = geo.get("latitude")
                            lon = geo.get("longitude")
                            conf = geo.get("confidence_score", 0.0)
                            if lat is not None and lon is not None:
                                live_asset.latitude = lat
                                live_asset.longitude = lon
                                live_asset.confidence_score = conf
                                live_asset.confidence_rationale = geo.get("resolution_rationale", "")
                                live_asset.last_updated = datetime.now(timezone.utc).isoformat() + "Z"
                                console.print(
                                    f"[green]  📍 Auto-located: {live_asset.name} → [{lat:.2f}, {lon:.2f}] "
                                    f"(conf={conf:.2f})[/green]"
                                )
                        except Exception as geo_err:
                            console.print(f"[yellow]  Auto-geocode error for {live_asset.name}: {geo_err}[/yellow]")

                except Exception as e:
                    console.print(f"[yellow]  Unit parse error: {e} — {asset_raw}[/yellow]")

            tokens.input_tokens += result.get("input_tokens", 0)
            tokens.output_tokens += result.get("output_tokens", 0)

        elif tool_name == "resolve_location":
            asset_name = tool_input.get("asset_name", "")
            lat = result.get("latitude")
            lon = result.get("longitude")
            conf = result.get("confidence_score", 0.0)
            rationale = result.get("resolution_rationale", "")

            if lat is not None and lon is not None:
                asset = state.get_asset_by_name(asset_name)
                if asset:
                    existing_conf = asset.confidence_score or 0.0
                    if asset.latitude is None or conf > existing_conf:
                        asset.latitude = lat
                        asset.longitude = lon
                        asset.confidence_score = conf
                        asset.confidence_rationale = rationale
                        asset.last_updated = datetime.now(timezone.utc).isoformat() + "Z"
                        console.print(
                            f"[green]  📍 Located: {asset_name} → [{lat:.2f}, {lon:.2f}] "
                            f"(conf={conf:.2f})[/green]"
                        )
                else:
                    console.print(
                        f"[yellow]  resolve_location: unit '{asset_name}' not found in state[/yellow]"
                    )

    # Sweep: auto-geocode any units that have a description but still no coords
    for asset in state.assets_without_locations():
        if asset.location_description:
            console.print(
                f"[dim]  Sweep-geocoding: {asset.name} — '{asset.location_description}'[/dim]"
            )
            try:
                geo = resolve_location(client, asset.name, asset.location_description)
                lat = geo.get("latitude")
                lon = geo.get("longitude")
                conf = geo.get("confidence_score", 0.0)
                if lat is not None and lon is not None:
                    asset.latitude = lat
                    asset.longitude = lon
                    asset.confidence_score = conf
                    asset.confidence_rationale = geo.get("resolution_rationale", "")
                    asset.last_updated = datetime.now(timezone.utc).isoformat() + "Z"
                    console.print(
                        f"[green]  📍 Sweep-located: {asset.name} → [{lat:.2f}, {lon:.2f}] "
                        f"(conf={conf:.2f})[/green]"
                    )
            except Exception as geo_err:
                console.print(f"[yellow]  Sweep-geocode error for {asset.name}: {geo_err}[/yellow]")


def run_agent():
    """Main agent loop."""
    console.print(Panel.fit(
        "[bold green]British Army OSINT Tracking Agent[/bold green]\n"
        "[dim]Using Anthropic API with tool use[/dim]",
        border_style="green",
    ))

    if not config.ANTHROPIC_API_KEY:
        console.print("[red]ERROR: ANTHROPIC_API_KEY not set. Export it and retry.[/red]")
        sys.exit(1)
    if not config.BRAVE_SEARCH_API_KEY:
        console.print("[red]ERROR: BRAVE_SEARCH_API_KEY not set. Export it and retry.[/red]")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    state = AgentState()
    tokens = TokenTracker()
    messages = []

    initial_message = (
        "You are starting a British Army OSINT collection mission.\n\n"
        + build_state_context(state)
        + "\n\nBegin by searching for recent British Army news, exercises, and deployments. "
        "Search for units one at a time with narrow, focused queries. "
        "Use the seed search terms and URLs as starting points.\n\n"
        "Seed URLs to consider: " + ", ".join(config.SEED_URLS) + "\n"
        "Seed search terms to consider: " + "; ".join(config.SEED_SEARCH_TERMS)
    )
    messages.append({"role": "user", "content": initial_message})

    console.print(f"\n[bold]Starting agent loop (max {config.MAX_ITERATIONS} iterations)[/bold]\n")

    for iteration in range(1, config.MAX_ITERATIONS + 1):
        state.iteration = iteration

        console.print(f"\n{'━' * 60}")
        console.print(
            f"[bold yellow]ITERATION {iteration}/{config.MAX_ITERATIONS}[/bold yellow] | "
            + state.summary()
        )
        console.print(f"{'━' * 60}")

        if len(state.assets_with_locations()) >= config.TARGET_ASSETS_WITH_LOCATIONS:
            console.print(
                f"[green bold]✓ Target reached: {len(state.assets_with_locations())} units with locations![/green bold]"
            )
            state.complete = True
            state.completion_summary = f"Reached target of {config.TARGET_ASSETS_WITH_LOCATIONS} units with locations."
            break

        if iteration > 1:
            messages.append({
                "role": "user",
                "content": (
                    "Continue the intelligence gathering.\n\n"
                    + build_state_context(state)
                    + "\n\nDecide your next action based on the gaps above. "
                    "If units are missing locations, prioritise finding them. "
                    "Avoid repeating searches you've already run."
                ),
            })

        console.print("[dim]Calling LLM...[/dim]")
        try:
            response = _call_with_retry(client, messages)
        except Exception as e:
            console.print(f"[red]LLM call failed after retries: {e}[/red]")
            break

        tokens.add(response.usage)
        console.print(
            f"[dim]LLM response: stop_reason={response.stop_reason} | "
            f"blocks={len(response.content)}[/dim]"
        )

        text_blocks = [b for b in response.content if b.type == "text"]
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        if text_blocks:
            thinking = text_blocks[0].text[:300]
            console.print(f"\n[italic dim]Agent reasoning: {thinking}{'...' if len(text_blocks[0].text) > 300 else ''}[/italic dim]")

        messages.append({"role": "assistant", "content": response.content})

        if not tool_use_blocks:
            console.print("[yellow]No tool calls made — agent may be done or confused.[/yellow]")
            if response.stop_reason == "end_turn":
                console.print("[yellow]Agent declared end_turn without task_complete.[/yellow]")
            break

        tool_results_for_update = []
        tool_result_messages = []

        for tool_use in tool_use_blocks:
            tool_name = tool_use.name
            tool_input = tool_use.input
            tool_use_id = tool_use.id

            console.print(
                f"\n[bold cyan]▶ Tool call: {tool_name}[/bold cyan] "
                f"[dim]{json.dumps(tool_input)[:150]}[/dim]"
            )

            result_json = execute_tool(client, tool_name, tool_input, state)
            tool_results_for_update.append((result_json, tool_name, tool_input))

            try:
                result_preview = json.loads(result_json)
                if "results" in result_preview:
                    console.print(f"[dim]  Result: {len(result_preview['results'])} search results[/dim]")
                elif "text" in result_preview:
                    console.print(f"[dim]  Result: {len(result_preview['text'])} chars fetched[/dim]")
                elif "error" in result_preview:
                    console.print(f"[yellow]  Result: ERROR — {result_preview['error']}[/yellow]")
            except Exception:
                pass

            tool_result_messages.append({
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": result_json,
            })

        messages.append({"role": "user", "content": tool_result_messages})
        parse_tool_results_and_update_state(client, tool_results_for_update, state, tokens)

        if state.complete:
            console.print(f"\n[green bold]✓ Agent declared task complete: {state.completion_summary}[/green bold]")
            break

        time.sleep(0.5)

    # ─── Output results ────────────────────────────────────────────────────────
    console.print(f"\n{'═' * 60}")
    console.print("[bold green]AGENT RUN COMPLETE[/bold green]")
    console.print(f"{'═' * 60}\n")

    output_data = [a.to_output_dict() for a in state.assets]

    table = Table(title="Discovered British Army Units", show_header=True, header_style="bold magenta")
    table.add_column("Unit", style="bold", max_width=35)
    table.add_column("Type", max_width=15)
    table.add_column("Location", max_width=30)
    table.add_column("Confidence", justify="right", max_width=10)

    for asset in state.assets:
        conf_str = f"{asset.confidence_score:.2f}" if asset.confidence_score is not None else "—"
        loc_str = asset.location_description or "UNKNOWN"
        conf_style = "green" if (asset.confidence_score or 0) >= 0.7 else "yellow"
        table.add_row(
            asset.name,
            asset.type,
            loc_str[:30],
            Text(conf_str, style=conf_style),
        )

    console.print(table)
    console.print(f"\n[bold]{tokens.summary()}[/bold]")
    console.print(f"Iterations used: {state.iteration}")
    console.print(f"Units with locations: {len(state.assets_with_locations())} / {len(state.assets)}")

    console.print("\n[bold]=== FULL JSON OUTPUT ===[/bold]")
    json_output = json.dumps(output_data, indent=2)
    console.print(json_output)

    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"ba_assets_{timestamp}.json"
    output_path.write_text(json_output)
    console.print(f"\n[green]Saved to: {output_path}[/green]")

    return output_data


def _call_with_retry(client: anthropic.Anthropic, messages: list, max_retries: int = 3) -> anthropic.types.Message:
    import random
    last_exc = None
    for attempt in range(max_retries):
        try:
            return client.messages.create(
                model=config.MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOL_SCHEMAS,
                messages=messages,
            )
        except anthropic.RateLimitError as e:
            last_exc = e
            delay = min(2 ** attempt + random.uniform(0, 1), 60)
            console.print(f"[yellow]Rate limited. Retry {attempt + 1}/{max_retries} in {delay:.1f}s[/yellow]")
            time.sleep(delay)
        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                last_exc = e
                delay = min(2 ** attempt + random.uniform(0, 1), 60)
                console.print(f"[yellow]Server error {e.status_code}. Retry {attempt + 1}/{max_retries} in {delay:.1f}s[/yellow]")
                time.sleep(delay)
            else:
                raise
    raise last_exc


if __name__ == "__main__":
    run_agent()
