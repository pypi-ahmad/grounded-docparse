const fs = require("fs");
const path = require("path");

const uaDir = process.argv[2];
const projectRoot = process.argv[3];
const commit = process.argv[4];
const assembledPath = path.join(uaDir, "intermediate", "assembled-graph.json");
const scanPath = path.join(uaDir, "intermediate", "scan-result.json");
const graph = JSON.parse(fs.readFileSync(assembledPath, "utf8"));
const scan = JSON.parse(fs.readFileSync(scanPath, "utf8"));

fs.writeFileSync(
  path.join(uaDir, "knowledge-graph.json"),
  JSON.stringify(graph, null, 2),
);
fs.writeFileSync(
  path.join(uaDir, "intermediate", "fingerprint-input.json"),
  JSON.stringify(
    {
      projectRoot,
      sourceFilePaths: scan.files.map(file => file.path),
      gitCommitHash: commit,
    },
    null,
    2,
  ),
);
