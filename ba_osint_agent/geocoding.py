import json
import anthropic
from rich.console import Console

import config

console = Console()

# ─── Fixed known locations for British Army garrisons and deployed areas ──────
KNOWN_FIXED_LOCATIONS = {
    # UK garrisons
    "tidworth":              (51.2337, -1.6549, 0.97, "Tidworth Garrison, Wiltshire"),
    "bulford":               (51.2011, -1.7213, 0.97, "Bulford Camp, Wiltshire"),
    "larkhill":              (51.2085, -1.8028, 0.97, "Larkhill Garrison, Wiltshire"),
    "aldershot":             (51.2480, -0.7590, 0.97, "Aldershot Garrison, Hampshire"),
    "colchester":            (51.8862,  0.8797, 0.97, "Colchester Garrison, Essex"),
    "catterick":             (54.3744, -1.6977, 0.97, "Catterick Garrison, North Yorkshire"),
    "bovington":             (50.7367, -2.2497, 0.97, "Bovington Camp, Dorset"),
    "warminster":            (51.2027, -2.1740, 0.97, "Warminster Garrison, Wiltshire"),
    "perham down":           (51.2457, -1.6183, 0.95, "Perham Down, Wiltshire"),
    "brecon":                (51.9462, -3.3874, 0.97, "Brecon Barracks, Wales"),
    "sandhurst":             (51.3605, -0.7419, 0.97, "Royal Military Academy Sandhurst"),
    "pirbright":             (51.3029, -0.6441, 0.97, "Pirbright Camp, Surrey"),
    "shrivenham":            (51.6079, -1.6607, 0.95, "Defence Academy of the UK, Shrivenham"),
    "abingdon":              (51.6890, -1.3033, 0.92, "Dalton Barracks, Abingdon"),
    "dalton barracks":       (51.6890, -1.3033, 0.97, "Dalton Barracks, Abingdon"),
    "bassingbourn":          (52.0850, -0.0400, 0.95, "Bassingbourn Barracks, Cambridgeshire"),
    "dishforth":             (54.1281, -1.4082, 0.95, "Dishforth Airfield, North Yorkshire"),
    "kinloss":               (57.6494, -3.5611, 0.95, "Kinloss Barracks, Moray"),
    "leuchars":              (56.3728, -2.8652, 0.95, "Leuchars Station, Fife"),
    "hereford":              (52.0567, -2.7160, 0.90, "SAS HQ, Hereford"),
    "sterling lines":        (52.0567, -2.7160, 0.97, "SAS Stirling Lines, Hereford"),
    "commando training":     (50.5648, -3.6483, 0.95, "Commando Training Centre Royal Marines, Lympstone"),
    "lympstone":             (50.5648, -3.6483, 0.97, "Commando Training Centre RM, Lympstone"),
    "folkestone":            (51.0835,  1.1662, 0.92, "Folkestone, Kent"),
    "lisburn":               (54.5097, -6.0420, 0.97, "Thiepval Barracks, Lisburn, NI"),
    "palace barracks":       (54.6408, -5.8740, 0.97, "Palace Barracks, Holywood, NI"),
    "edinburgh castle":      (55.9487, -3.2008, 0.97, "Edinburgh Castle"),
    # Overseas permanent/semi-permanent
    "cyprus":                (34.9529,  33.0838, 0.85, "British Forces Cyprus"),
    "episkopi":              (34.6682,  32.9046, 0.97, "Episkopi Garrison, Cyprus"),
    "dhekelia":              (34.9917,  33.7444, 0.97, "Dhekelia Garrison, Cyprus"),
    "kenya":                 (-0.0236,  37.9062, 0.80, "BATUK — British Army Training Unit Kenya"),
    "batus":                 (50.9668, -110.7245, 0.97, "BATUS — British Army Training Unit Suffield, Canada"),
    "suffield":              (50.9668, -110.7245, 0.97, "British Army Training Unit Suffield, Canada"),
    "brunei":                (4.9459,  114.9486, 0.90, "British Garrison Seria, Brunei"),
    "seria":                 (4.6066,  114.1706, 0.95, "British Garrison Seria, Brunei"),
    "falkland":              (-51.693, -57.777,  0.85, "Falkland Islands — British Forces"),
    # NATO enhanced forward presence
    "tapa":                  (59.2683,  25.9560, 0.97, "Tapa Camp, Estonia — NATO eFP"),
    "estonia":               (59.2683,  25.9560, 0.85, "Estonia — NATO Enhanced Forward Presence"),
    "op cabrit":             (59.2683,  25.9560, 0.90, "Op Cabrit — Estonia, NATO eFP"),
    "orzysz":                (53.8085,  21.9689, 0.95, "Orzysz, Poland — NATO eFP"),
    "poland":                (53.8085,  21.9689, 0.75, "Poland — British Army deployment"),
    "kosovo":                (42.6026,  20.9030, 0.85, "Kosovo — KFOR British contingent"),
    "mali":                  (17.5707,  -3.9962, 0.80, "Mali — Op Newcombe"),
    "op newcombe":           (17.5707,  -3.9962, 0.85, "Mali — Op Newcombe"),
    "ukraine":               (49.1735,  31.8240, 0.75, "Ukraine — Op Interflex training"),
    "op interflex":          (51.5074,  -0.1278, 0.75, "Op Interflex — UK-based training for Ukrainian forces"),
    "germany":               (51.1657,  10.4515, 0.70, "Germany — British Army"),
    "british forces germany":(51.1657,  10.4515, 0.80, "British Forces Germany"),
}


def _lookup_fixed_location(location_description: str) -> dict | None:
    desc_lower = location_description.lower()
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
    Checks fixed lookup table first, then falls back to LLM.
    """
    fixed = _lookup_fixed_location(location_description)
    if fixed and fixed["confidence_score"] >= 0.90:
        console.print(f"[dim]    Fixed lookup hit: {fixed['resolution_rationale']}[/dim]")
        return fixed

    prompt = f"""You are a geographic intelligence analyst. Resolve the following location description to approximate coordinates.

Asset: {asset_name}
Location description: {location_description}

IMPORTANT: Always provide coordinates. A low-confidence estimate is better than no location.
- For UK barracks/garrisons — use the garrison coordinates.
- For overseas deployments (Estonia, Poland, Mali, Kenya, etc.) — use the deployment area centre.
- For exercise areas — use the centre of the exercise area.
- Never return null coordinates.

Confidence scale:
  0.9–1.0: Named garrison or base with known coordinates
  0.7–0.89: Named city/region precisely locatable
  0.5–0.69: General country/area
  0.3–0.49: Vague (e.g. "deployed overseas", "on exercise")
  0.1–0.29: Extremely vague — still provide best-estimate coords

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
            if result.get("latitude") is None or result.get("longitude") is None:
                if fixed:
                    return fixed
                return {
                    "latitude": None,
                    "longitude": None,
                    "confidence_score": 0.0,
                    "resolution_rationale": "LLM returned null coordinates",
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
