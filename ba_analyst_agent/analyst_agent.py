"""
British Army Analyst Agent
==========================
Takes the JSON output from the BA OSINT tracking agent and enriches each unit
with operational readiness, current assignment, unit category, and capability scores.

Usage:
    python analyst_agent.py path/to/ba_assets_TIMESTAMP.json
"""
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import json
import sys
import time
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import anthropic
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

import config
from models import EnrichedAsset, OperationType, AnalystOutput
from tools import TOOL_SCHEMAS, execute_tool

console = Console()

SYSTEM_PROMPT = """You are a British Army intelligence analyst assessing the current order of battle. You have been given a dataset of British Army units with their names, types, and last known locations.

Your task is to enrich this dataset with analytical assessments. For each unit, determine its operational readiness, current assignment, precise unit category, and its capability to support different types of land operations.

Use web search tools to find current information about each unit's status — exercises, recent deployments, homecomings, and operational assignments. For general knowledge about unit capabilities and established regimental roles, use your training knowledge.

Be honest about uncertainty. If you cannot determine a unit's current assignment, say so. Do not fabricate deployments.

Think about the units as a force. When you research one unit and discover information about others in the same brigade or garrison, use that information across multiple assessments.

Process units efficiently. You do not need a separate search for every unit — if multiple units are at the same garrison, one search may cover all of them.

TODAY'S DATE: """ + datetime.now(timezone.utc).strftime("%Y-%m-%d")


class TokenTracker:
    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0

    def add(self, usage):
        if usage:
            self.input_tokens += getattr(usage, "input_tokens", 0)
            self.output_tokens += getattr(usage, "output_tokens", 0)

    def add_extra(self, extra: dict):
        self.input_tokens += extra.get("input", 0)
        self.output_tokens += extra.get("output", 0)

    def total(self):
        return self.input_tokens + self.output_tokens

    def summary(self):
        return f"Tokens: {self.input_tokens:,} input / {self.output_tokens:,} output / {self.total():,} total"


def load_input(path: str) -> List[dict]:
    p = Path(path)
    if not p.exists():
        console.print(f"[red]ERROR: File not found: {path}[/red]")
        sys.exit(1)
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        console.print(f"[red]ERROR: Malformed JSON in {path}: {e}[/red]")
        sys.exit(1)
    if not isinstance(data, list):
        console.print(f"[red]ERROR: Expected a JSON array, got {type(data).__name__}[/red]")
        sys.exit(1)
    if not data:
        console.print("[red]ERROR: Input file contains no units.[/red]")
        sys.exit(1)
    return data


def build_assets_summary(raw_assets: List[dict]) -> str:
    lines = [f"Total units: {len(raw_assets)}\n"]
    for a in raw_assets:
        cls = a.get("class") or "type unknown"
        lines.append(f"- {a.get('name', 'Unknown')} ({a.get('type', 'unknown')}, {cls})")
    return "\n".join(lines)


def build_iteration_context(
    enriched: List[EnrichedAsset],
    raw_assets: List[dict],
    operation_types: List[OperationType],
    iteration: int,
) -> str:
    total = len(raw_assets)
    done = sum(1 for a in enriched if a.is_enriched())
    remaining = [a for a in raw_assets if not any(
        e.name.lower() == a.get("name", "").lower() and e.is_enriched()
        for e in enriched
    )]

    lines = [
        f"=== ANALYST STATE (Iteration {iteration}) ===",
        f"Units enriched: {done} / {total} | Remaining: {len(remaining)}",
        "",
    ]

    if operation_types:
        lines.append(f"Operation types ({len(operation_types)}): "
                     + ", ".join(ot.id for ot in operation_types))
        lines.append("")

    if done > 0:
        lines.append("COMPLETED UNITS:")
        for a in enriched:
            if a.is_enriched():
                lines.append(
                    f"  ✓ {a.name} — readiness={a.operational_readiness}, "
                    f"category={a.unit_category}"
                )
        lines.append("")

    if remaining:
        lines.append("UNITS STILL NEEDING ASSESSMENT:")
        for a in remaining:
            cls = a.get("class") or "type unknown"
            loc = a.get("location_description") or "location unknown"
            lines.append(f"  ✗ {a.get('name')} ({a.get('type')}, {cls}) — {loc}")
        lines.append("")
        lines.append(
            "For each remaining unit: search for current status if needed, "
            "then call assess_asset. When done with all units, call task_complete."
        )

    return "\n".join(lines)


