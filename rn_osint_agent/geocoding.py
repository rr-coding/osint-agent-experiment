import json
import re
import anthropic
from rich.console import Console

import config

console = Console()

# ─── Fixed known locations for Royal Navy bases and stations ──────────────────
# These never need an LLM call — coordinates are authoritative.
KNOWN_FIXED_LOCATIONS = {
    # Naval bases
    "hmnb portsmouth":      (50.7984, -1.1082, 0.99, "HMNB Portsmouth — fixed base location"),
    "hmnb devonport":       (50.3714, -4.1872, 0.99, "HMNB Devonport — fixed base location"),
    "hmnb clyde":           (56.0748, -4.8040, 0.99, "HMNB Clyde (Faslane) — fixed base location"),
    "portsmouth":           (50.7984, -1.1082, 0.97, "Portsmouth Naval Base"),
    "devonport":            (50.3714, -4.1872, 0.97, "HMNB Devonport, Plymouth"),
    "plymouth":             (50.3714, -4.1872, 0.95, "HMNB Devonport, Plymouth"),
    "faslane":              (56.0748, -4.8040, 0.97, "HMNB Clyde, Faslane"),
    "clyde":                (56.0748, -4.8040, 0.92, "HMNB Clyde area"),
    "rosyth":               (56.0245, -3.4355, 0.97, "Rosyth Dockyard, Firth of Forth"),
    # Air stations
    "rnas culdrose":        (50.0858, -5.2567, 0.99, "RNAS Culdrose — fixed station location"),
    "rnas yeovilton":       (51.0094, -2.6386, 0.99, "RNAS Yeovilton — fixed station location"),
    "culdrose":             (50.0858, -5.2567, 0.97, "RNAS Culdrose, Cornwall"),
    "yeovilton":            (51.0094, -2.6386, 0.97, "RNAS Yeovilton, Somerset"),
    # Overseas bases
    "gibraltar":            (36.1408, -5.3536, 0.97, "Gibraltar — Royal Navy facility"),
    "bahrain":              (26.2041,  50.6465, 0.95, "Naval Support Activity Bahrain (HMS Jufair)"),
    "jufair":               (26.2041,  50.6465, 0.97, "HMS Jufair, Bahrain"),
    "cyprus":               (34.9529,  33.0838, 0.85, "British Sovereign Base Areas, Cyprus"),
    "akrotiri":             (34.5900,  32.9872, 0.97, "RAF Akrotiri, Cyprus SBA"),
    "bfbs falkland":        (-51.693, -57.777,  0.95, "Mount Pleasant, Falkland Islands"),
    "falkland":             (-51.693, -57.777,  0.90, "Falkland Islands"),
    "diego garcia":         (-7.3195,  72.4228, 0.97, "Diego Garcia, BIOT"),
    "ascension":            (-7.9697, -14.3559, 0.97, "Ascension Island"),
}


def _lookup_fixed_location(location_description: str) -> dict | None:
    """
    Check if the location description matches a known fixed location.
    Returns a geocoding result dict or None.
    """
    desc_lower = location_description.lower()
    # Try longest key match first
    for key in sorted(KNOWN_FIXED_LOCATIONS, key=len, reverse=True):
        if key in desc_lower:
            lat, lon, conf, rationale = KNOWN_FIXED_LOCATIONS[key]
            return {
                "latitude": lat,
                "longitude": lon,
                "confidence_score": conf,
                "resolution_rationale": rationale,
            }
    return None


def resolve_location(
    client: anthropic.Anthropic,
    asset_name: str,
    location_description: str,
) -> dict:
    """
    Resolve a location description to approximate coordinates.
    First checks fixed lookup table, then falls back to LLM.
    Always returns coordinates — a low-confidence estimate is better than nothing.
    """
    # ── 1. Check fixed lookup first ───────────────────────────────────────────
    fixed = _lookup_fixed_location(location_description)
    if fixed and fixed["confidence_score"] >= 0.90:
        console.print(f"[dim]    Fixed lookup hit: {fixed['resolution_rationale']}[/dim]")
        return fixed

    # ── 2. LLM geocoding for everything else ─────────────────────────────────
    prompt = f"""You are a geographic intelligence analyst. Resolve the following location description to approximate coordinates.

Asset: {asset_name}
Location description: {location_description}

IMPORTANT: Always provide coordinates. A low-confidence estimate is better than no location.
- For vague descriptions like "at sea", "deployed", "on exercise" — give the most likely geographic centre.
- For refit or maintenance descriptions — use the dockyard's coordinates.
- For sea areas — use the centre of that sea area.
- Never return null coordinates.

Confidence scale:
  0.9–1.0: Named port or base with known coordinates
  0.7–0.89: Named city/region precisely locatable
  0.5–0.69: General sea area (e.g. "Eastern Mediterranean", "North Atlantic")
  0.3–0.49: Vague (e.g. "deployed overseas", "on exercise in the Gulf")
  0.1–0.29: Extremely vague (e.g. "at sea", "operational") — still provide best-estimate coords

Respond ONLY with valid JSON:
{{
  "latitude": <float>,
  "longitude": <float>,
  "confidence_score": <float 0.1-1.0>,
  "resolution_rationale": "<string>"
}}"""

    try:
        response = client.messages.create(
            model=config.EXTRACT_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            result = json.loads(text[start:end])
            # Reject null coordinates — fall back to fixed lookup if available
            if result.get("latitude") is None or result.get("longitude") is None:
                if fixed:
                    return fixed
                return {
                    "latitude": None,
                    "longitude": None,
                    "confidence_score": 0.0,
                    "resolution_rationale": "LLM returned null coordinates and no fixed lookup available",
                }
            return result
        return {
            "latitude": None,
            "longitude": None,
            "confidence_score": 0.0,
            "resolution_rationale": "Failed to parse geocoding response",
        }
    except Exception as e:
        console.print(f"[yellow]Geocoding error for {asset_name}: {e}[/yellow]")
        if fixed:
            return fixed
        return {
            "latitude": None,
            "longitude": None,
            "confidence_score": 0.0,
            "resolution_rationale": f"Geocoding error: {str(e)}",
        }
