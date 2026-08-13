const fs = require('fs');
fs.copyFileSync(process.argv[2], process.argv[3]);
fs.writeFileSync(process.argv[4], JSON.stringify({
  lastAnalyzedAt: new Date().toISOString(),
  gitCommitHash: process.argv[5],
  version: '1.0.0',
  analyzedFiles: Number(process.argv[6]),
}, null, 2));
