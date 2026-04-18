import json
import anthropic
from rich.console import Console

import config

console = Console()

# ─── Fixed known locations for RAF stations and deployed areas ────────────────
KNOWN_FIXED_LOCATIONS = {
    # UK RAF stations
    "raf brize norton":      (51.7594, -1.5834, 0.99, "RAF Brize Norton, Oxfordshire"),
    "brize norton":          (51.7594, -1.5834, 0.97, "RAF Brize Norton, Oxfordshire"),
    "raf marham":            (52.6444,  0.5535, 0.99, "RAF Marham, Norfolk"),
    "marham":                (52.6444,  0.5535, 0.97, "RAF Marham, Norfolk"),
    "raf lossiemouth":       (57.7053, -3.3389, 0.99, "RAF Lossiemouth, Moray"),
    "lossiemouth":           (57.7053, -3.3389, 0.97, "RAF Lossiemouth, Moray"),
    "raf coningsby":         (53.0931, -0.1660, 0.99, "RAF Coningsby, Lincolnshire"),
    "coningsby":             (53.0931, -0.1660, 0.97, "RAF Coningsby, Lincolnshire"),
    "raf waddington":        (53.1645, -0.5229, 0.99, "RAF Waddington, Lincolnshire"),
    "waddington":            (53.1645, -0.5229, 0.97, "RAF Waddington, Lincolnshire"),
    "raf northolt":          (51.5530, -0.4188, 0.99, "RAF Northolt, London"),
    "northolt":              (51.5530, -0.4188, 0.97, "RAF Northolt, London"),
    "raf valley":            (53.2481, -4.5342, 0.99, "RAF Valley, Anglesey"),
    "valley":                (53.2481, -4.5342, 0.97, "RAF Valley, Anglesey"),
    "raf cranwell":          (53.0303, -0.4826, 0.99, "RAF Cranwell, Lincolnshire"),
    "cranwell":              (53.0303, -0.4826, 0.97, "RAF Cranwell, Lincolnshire"),
    "raf benson":            (51.6161, -1.0952, 0.99, "RAF Benson, Oxfordshire"),
    "benson":                (51.6161, -1.0952, 0.97, "RAF Benson, Oxfordshire"),
    "raf honington":         (52.3427,  0.7737, 0.99, "RAF Honington, Suffolk"),
    "honington":             (52.3427,  0.7737, 0.97, "RAF Honington, Suffolk"),
    "raf shawbury":          (52.7977, -2.6651, 0.99, "RAF Shawbury, Shropshire"),
    "shawbury":              (52.7977, -2.6651, 0.97, "RAF Shawbury, Shropshire"),
    "raf wittering":         (52.6119, -0.4762, 0.99, "RAF Wittering, Cambridgeshire"),
    "wittering":             (52.6119, -0.4762, 0.97, "RAF Wittering, Cambridgeshire"),
    "raf odiham":            (51.2344, -1.0024, 0.99, "RAF Odiham, Hampshire"),
    "odiham":                (51.2344, -1.0024, 0.97, "RAF Odiham, Hampshire"),
    "raf halton":            (51.7900, -0.7219, 0.99, "RAF Halton, Buckinghamshire"),
    "halton":                (51.7900, -0.7219, 0.97, "RAF Halton, Buckinghamshire"),
    "raf high wycombe":      (51.6301, -0.7443, 0.99, "RAF High Wycombe, Bucks (HQ Air Command)"),
    "high wycombe":          (51.6301, -0.7443, 0.95, "RAF High Wycombe, HQ Air Command"),
    "raf syerston":          (53.0261, -0.9005, 0.99, "RAF Syerston, Nottinghamshire"),
    "raf linton-on-ouse":    (54.0436, -1.2474, 0.99, "RAF Linton-on-Ouse, Yorkshire"),
    "raf cosford":           (52.6405, -2.3060, 0.99, "RAF Cosford, Shropshire"),
    "cosford":               (52.6405, -2.3060, 0.97, "RAF Cosford, Shropshire"),
    # Overseas stations
    "raf akrotiri":          (34.5900,  32.9872, 0.99, "RAF Akrotiri, Cyprus"),
    "akrotiri":              (34.5900,  32.9872, 0.97, "RAF Akrotiri, Cyprus"),
    "raf mount pleasant":    (-51.823, -58.447,  0.99, "RAF Mount Pleasant, Falkland Islands"),
    "mount pleasant":        (-51.823, -58.447,  0.95, "RAF Mount Pleasant, Falkland Islands"),
    "raf ascension":         (-7.9697, -14.3559, 0.99, "RAF Ascension Island"),
    "ascension island":      (-7.9697, -14.3559, 0.97, "Ascension Island"),
    "raf diego garcia":      (-7.3195,  72.4228, 0.97, "Diego Garcia, BIOT"),
    "diego garcia":          (-7.3195,  72.4228, 0.97, "Diego Garcia, BIOT"),
    # Exercise locations
    "nellis":                (36.2361, -115.0342, 0.97, "Nellis AFB, Nevada — Exercise Red Flag"),
    "red flag":              (36.2361, -115.0342, 0.90, "Nellis AFB — Exercise Red Flag"),
    "andersen":              (13.5775,  144.9282, 0.95, "Andersen AFB, Guam — Exercise Cope North"),
    "cope north":            (13.5775,  144.9282, 0.85, "Guam — Exercise Cope North"),
    "op shader":             (34.5900,  32.9872, 0.80, "Op Shader — Akrotiri-based operations"),
    "op biloxi":             (-7.3195,  72.4228, 0.75, "Op Biloxi — Diego Garcia-based operations"),
    "cyprus":                (34.9529,  33.0838, 0.85, "Cyprus — RAF detachment"),
    "falkland":              (-51.823, -58.447,  0.85, "Falkland Islands — RAF detachment"),
    "bahrain":               (26.2041,  50.6465, 0.85, "Bahrain — RAF detachment"),
    "al udeid":              (25.1172,  51.3153, 0.95, "Al Udeid Air Base, Qatar"),
    "qatar":                 (25.1172,  51.3153, 0.85, "Qatar — RAF detachment"),
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
- For RAF stations (Brize Norton, Marham, Coningsby, Lossiemouth, etc.) — use the station coordinates.
- For overseas deployments — use the base or area coordinates.
- For exercise locations — use the exercise area.
- Never return null coordinates.

Confidence scale:
  0.9–1.0: Named station or base with known coordinates
  0.7–0.89: Named city/region precisely locatable
  0.5–0.69: General country/region
  0.3–0.49: Vague area (e.g. "deployed overseas", "on exercise")
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
