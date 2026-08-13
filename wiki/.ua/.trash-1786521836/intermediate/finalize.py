from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


WIKI_ROOT = Path(__file__).resolve().parents[2]
UA_DIR = WIKI_ROOT / ".ua"
ASSEMBLED = UA_DIR / "intermediate" / "assembled-graph.json"
REQUIRED = {"id", "type", "name", "summary", "tags", "complexity"}

graph = json.loads(ASSEMBLED.read_text(encoding="utf-8"))
issues: list[str] = []
node_ids: set[str] = set()
for index, node in enumerate(graph.get("nodes", [])):
    missing = sorted(REQUIRED - node.keys())
    if missing:
        issues.append(f"node[{index}] missing {', '.join(missing)}")
    node_id = node.get("id")
    if node_id in node_ids:
        issues.append(f"duplicate node id: {node_id}")
    if node_id:
        node_ids.add(node_id)

valid_edges = []
dangling = []
for edge in graph.get("edges", []):
    if edge.get("source") in node_ids and edge.get("target") in node_ids:
        valid_edges.append(edge)
    else:
        dangling.append(edge)
graph["edges"] = valid_edges
if issues:
    raise SystemExit("\n".join(issues))

(UA_DIR / "knowledge-graph.json").write_text(
    json.dumps(graph, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
commit = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=WIKI_ROOT.parent,
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
meta = {
    "lastAnalyzedAt": datetime.now(UTC).isoformat(),
    "gitCommitHash": commit,
    "version": "1.0.0",
    "analyzedFiles": 24,
}
(UA_DIR / "meta.json").write_text(
    json.dumps(meta, indent=2) + "\n", encoding="utf-8"
)
print(
    json.dumps(
        {
            "nodes": len(graph["nodes"]),
            "edges": len(graph["edges"]),
            "dangling_removed": len(dangling),
            "layers": len(graph.get("layers", [])),
            "tour_steps": len(graph.get("tour", [])),
        }
    )
)
