const fs = require('fs');
const root = 'D:/AI/Github/grounded-docparse';
const graph=JSON.parse(fs.readFileSync(`${root}/.ua/intermediate/assembled-graph.json`,'utf8'));
const types=new Set(['file','config','document','service','pipeline','table','schema','resource','endpoint']);
const fileNodes=graph.nodes.filter(n=>types.has(n.type));
const fileIds=new Set(fileNodes.map(n=>n.id));
const allEdges=graph.edges.filter(e=>fileIds.has(e.source)&&fileIds.has(e.target));
fs.writeFileSync(`${root}/.ua/tmp/ua-arch-input.json`,JSON.stringify({fileNodes,importEdges:allEdges.filter(e=>e.type==='imports'),allEdges},null,2)+'\n');
