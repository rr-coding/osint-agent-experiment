"""
Build script: produces docs/index.html — a self-contained GitHub Pages demo
from the existing index.html + merged enriched/OSINT JSON from all three services.
"""
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

BASE       = Path(__file__).parent
DOCS       = BASE.parent / "docs"
SRC_HTML   = BASE / "index.html"

# Agent directories
AGENT_DIRS = {
    "royal_navy": {
        "analyst": BASE.parent / "rn_analyst_agent" / "output",
        "osint":   BASE.parent / "rn_osint_agent" / "output",
        "analyst_glob": "rn_enriched_*.json",
        "osint_glob":   "rn_assets_*.json",
    },
    "british_army": {
        "analyst": BASE.parent / "ba_analyst_agent" / "output",
        "osint":   BASE.parent / "ba_osint_agent" / "output",
        "analyst_glob": "ba_enriched_*.json",
        "osint_glob":   "ba_assets_*.json",
    },
    "royal_air_force": {
        "analyst": BASE.parent / "raf_analyst_agent" / "output",
        "osint":   BASE.parent / "raf_osint_agent" / "output",
        "analyst_glob": "raf_enriched_*.json",
        "osint_glob":   "raf_assets_*.json",
    },
}


def _latest(directory: Path, glob: str):
    """Return path to most recently modified matching file, or None."""
    try:
        files = sorted(directory.glob(glob), key=lambda p: p.stat().st_mtime)
    except FileNotFoundError:
        return None
    return files[-1] if files else None


# ── Merge data from all available services ────────────────────────────────────
all_assets = []
merged_metadata = {
    "generated_at": datetime.now(timezone.utc).isoformat() + "Z",
    "services_loaded": [],
    "total_tokens_used": 0,
    "operation_types": [],
}

for svc_key, dirs in AGENT_DIRS.items():
    path = _latest(dirs["analyst"], dirs["analyst_glob"])
    if path is None:
        path = _latest(dirs["osint"], dirs["osint_glob"])
    if path is None:
        print(f"  ℹ No data found for {svc_key} — skipping")
        continue

    print(f"  Embedding ({svc_key}): {path.name}")
    with open(path) as f:
        data = json.load(f)

    if isinstance(data, dict) and "assets" in data:
        assets = data["assets"]
        svc_meta = data.get("metadata", {})
        merged_metadata["total_tokens_used"] += svc_meta.get("total_tokens_used", 0)
        for ot in svc_meta.get("operation_types", []):
            if not any(x["id"] == ot["id"] for x in merged_metadata["operation_types"]):
                merged_metadata["operation_types"].append(ot)
    elif isinstance(data, list):
        assets = data
    else:
        continue

    for asset in assets:
        if not asset.get("service"):
            asset["service"] = svc_key

    all_assets.extend(assets)
    merged_metadata["services_loaded"].append(svc_key)

if not all_assets:
    print("ERROR: No data found in any service output directory.")
    sys.exit(1)

print(f"  Total assets: {len(all_assets)} from {len(merged_metadata['services_loaded'])} service(s)")

embedded_data = {"metadata": merged_metadata, "assets": all_assets}
embedded_json = json.dumps(embedded_data, separators=(",", ":"))
DOCS.mkdir(exist_ok=True)

# ── Read source HTML ──────────────────────────────────────────────────────────
src = SRC_HTML.read_text()

# ── 1. Inject embedded data block right after <script> ───────────────────────
data_block = f"const EMBEDDED_DATA = {embedded_json};\n\n"
src = src.replace(
    "<script>\n/* ═══",
    f"<script>\n{data_block}/* ═══"
)

# ── 2. Replace init block ─────────────────────────────────────────────────────
old_init = """\
// ── Init ──────────────────────────────────────────────────────────────────
initMap();
setStatus("nodata", "NO DATA");

// Check status then auto-load most recent enriched data if available
(async () => {
  await checkStatus();
  if (statusInfo.existing) {
    selectDatasource("existing");
    await loadExistingData();
  }
})();"""

