import fs from "node:fs";
import path from "node:path";

const projectRoot = process.argv[2];
const commitHash = process.argv[3];
if (!projectRoot || !commitHash) throw new Error("Usage: node prepare-save.mjs <project-root> <commit-hash>");
const uaDir = path.join(projectRoot, ".ua");
const intermediate = path.join(uaDir, "intermediate");
const graphPath = path.join(intermediate, "assembled-graph.json");
const graph = JSON.parse(fs.readFileSync(graphPath, "utf8"));
const scan = JSON.parse(fs.readFileSync(path.join(intermediate, "scan-result.json"), "utf8"));

fs.writeFileSync(path.join(uaDir, "knowledge-graph.json"), `${JSON.stringify(graph, null, 2)}\n`, "utf8");
fs.writeFileSync(
  path.join(intermediate, "fingerprint-input.json"),
  `${JSON.stringify({ projectRoot, sourceFilePaths: scan.files.map((file) => file.path), gitCommitHash: commitHash }, null, 2)}\n`,
  "utf8",
);
console.log(JSON.stringify({ files: scan.files.length, graphPath: path.join(uaDir, "knowledge-graph.json") }));
