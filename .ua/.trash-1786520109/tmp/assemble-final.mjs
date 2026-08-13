import fs from "node:fs";
import path from "node:path";

const projectRoot = process.argv[2];
const commitHash = process.argv[3];
if (!projectRoot || !commitHash) throw new Error("Usage: node assemble-final.mjs <project-root> <commit-hash>");

const uaDir = path.join(projectRoot, ".ua");
const intermediate = path.join(uaDir, "intermediate");
const scan = JSON.parse(fs.readFileSync(path.join(intermediate, "scan-result.json"), "utf8"));
const assembled = JSON.parse(fs.readFileSync(path.join(intermediate, "assembled-graph.json"), "utf8"));
const layers = JSON.parse(fs.readFileSync(path.join(intermediate, "layers.json"), "utf8"));
const tour = JSON.parse(fs.readFileSync(path.join(intermediate, "tour.json"), "utf8"));

const graph = {
  version: "1.0.0",
  project: {
    name: scan.name,
    languages: scan.languages,
    frameworks: scan.frameworks,
    description: scan.description,
    analyzedAt: new Date().toISOString(),
    gitCommitHash: commitHash,
  },
  nodes: assembled.nodes,
  edges: assembled.edges,
  layers,
  tour,
};
fs.writeFileSync(path.join(intermediate, "assembled-graph.json"), `${JSON.stringify(graph, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ nodes: graph.nodes.length, edges: graph.edges.length, layers: graph.layers.length, tour: graph.tour.length }));
