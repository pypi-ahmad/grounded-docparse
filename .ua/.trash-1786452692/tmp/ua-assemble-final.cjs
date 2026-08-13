const fs = require('fs');

const base = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const scan = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const rawLayers = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));
const rawTour = JSON.parse(fs.readFileSync(process.argv[5], 'utf8'));
const output = process.argv[6];
const commit = process.argv[7];
const nodeIds = new Set(base.nodes.map(node => node.id));
const prefixes = /^(file|config|document|service|pipeline|table|schema|resource|endpoint):/;
const kebab = value => String(value || 'unnamed').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const ref = value => prefixes.test(value) ? value : `file:${value}`;
const layersInput = Array.isArray(rawLayers) ? rawLayers : rawLayers.layers || [];
const tourInput = Array.isArray(rawTour) ? rawTour : rawTour.steps || [];

const layers = layersInput.map((layer, index) => {
  const source = layer.nodeIds || layer.nodes || [];
  const nodeRefs = source.map(value => typeof value === 'string' ? value : value.id).filter(Boolean).map(ref).filter(id => nodeIds.has(id));
  return {
    id: layer.id || `layer:${kebab(layer.name || index + 1)}`,
    name: layer.name || `Layer ${index + 1}`,
    description: layer.description || 'No description available',
    nodeIds: [...new Set(nodeRefs)],
  };
});

const tour = tourInput.map((step, index) => {
  const source = step.nodeIds || step.nodesToInspect || [];
  const normalized = {
    order: Number(step.order || index + 1),
    title: step.title || `Step ${index + 1}`,
    description: step.description || step.whyItMatters || 'No description available',
    nodeIds: [...new Set(source.map(ref).filter(id => nodeIds.has(id)))],
  };
  if (typeof step.languageLesson === 'string') normalized.languageLesson = step.languageLesson;
  return normalized;
}).sort((a, b) => a.order - b.order).map((step, index) => ({ ...step, order: index + 1 }));

const graph = {
  version: '1.0.0',
  project: {
    name: scan.name,
    languages: scan.languages,
    frameworks: scan.frameworks,
    description: scan.description,
    analyzedAt: new Date().toISOString(),
    gitCommitHash: commit,
  },
  nodes: base.nodes,
  edges: base.edges,
  layers,
  tour,
};
fs.writeFileSync(output, JSON.stringify(graph, null, 2));
