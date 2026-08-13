const fs = require("fs");
const path = require("path");

const uaDir = process.argv[2];
const commit = process.argv[3];
const graphPath = path.join(uaDir, "intermediate", "assembled-graph.json");
const graph = JSON.parse(fs.readFileSync(graphPath, "utf8"));
const scan = JSON.parse(
  fs.readFileSync(path.join(uaDir, "intermediate", "scan-result.json"), "utf8"),
);
const layers = JSON.parse(
  fs.readFileSync(path.join(uaDir, "intermediate", "layers.json"), "utf8"),
);
const tour = JSON.parse(
  fs.readFileSync(path.join(uaDir, "intermediate", "tour.json"), "utf8"),
);

const assembled = {
  version: "1.0.0",
  project: {
    name: scan.name,
    languages: scan.languages,
    frameworks: scan.frameworks,
    description: scan.description,
    analyzedAt: new Date().toISOString(),
    gitCommitHash: commit,
  },
  nodes: graph.nodes,
  edges: graph.edges,
  layers,
  tour,
};

fs.writeFileSync(graphPath, JSON.stringify(assembled, null, 2));
