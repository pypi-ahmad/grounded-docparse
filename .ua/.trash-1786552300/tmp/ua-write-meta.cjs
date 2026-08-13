const fs = require("fs");
const path = require("path");

const uaDir = process.argv[2];
const commit = process.argv[3];
const analyzedFiles = Number(process.argv[4]);
fs.writeFileSync(
  path.join(uaDir, "meta.json"),
  JSON.stringify(
    {
      lastAnalyzedAt: new Date().toISOString(),
      gitCommitHash: commit,
      version: "1.0.0",
      analyzedFiles,
    },
    null,
    2,
  ) + "\n",
);
