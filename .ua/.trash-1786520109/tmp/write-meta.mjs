import fs from "node:fs";
import path from "node:path";

const projectRoot = process.argv[2];
const commitHash = process.argv[3];
if (!projectRoot || !commitHash) throw new Error("Usage: node write-meta.mjs <project-root> <commit-hash>");
const uaDir = path.join(projectRoot, ".ua");
const scan = JSON.parse(fs.readFileSync(path.join(uaDir, "intermediate", "scan-result.json"), "utf8"));
const meta = {
  lastAnalyzedAt: new Date().toISOString(),
  gitCommitHash: commitHash,
  version: "1.0.0",
  analyzedFiles: scan.files.length,
};
fs.writeFileSync(path.join(uaDir, "meta.json"), `${JSON.stringify(meta, null, 2)}\n`, "utf8");
console.log(JSON.stringify(meta));
