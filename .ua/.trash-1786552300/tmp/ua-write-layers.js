const fs = require('fs');
const [inputPath, outputPath] = process.argv.slice(2);
const graph = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
const allowed = new Set(['file','config','document','service','pipeline','table','schema','resource','endpoint']);
const files = graph.nodes.filter(n => allowed.has(n.type));
const layers = [
  ['layer:document-processing', 'Document Processing Application', 'The Streamlit entry point and grounded-docparse package that ingest documents, run OCR/native extraction, preserve evidence, and present results.'],
  ['layer:quality-and-evaluation', 'Quality and Evaluation', 'Pytest coverage and benchmark assets that verify parsing behavior, evidence grounding, and OCR quality.'],
  ['layer:documentation-and-presentations', 'Documentation and Presentations', 'Contributor, user, site, and presentation materials describing grounded-docparse and its workflows.'],
  ['layer:runtime-and-delivery', 'Runtime and Delivery Tooling', 'Launchers, runtime configuration, installation, packaging, and operational automation for local document-processing services.'],
  ['layer:generated-analysis-artifacts', 'Generated Analysis Artifacts', 'Persisted Understand Anything, Graphify, and code-graph outputs retained in this repository for architecture exploration.'],
  ['layer:project-governance', 'Project Governance', 'Repository-level metadata and files not owned by the runtime, documentation, tests, or generated analysis outputs.'],
].map(([id,name,description]) => ({id,name,description,nodeIds:[]}));
const layer = Object.fromEntries(layers.map(x => [x.id,x]));
for (const n of files) {
  const p = n.filePath || '';
  let id;
  if (/^(\.ua|graphify-out|\.codegraph|\.code-review-graph)\//.test(p)) id='layer:generated-analysis-artifacts';
  else if (/^(tests|benchmarks)\//.test(p)) id='layer:quality-and-evaluation';
  else if (n.type === 'document' || /^(docs|docs-site|presentations)\//.test(p)) id='layer:documentation-and-presentations';
  else if (p === 'streamlit_app.py' || p.startsWith('src/')) id='layer:document-processing';
  else if (/^(scripts|installer|config|\.streamlit|\.github)\//.test(p) || /^(Launch-|Setup-)/.test(p) || ['pyproject.toml','.env.example'].includes(p)) id='layer:runtime-and-delivery';
  else id='layer:project-governance';
  layer[id].nodeIds.push(n.id);
}
const all = layers.flatMap(x=>x.nodeIds);
const unique = new Set(all);
if (layers.some(x=>!x.nodeIds.length) || all.length!==files.length || unique.size!==files.length || files.some(n=>!unique.has(n.id))) throw new Error(`invalid assignment: files=${files.length}, assigned=${all.length}, unique=${unique.size}`);
fs.writeFileSync(outputPath, JSON.stringify(layers,null,2));
console.log(JSON.stringify(Object.fromEntries(layers.map(x=>[x.name,x.nodeIds.length]))));
