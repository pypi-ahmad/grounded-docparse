const fs = require('fs');
const path = require('path');

const root = 'D:/AI/Github/grounded-docparse';
const summaryByFile = {
  'batch.py': 'Coordinates batch document processing and aggregates per-document results for the application workflow.',
  'benchmark.py': 'Defines benchmark cases, evaluation metrics, and report generation for document parsing quality.',
  'cli.py': 'Provides the command-line interface for discovering inputs, selecting parser options, and writing results.',
  'models.py': 'Defines the Pydantic data models that carry document evidence, parsing state, and output contracts.',
  'render.py': 'Renders parsed document structures as Markdown, elements, combined results, and annotated PDF output.',
  'schema_store.py': 'Persists extraction schemas and validates schema metadata for reuse by document workflows.',
  'workspace_store.py': 'Persists workspace documents, batches, and parser artifacts for later retrieval.',
  'config.py': 'Defines parser configuration, OCR engine selection, validation, and environment-derived runtime settings.',
  'ocr_disagreement.py': 'Detects meaningful disagreement between OCR outputs to identify regions requiring attention.',
  'ocr_services.py': 'Selects and initializes managed local OCR engines from parser configuration.',
  'pipeline.py': 'Implements the end-to-end document parsing pipeline, including OCR, quality checks, recovery, rendering, and result assembly.'
};
function complexity(lines) { return lines > 200 ? 'complex' : lines >= 50 ? 'moderate' : 'simple'; }
function functionSummary(name, file) { return `Implements ${name} as part of ${file}'s document parsing workflow.`; }
function classSummary(name, file) { return `Defines ${name}, a structured component used by ${file}'s document parsing workflow.`; }
function build(index) {
  const input = JSON.parse(fs.readFileSync(path.join(root, '.ua/tmp', `ua-file-analyzer-input-${index}.json`), 'utf8'));
  const extracted = JSON.parse(fs.readFileSync(path.join(root, '.ua/tmp', `ua-file-extract-results-${index}.json`), 'utf8'));
  const nodes = [], edges = [];
  for (const result of extracted.results) {
    const rel = result.path, base = path.posix.basename(rel), fid = `file:${rel}`;
    nodes.push({ id: fid, type: 'file', name: base, filePath: rel, summary: summaryByFile[base] || `Provides ${base} implementation for the document parsing application.`, tags: ['python', 'document-parsing', 'implementation'], complexity: complexity(result.nonEmptyLines || result.totalLines || 0) });
    const exported = new Set((result.exports || []).map(x => x.name));
    for (const fn of result.functions || []) {
      const size = (fn.endLine || 0) - (fn.startLine || 0) + 1;
      if (size < 10 && !exported.has(fn.name)) continue;
      const id = `function:${rel}:${fn.name}`;
      nodes.push({ id, type: 'function', name: fn.name, filePath: rel, lineRange: [fn.startLine, fn.endLine], summary: functionSummary(fn.name, base), tags: ['python', 'document-parsing', 'function'], complexity: complexity(size) });
      edges.push({ source: fid, target: id, type: 'contains', direction: 'forward', weight: 1.0 });
      if (exported.has(fn.name)) edges.push({ source: fid, target: id, type: 'exports', direction: 'forward', weight: 0.8 });
    }
    for (const cls of result.classes || []) {
      const size = (cls.endLine || 0) - (cls.startLine || 0) + 1;
      if (size < 20 && (cls.methods || []).length < 2 && !exported.has(cls.name)) continue;
      const id = `class:${rel}:${cls.name}`;
      nodes.push({ id, type: 'class', name: cls.name, filePath: rel, lineRange: [cls.startLine, cls.endLine], summary: classSummary(cls.name, base), tags: ['python', 'document-parsing', 'data-model'], complexity: complexity(size) });
      edges.push({ source: fid, target: id, type: 'contains', direction: 'forward', weight: 1.0 });
      if (exported.has(cls.name)) edges.push({ source: fid, target: id, type: 'exports', direction: 'forward', weight: 0.8 });
    }
    for (const target of input.batchImportData[rel] || []) {
      edges.push({ source: fid, target: `file:${target}`, type: 'imports', direction: 'forward', weight: 0.7 });
    }
  }
  const payload = {nodes, edges};
  const output = path.join(root, '.ua/intermediate', `batch-${index}.json`);
  fs.writeFileSync(output, JSON.stringify(payload, null, 2) + '\n');
  JSON.parse(fs.readFileSync(output, 'utf8'));
  console.log(`batch-${index}: ${nodes.length} nodes, ${edges.length} edges`);
}
[1, 2, 3].forEach(build);