def apply_assessment(enriched: List[EnrichedAsset], asset_name: str, assessment: dict):
    asset = next((a for a in enriched if a.name.lower() == asset_name.lower()), None)
    if not asset:
        console.print(f"[yellow]  assess_asset: '{asset_name}' not found[/yellow]")
        return

    asset.unit_category = assessment.get("unit_category") or asset.unit_category
    asset.operational_readiness = assessment.get("operational_readiness") or asset.operational_readiness
    asset.readiness_rationale = assessment.get("readiness_rationale")
    asset.current_assignment = assessment.get("current_assignment")
    asset.assignment_source = assessment.get("assignment_source")
    asset.capability_scores = assessment.get("capability_scores", {})
    asset.capability_rationale = assessment.get("capability_rationale")
    asset.parent_brigade = assessment.get("parent_brigade")
    asset.regimental_identity = assessment.get("regimental_identity")
    asset.vehicle_fleet = assessment.get("vehicle_fleet")
    asset.last_updated = datetime.now(timezone.utc).isoformat() + "Z"

    console.print(
        f"[green]  ✓ Assessed: {asset.name} — "
        f"readiness=[bold]{asset.operational_readiness}[/bold], "
        f"category={asset.unit_category}[/green]"
    )


def apply_operation_types(raw_list: list, operation_types: List[OperationType]) -> List[OperationType]:
    result = []
    console.print("\n[bold magenta]Generated Operation Types:[/bold magenta]")
    for item in raw_list:
        try:
            ot = OperationType(
                id=item["id"],
                name=item["name"],
                description=item.get("description", ""),
            )
            result.append(ot)
            console.print(f"  [magenta]• {ot.name}[/magenta] — {ot.description[:80]}")
        except Exception as e:
            console.print(f"[yellow]  Could not parse operation type {item}: {e}[/yellow]")
    return result


def call_with_retry(client: anthropic.Anthropic, messages: list, max_retries: int = 3):
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
        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                last_exc = e
            else:
                raise
        delay = min(2 ** attempt + random.uniform(0, 1), 60)
        console.print(f"[yellow]  API error, retry {attempt+1}/{max_retries} in {delay:.1f}s[/yellow]")
        time.sleep(delay)
    raise last_exc


