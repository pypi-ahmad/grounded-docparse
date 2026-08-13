const fs = require('fs');
const root = 'D:/AI/Github/grounded-docparse';
const graph = JSON.parse(fs.readFileSync(`${root}/.ua/intermediate/assembled-graph.json`, 'utf8'));
const previous = JSON.parse(fs.readFileSync(`${root}/.ua/knowledge-graph.json`, 'utf8'));
const fileTypes = new Set(['file','config','document','service','pipeline','table','schema','resource','endpoint']);
const valid = new Set(graph.nodes.filter(n => fileTypes.has(n.type)).map(n => n.id));
const used = new Set();
const layers = previous.layers.map(layer => ({...layer, nodeIds: layer.nodeIds.filter(id => valid.has(id) && !used.has(id) && (used.add(id), true))})).filter(layer => layer.nodeIds.length);
const missing = [...valid].filter(id => !used.has(id));
if (missing.length) layers.push({id:'layer:project-support',name:'Project Support',description:'Supporting repository files that do not fit the established processing, testing, evaluation, documentation, or operations layers.',nodeIds:missing.sort()});
if (layers.length < 3 || layers.length > 10) throw new Error(`invalid layer count ${layers.length}`);
const assigned = layers.flatMap(x => x.nodeIds);
if (assigned.length !== valid.size || new Set(assigned).size !== valid.size) throw new Error('layer assignment is incomplete or duplicated');
for (const layer of layers) {
  if (!/^layer:[a-z0-9]+(?:-[a-z0-9]+)*$/.test(layer.id) || !layer.name || !layer.description || !layer.nodeIds.length) throw new Error(`invalid layer ${layer.id}`);
}
fs.writeFileSync(`${root}/.ua/intermediate/layers.json`, JSON.stringify(layers, null, 2) + '\n');
console.log(`${layers.length} layers, ${assigned.length} files, ${missing.length} newly assigned`);