new_init = """\
// ── Init ──────────────────────────────────────────────────────────────────
initMap();
setStatus("ready", "SYSTEM READY");

// Demo mode: load embedded data immediately
(function () {
  currentData = EMBEDDED_DATA;
  const meta = EMBEDDED_DATA.metadata || {};
  statusInfo.existing = true;
  statusInfo.existingFile = "embedded (" + (meta.services_loaded || []).join(", ") + ")";
  statusInfo.existingModified = meta.generated_at || null;
  selectDatasource("existing");
  updateMap();
  updateFooter();

  // Enable toggles for services that have data
  const loaded = meta.services_loaded || [];
  if (loaded.includes("british_army"))   document.getElementById("ba-toggle").checked = true;
  if (loaded.includes("royal_air_force"))document.getElementById("raf-toggle").checked = true;
  updateMap();
  updateFooter();

  // Simulated typewriter agent log
  const assets = EMBEDDED_DATA.assets || [];
  const lines = [];
  const readinessLabel = r => r ? r.toUpperCase() : "UNKNOWN";
  const svcTag = svc => {
    if (svc === "royal_navy")      return "[NAVY/OSINT]";
    if (svc === "british_army")    return "[ARMY/OSINT]";
    if (svc === "royal_air_force") return "[RAF/OSINT]";
    return "[OSINT]";
  };
  assets.forEach(a => {
    const tag = svcTag(a.service);
    lines.push(["cyan",  `${tag} Querying: ${a.name} deployment 2026`]);
    if (a.location_description) {
      lines.push(["green", `${tag} ${a.name} — ${a.class || a.type} — ${a.location_description}`]);
    } else {
      lines.push(["green", `${tag} ${a.name} — ${a.class || a.type}`]);
    }
    if (a.operational_readiness) {
      lines.push(["white", `${tag} Readiness: ${readinessLabel(a.operational_readiness)} — ${(a.current_assignment || "assignment not confirmed").slice(0,80)}`]);
    }
  });
  lines.push(["dim", `[STATUS] Dataset loaded. ${assets.length} assets. ${assets.filter(x=>x.latitude!=null).length} geocoded.`]);

  let i = 0;
  const typeNext = () => {
    if (i >= lines.length) return;
    const [cls, text] = lines[i++];
    log(cls, text);
    setTimeout(typeNext, 40);
  };
  typeNext();
})();"""

src = src.replace(old_init, new_init)

# ── 3. Replace async loadExistingData (fetch call) with demo stub ─────────────
old_load = """\
async function loadExistingData() {
  log("dim", `Loading existing dataset... ${statusInfo.existingFile || ""}`);
  try {
    const res = await fetch("/api/data");
    if (!res.ok) { log("red", "[ERROR] Failed to load data: " + res.status); return; }
    const data = await res.json();
    setData(data);
    const assets = data.assets || data;
    const located = Array.isArray(assets) ? assets.filter(a => a.latitude != null).length : 0;
    const total = Array.isArray(assets) ? assets.length : 0;
    log("white", `[STATUS] ${total} assets loaded. ${located} geocoded. Map populated.`);
    setStatus("ready", "SYSTEM READY");
  } catch (e) {
    log("red", "[ERROR] " + e.message);
  }
}"""

new_load = """\
async function loadExistingData() {
  // Demo mode: data already embedded
  setData(EMBEDDED_DATA);
  const assets = EMBEDDED_DATA.assets || [];
  log("white", `[STATUS] ${assets.length} assets loaded from embedded data. Map populated.`);
  setStatus("ready", "SYSTEM READY");
}"""

src = src.replace(old_load, new_load)