def run_analyst(input_path: str):
    console.print(Panel.fit(
        "[bold green]British Army Analyst Agent[/bold green]\n"
        "[dim]Enriching OSINT data with operational assessments[/dim]",
        border_style="green",
    ))

    if not config.ANTHROPIC_API_KEY:
        console.print("[red]ERROR: ANTHROPIC_API_KEY not set.[/red]")
        sys.exit(1)

    raw_assets = load_input(input_path)
    console.print(f"[green]Loaded {len(raw_assets)} units from {input_path}[/green]\n")

    enriched: List[EnrichedAsset] = []
    for raw in raw_assets:
        try:
            asset = EnrichedAsset(
                name=raw.get("name", "Unknown"),
                service=raw.get("service", "british_army"),
                type=raw.get("type", "regiment"),
                **{"class": raw.get("class")},
                location_description=raw.get("location_description"),
                latitude=raw.get("latitude"),
                longitude=raw.get("longitude"),
                confidence_score=raw.get("confidence_score"),
                confidence_rationale=raw.get("confidence_rationale"),
                source_urls=raw.get("source_urls", []),
                date_observed=raw.get("date_observed"),
                last_updated=raw.get("last_updated"),
            )
            enriched.append(asset)
        except Exception as e:
            console.print(f"[yellow]Warning: could not parse unit {raw.get('name')}: {e}[/yellow]")

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    tokens = TokenTracker()
    operation_types: List[OperationType] = []

    state = {
        "searched_queries": [],
        "fetched_urls": [],
        "complete": False,
        "completion_summary": "",
        "extra_tokens": {"input": 0, "output": 0},
    }

    messages = []
    assets_summary = build_assets_summary(raw_assets)
    initial_msg = (
        "You are starting a British Army analytical assessment.\n\n"
        f"{assets_summary}\n\n"
        "Step 1: Call generate_operation_types with the units summary above.\n"
        "Step 2: Research and assess each unit — search for current status where needed, "
        "then call assess_asset for each one.\n"
        "Step 3: When all units are assessed, call task_complete."
    )
    messages.append({"role": "user", "content": initial_msg})

    console.print(f"[bold]Starting analyst loop (max {config.MAX_ITERATIONS} iterations)[/bold]\n")

    for iteration in range(1, config.MAX_ITERATIONS + 1):
        enriched_count = sum(1 for a in enriched if a.is_enriched())

        console.print(f"\n{'━' * 60}")
        console.print(
            f"[bold yellow]ITERATION {iteration}/{config.MAX_ITERATIONS}[/bold yellow] | "
            f"Enriched: {enriched_count}/{len(enriched)} | "
            f"{tokens.summary()}"
        )
        console.print(f"{'━' * 60}")

        if state["complete"]:
            break
        if enriched_count == len(enriched):
            console.print("[green bold]All units enriched — calling complete.[/green bold]")
            break

        if iteration > 1:
            messages.append({
                "role": "user",
                "content": build_iteration_context(enriched, raw_assets, operation_types, iteration),
            })

        console.print("[dim]Calling LLM...[/dim]")
        try:
            response = call_with_retry(client, messages)
        except Exception as e:
            console.print(f"[red]LLM call failed: {e}[/red]")
            break

        tokens.add(response.usage)

        text_blocks = [b for b in response.content if b.type == "text"]
        tool_blocks = [b for b in response.content if b.type == "tool_use"]
        if text_blocks:
            reasoning = text_blocks[0].text[:400]
            console.print(f"\n[italic dim]{reasoning}{'...' if len(text_blocks[0].text) > 400 else ''}[/italic dim]")

        messages.append({"role": "assistant", "content": response.content})

        if not tool_blocks:
            console.print("[yellow]No tool calls — agent may be done.[/yellow]")
            if response.stop_reason == "end_turn":
                break
            continue

        tool_result_messages = []

        for tool_use in tool_blocks:
            name = tool_use.name
            inp = tool_use.input
            console.print(f"\n[bold cyan]▶ {name}[/bold cyan] [dim]{json.dumps(inp)[:120]}[/dim]")

            result_json = execute_tool(client, name, inp, state)

            try:
                result = json.loads(result_json)
            except Exception:
                result = {}

            if name == "generate_operation_types" and "operation_types" in result:
                operation_types = apply_operation_types(result["operation_types"], operation_types)
            elif name == "assess_asset":
                if "error" not in result:
                    apply_assessment(enriched, inp.get("asset_name", ""), result)
                else:
                    console.print(f"[red]  assess_asset error: {result.get('error')}[/red]")
            elif name == "web_search":
                console.print(f"[dim]  → {len(result.get('results', []))} results[/dim]")
            elif name == "fetch_page":
                if "error" in result:
                    console.print(f"[yellow]  → {result['error']}[/yellow]")
                else:
                    console.print(f"[dim]  → {len(result.get('text', ''))} chars[/dim]")
            elif name == "task_complete":
                console.print(f"[green bold]  ✓ Task complete: {state['completion_summary']}[/green bold]")

            tool_result_messages.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": result_json,
            })

        messages.append({"role": "user", "content": tool_result_messages})
        tokens.add_extra(state["extra_tokens"])
        state["extra_tokens"] = {"input": 0, "output": 0}

        if state["complete"]:
            break

        time.sleep(0.3)

    # ── Build output ───────────────────────────────────────────────────────────
    console.print(f"\n{'═' * 60}")
    console.print("[bold green]ANALYST RUN COMPLETE[/bold green]")
    console.print(f"{'═' * 60}\n")

    output = AnalystOutput(
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat() + "Z",
            "source_file": str(Path(input_path).name),
            "service": config.SERVICE,
            "agent_model": config.MODEL,
            "total_assets_analysed": len(enriched),
            "total_iterations": iteration,
            "total_tokens_used": tokens.total(),
            "operation_types": [
                {"id": ot.id, "name": ot.name, "description": ot.description}
                for ot in operation_types
            ],
        },
        assets=enriched,
    )

    output_dict = output.to_output_dict()
    json_output = json.dumps(output_dict, indent=2)

    table = Table(title="British Army Unit Assessments", show_header=True, header_style="bold magenta")
    table.add_column("Unit", style="bold", max_width=28)
    table.add_column("Category", max_width=20)
    table.add_column("Readiness", max_width=8)
    table.add_column("Assignment", max_width=30)

    readiness_colours = {"high": "green", "medium": "yellow", "low": "red"}
    for a in enriched:
        r = a.operational_readiness or "—"
        colour = readiness_colours.get(r, "white")
        table.add_row(
            a.name,
            a.unit_category or "—",
            Text(r, style=colour),
            (a.current_assignment or "—")[:30],
        )
    console.print(table)

    if operation_types:
        console.print("\n[bold]Operation Types Used:[/bold]")
        for ot in operation_types:
            console.print(f"  [magenta]{ot.id}[/magenta]: {ot.name} — {ot.description[:80]}")

    console.print(f"\n[bold]{tokens.summary()}[/bold]")
    console.print(f"Iterations used: {iteration}")
    console.print(f"Units enriched: {sum(1 for a in enriched if a.is_enriched())} / {len(enriched)}")

    console.print("\n[bold]=== ENRICHED JSON OUTPUT ===[/bold]")
    console.print(json_output)

    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"ba_enriched_{timestamp}.json"
    out_path.write_text(json_output)
    console.print(f"\n[green]Saved to: {out_path}[/green]")

    return output_dict


if __name__ == "__main__":
    if len(sys.argv) < 2:
        console.print(
            "[bold]Usage:[/bold] python analyst_agent.py path/to/ba_assets_TIMESTAMP.json\n"
            "[dim]Example:[/dim] python analyst_agent.py "
            "../ba_osint_agent/output/ba_assets_20260412_120000.json"
        )
        sys.exit(1)

    run_analyst(sys.argv[1])
