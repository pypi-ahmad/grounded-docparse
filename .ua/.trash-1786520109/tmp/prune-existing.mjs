import fs from "node:fs";
import path from "node:path";

const projectRoot = process.argv[2];
if (!projectRoot) throw new Error("Usage: node prune-existing.mjs <project-root>");

const uaDir = path.join(projectRoot, ".ua");
const graph = JSON.parse(fs.readFileSync(path.join(uaDir, "knowledge-graph.json"), "utf8"));
const changed = new Set(
  fs.readFileSync(path.join(uaDir, "tmp", "changed-files.txt"), "utf8")
    .split(/\r?\n/)
    .map((value) => value.trim().replaceAll("\\", "/"))
    .filter(Boolean),
);

const removedIds = new Set(
  graph.nodes
    .filter((node) => node.filePath && changed.has(node.filePath.replaceAll("\\", "/")))
    .map((node) => node.id),
);
const nodes = graph.nodes.filter((node) => !removedIds.has(node.id));
const edges = graph.edges.filter(
  (edge) => !removedIds.has(edge.source) && !removedIds.has(edge.target),
);

fs.writeFileSync(
  path.join(uaDir, "intermediate", "batch-existing.json"),
  `${JSON.stringify({ nodes, edges }, null, 2)}\n`,
  "utf8",
);
console.log(JSON.stringify({ changedFiles: changed.size, removedNodes: removedIds.size, retainedNodes: nodes.length, retainedEdges: edges.length }));
