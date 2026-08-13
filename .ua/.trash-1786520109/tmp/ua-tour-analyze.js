const fs = require('fs');
const [,, graphPath, layersPath, outputPath] = process.argv;
if (!graphPath || !layersPath || !outputPath) throw new Error('usage: graph layers output');
const graph = JSON.parse(fs.readFileSync(graphPath, 'utf8'));
const layers = JSON.parse(fs.readFileSync(layersPath, 'utf8'));
const nodes = graph.nodes || [];
const edges = graph.edges || [];
const byId = new Map(nodes.map(n => [n.id, n]));
const ins = new Map(nodes.map(n => [n.id, 0]));
const outs = new Map(nodes.map(n => [n.id, 0]));
for (const e of edges) { if (ins.has(e.target)) ins.set(e.target, ins.get(e.target)+1); if (outs.has(e.source)) outs.set(e.source, outs.get(e.source)+1); }
const rank = (m, key) => [...m].map(([id, value]) => ({id, [key]:value, name:byId.get(id).name})).sort((a,b)=>b[key]-a[key] || a.id.localeCompare(b.id)).slice(0,20);
const candidates = nodes.map(n => { let score=0; const p=n.filePath||''; if(n.id==='document:README.md') score+=5; if(n.type==='file' && (/^(streamlit_app\.py|.*\/cli\.py|main\.(py|js|ts)|app\.(py|js|ts)|__main__\.py)$/.test(p))) score+=3; if(n.type==='file' && !p.includes('/')) score++; if((outs.get(n.id)||0)>0) score++; return {id:n.id,score,name:n.name,summary:n.summary}; }).filter(x=>x.score>0).sort((a,b)=>b.score-a.score||a.id.localeCompare(b.id)).slice(0,5);
const start='file:streamlit_app.py'; const allowed=new Set(['imports','calls']); const queue=[start], depth={[start]:0}, order=[];
while(queue.length){const id=queue.shift(); order.push(id); for(const e of edges){if(e.source===id && allowed.has(e.type) && byId.has(e.target) && depth[e.target]===undefined){depth[e.target]=depth[id]+1;queue.push(e.target);}}}
const byDepth={}; for(const id of order){const d=depth[id];(byDepth[d]??=[]).push(id);}
const classified={documentation:[],infrastructure:[],data:[],config:[]}; for(const n of nodes){if(n.type==='document')classified.documentation.push({id:n.id,name:n.name,summary:n.summary}); else if(['service','pipeline','resource'].includes(n.type))classified.infrastructure.push({id:n.id,name:n.name,summary:n.summary}); else if(['table','schema','endpoint'].includes(n.type))classified.data.push({id:n.id,name:n.name,summary:n.summary}); else if(n.type==='config')classified.config.push({id:n.id,name:n.name,summary:n.summary});}
const index=Object.fromEntries(nodes.map(n=>[n.id,{name:n.name,type:n.type,summary:n.summary}]));
fs.writeFileSync(outputPath, JSON.stringify({scriptCompleted:true,entryPointCandidates:candidates,fanInRanking:rank(ins,'fanIn'),fanOutRanking:rank(outs,'fanOut'),bfsTraversal:{startNode:start,order,depthMap:depth,byDepth},nonCodeFiles:classified,clusters:[],layers:{count:layers.length,list:layers.map(({id,name,description})=>({id,name,description}))},nodeSummaryIndex:index,totalNodes:nodes.length,totalEdges:edges.length},null,2));
