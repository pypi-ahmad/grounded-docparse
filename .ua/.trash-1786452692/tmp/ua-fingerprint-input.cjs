const fs = require('fs');
const scan = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
fs.writeFileSync(process.argv[3], JSON.stringify({
  projectRoot: process.argv[4],
  sourceFilePaths: scan.files.map(file => file.path),
  gitCommitHash: process.argv[5],
}, null, 2));