# ── 4. Replace gatherFreshOSINT (SSE fetch) with demo stub ───────────────────
old_gather = """\
async function gatherFreshOSINT() {
  isRunning = true;
  updateExecuteBtn();
  setStatus("running", "GATHERING INTEL...");
  log("white", "[STATUS] Connecting to agent...");

  if (sseConnection) sseConnection.close();

  try {
    const activeAgents = [];
    if (document.getElementById("rn-toggle").checked)  activeAgents.push("royal_navy");
    if (document.getElementById("raf-toggle").checked) activeAgents.push("royal_air_force");
    if (document.getElementById("ba-toggle").checked)  activeAgents.push("british_army");
    const res = await fetch("/api/gather", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agents: activeAgents }),
    });
    if (!res.ok) throw new Error("Server returned " + res.status);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\\n\\n");
      buffer = parts.pop();
      for (const part of parts) {
        if (!part.startsWith("data: ")) continue;
        try {
          const ev = JSON.parse(part.slice(6));
          handleSSEEvent(ev);
        } catch (_) {}
      }
    }
  } catch (e) {
    log("red", "[ERROR] " + e.message);
  }

  isRunning = false;
  updateExecuteBtn();
  setStatus("ready", "SYSTEM READY");
}"""

new_gather = """\
async function gatherFreshOSINT() {
  log("white", "[STATUS] Live agent execution not available in demo mode. Viewing cached data.");
}"""

src = src.replace(old_gather, new_gather)

# ── 5. Replace checkStatus (fetch /api/status) with no-op ────────────────────
old_status = """\
async function checkStatus() {
  try {
    const res = await fetch("/api/status");
    const s = await res.json();
    if (s.services) {
      // Multi-service response
      statusInfo.services = s.services;
      let hasData = false;
      let latestFile = null, latestMod = null;
      for (const [svc, info] of Object.entries(s.services)) {
        if (info.enriched_data_exists || info.osint_data_exists) {
          hasData = true;
          const f = info.enriched_data_file || info.osint_data_file;
          const m = info.enriched_data_modified || info.osint_data_modified;
          if (!latestMod || (m && m > latestMod)) { latestFile = f; latestMod = m; }
        }
      }
      statusInfo.existing = hasData;
      statusInfo.existingFile = latestFile;
      statusInfo.existingModified = latestMod;
    } else {
      // Legacy single-service response
      statusInfo.existing = s.enriched_data_exists || s.osint_data_exists;
      statusInfo.existingFile = s.enriched_data_file || s.osint_data_file || null;
      statusInfo.existingModified = s.enriched_data_modified || s.osint_data_modified || null;
    }
    updateSourceLabels();
    updateDatasourceUI();
  } catch (e) {
    log("dim", "[STATUS] Could not reach server.");
  }
}"""

new_status = """\
async function checkStatus() {
  // Demo mode: no server needed
  updateDatasourceUI();
}"""

src = src.replace(old_status, new_status)

# ── 6. Footer: prefix with DEMO MODE ─────────────────────────────────────────
old_footer = '  footer.innerHTML = `\n    <div id="footer-left">TOKENS: ${tokens} | UPDATED: ${updated}</div>'
new_footer = '  footer.innerHTML = `\n    <div id="footer-left">DEMO MODE &nbsp;|&nbsp; TOKENS: ${tokens} | UPDATED: ${updated}</div>'
src = src.replace(old_footer, new_footer)

# ── 7. Verify all substitutions worked ───────────────────────────────────────
checks = [
    ("EMBEDDED_DATA",                                       "data block injection"),
    ("Live agent execution not available in demo mode",      "gather stub"),
    ("Demo mode: data already embedded",                     "load stub"),
    ("Demo mode: no server needed",                          "status stub"),
    ("DEMO MODE",                                            "footer label"),
    ("typeNext",                                             "typewriter log"),
    ("services_loaded",                                      "multi-service metadata"),
]
ok = True
for token, label in checks:
    if token not in src:
        print(f"  ✗ FAILED: {label} (token: {token!r})")
        ok = False
    else:
        print(f"  ✓ {label}")

if not ok:
    print("\nBuild failed — check substitution strings.")
    sys.exit(1)

# ── 8. Write output ───────────────────────────────────────────────────────────
out = DOCS / "index.html"
out.write_text(src)
size_kb = out.stat().st_size / 1024
print(f"\nWritten: {out}  ({size_kb:.0f} KB)")
print("Done.")
