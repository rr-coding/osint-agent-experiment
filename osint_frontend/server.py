"""
OSINT Command Centre — Flask backend server.
Serves the frontend and provides API endpoints for data and agent execution.
Supports Royal Navy, British Army, and Royal Air Force.
"""
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, send_from_directory, request

# ── Agent configuration ───────────────────────────────────────────────────────
AGENTS = {
    "royal_navy": {
        "osint_dir":    "../rn_osint_agent",
        "analyst_dir":  "../rn_analyst_agent",
        "osint_cmd":    ["python", "agent.py"],
        "analyst_cmd":  ["python", "analyst_agent.py"],
        "osint_glob":   "rn_assets_*.json",
        "analyst_glob": "rn_enriched_*.json",
        "label":        "NAVY",
    },
    "british_army": {
        "osint_dir":    "../ba_osint_agent",
        "analyst_dir":  "../ba_analyst_agent",
        "osint_cmd":    ["python", "agent.py"],
        "analyst_cmd":  ["python", "analyst_agent.py"],
        "osint_glob":   "ba_assets_*.json",
        "analyst_glob": "ba_enriched_*.json",
        "label":        "ARMY",
    },
    "royal_air_force": {
        "osint_dir":    "../raf_osint_agent",
        "analyst_dir":  "../raf_analyst_agent",
        "osint_cmd":    ["python", "agent.py"],
        "analyst_cmd":  ["python", "analyst_agent.py"],
        "osint_glob":   "raf_assets_*.json",
        "analyst_glob": "raf_enriched_*.json",
        "label":        "RAF",
    },
}

HOST = "127.0.0.1"
PORT = 8080

BASE_DIR = Path(__file__).parent


def _resolve_output_dir(agent_key: str, agent_type: str) -> Path:
    """Return resolved path to an agent's output directory."""
    cfg = AGENTS[agent_key]
    rel_dir = cfg["osint_dir"] if agent_type == "osint" else cfg["analyst_dir"]
    return (BASE_DIR / rel_dir / "output").resolve()


def _latest_json(directory: Path, glob: str = "*.json"):
    """Return (path, mtime_iso) of the most recently modified matching .json."""
    try:
        files = list(directory.glob(glob))
    except FileNotFoundError:
        return None, None
    if not files:
        return None, None
    latest = max(files, key=lambda p: p.stat().st_mtime)
    mtime = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
    return latest, mtime.strftime("%Y-%m-%dT%H:%M:%SZ")


app = Flask(__name__, static_folder=str(BASE_DIR))


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(str(BASE_DIR), "index.html")


@app.route("/api/status")
def api_status():
    services = {}
    for svc_key, cfg in AGENTS.items():
        osint_dir    = _resolve_output_dir(svc_key, "osint")
        analyst_dir  = _resolve_output_dir(svc_key, "analyst")
        osint_path, osint_mtime     = _latest_json(osint_dir,   cfg["osint_glob"])
        analyst_path, analyst_mtime = _latest_json(analyst_dir, cfg["analyst_glob"])
        services[svc_key] = {
            "osint_data_exists":      osint_path is not None,
            "osint_data_file":        osint_path.name if osint_path else None,
            "osint_data_modified":    osint_mtime,
            "enriched_data_exists":   analyst_path is not None,
            "enriched_data_file":     analyst_path.name if analyst_path else None,
            "enriched_data_modified": analyst_mtime,
        }
    return jsonify({"services": services})


@app.route("/api/data")
def api_data():
    """
    Merge enriched (or OSINT fallback) data from all three services.
    Returns {"metadata": {...}, "assets": [...merged, each tagged with service field...]}
    """
    all_assets = []
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat() + "Z",
        "services_loaded": [],
        "total_tokens_used": 0,
        "operation_types": [],
    }

    for svc_key, cfg in AGENTS.items():
        analyst_dir = _resolve_output_dir(svc_key, "analyst")
        osint_dir   = _resolve_output_dir(svc_key, "osint")

        path, _ = _latest_json(analyst_dir, cfg["analyst_glob"])
        if path is None:
            path, _ = _latest_json(osint_dir, cfg["osint_glob"])
        if path is None:
            continue

        try:
            data = json.loads(path.read_text())
        except Exception:
            continue

        # Handle both enriched format {metadata, assets} and raw list
        if isinstance(data, dict) and "assets" in data:
            assets = data["assets"]
            svc_meta = data.get("metadata", {})
            metadata["total_tokens_used"] += svc_meta.get("total_tokens_used", 0)
            for ot in svc_meta.get("operation_types", []):
                if not any(x["id"] == ot["id"] for x in metadata["operation_types"]):
                    metadata["operation_types"].append(ot)
        elif isinstance(data, list):
            assets = data
        else:
            continue

        # Ensure every asset has a service field
        for asset in assets:
            if not asset.get("service"):
                asset["service"] = svc_key

        all_assets.extend(assets)
        metadata["services_loaded"].append(svc_key)

    if not all_assets:
        return jsonify({"error": "No data files available"}), 404

    return jsonify({"metadata": metadata, "assets": all_assets})


@app.route("/api/gather", methods=["POST"])
def api_gather():
    """
    Triggers OSINT + analyst agents for each requested service.
    Streams combined stdout/stderr back via Server-Sent Events.
    Accepts: {"agents": ["royal_navy", "british_army", "royal_air_force"]}
    """
    body = request.get_json(silent=True) or {}
    # Support both old "agent" (single) and new "agents" (list) keys
    requested = body.get("agents") or ([body["agent"]] if body.get("agent") else list(AGENTS.keys()))
    # Filter to valid service keys
    to_run = [s for s in requested if s in AGENTS]
    if not to_run:
        to_run = list(AGENTS.keys())

    def event(type_, **kwargs):
        payload = json.dumps({"type": type_, **kwargs})
        return f"data: {payload}\n\n"

    def generate():
        python_exe = _find_python()

        for svc_key in to_run:
            cfg = AGENTS[svc_key]
            label = cfg["label"]
            osint_dir   = (BASE_DIR / cfg["osint_dir"]).resolve()
            analyst_dir = (BASE_DIR / cfg["analyst_dir"]).resolve()

            # ── OSINT agent ───────────────────────────────────────────────────
            yield event("status", message=f"[{label}/OSINT] Starting OSINT agent...")
            osint_cmd = [python_exe] + cfg["osint_cmd"][1:]
            try:
                proc = subprocess.Popen(
                    osint_cmd,
                    cwd=str(osint_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env={**os.environ},
                )
            except Exception as e:
                yield event("error", message=f"[{label}/OSINT] Failed to start: {e}")
                continue

            for line in proc.stdout:
                yield event("log", source=f"{label}/OSINT", line=line.rstrip("\n"))

            proc.wait()
            if proc.returncode != 0:
                yield event("error", message=f"[{label}/OSINT] Exited with code {proc.returncode}")
                continue

            yield event("status", message=f"[{label}/OSINT] Complete. Starting analyst...")

            # Locate fresh OSINT output
            osint_out_dir = _resolve_output_dir(svc_key, "osint")
            osint_path, _ = _latest_json(osint_out_dir, cfg["osint_glob"])
            if osint_path is None:
                yield event("error", message=f"[{label}/OSINT] No output file found.")
                continue

            # ── Analyst agent ─────────────────────────────────────────────────
            analyst_cmd = [python_exe, cfg["analyst_cmd"][1] if len(cfg["analyst_cmd"]) > 1 else "analyst_agent.py", str(osint_path)]
            try:
                proc2 = subprocess.Popen(
                    analyst_cmd,
                    cwd=str(analyst_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env={**os.environ},
                )
            except Exception as e:
                yield event("error", message=f"[{label}/ANALYST] Failed to start: {e}")
                continue

            for line in proc2.stdout:
                yield event("log", source=f"{label}/ANALYST", line=line.rstrip("\n"))

            proc2.wait()
            if proc2.returncode != 0:
                yield event("error", message=f"[{label}/ANALYST] Exited with code {proc2.returncode}")
                continue

            analyst_out_dir = _resolve_output_dir(svc_key, "analyst")
            enriched_path, _ = _latest_json(analyst_out_dir, cfg["analyst_glob"])
            data_file = enriched_path.name if enriched_path else osint_path.name
            yield event("status", message=f"[{label}] Complete. Output: {data_file}")

        yield event("complete", data_file="merged")

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _find_python():
    import sys
    return sys.executable


if __name__ == "__main__":
    print(f"OSINT Command Centre server starting on http://{HOST}:{PORT}")
    for svc_key, cfg in AGENTS.items():
        osint_dir  = _resolve_output_dir(svc_key, "osint")
        analyst_dir = _resolve_output_dir(svc_key, "analyst")
        print(f"  {svc_key}: OSINT={osint_dir}, Analyst={analyst_dir}")
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
