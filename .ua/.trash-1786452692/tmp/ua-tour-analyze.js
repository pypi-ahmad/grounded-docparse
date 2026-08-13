const fs = require('fs');
const [inputPath, outputPath] = process.argv.slice(2);
try {
  const data = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
  const nodes = data.nodes || [], edges = data.edges || [], layers = data.layers || [];
  const byId = new Map(nodes.map(n => [n.id, n]));
  const inCount = new Map(nodes.map(n => [n.id, 0]));
  const outCount = new Map(nodes.map(n => [n.id, 0]));
  const forward = new Map(nodes.map(n => [n.id, []]));
  for (const e of edges) {
    if (!byId.has(e.source) || !byId.has(e.target)) continue;
    inCount.set(e.target, inCount.get(e.target) + 1);
    outCount.set(e.source, outCount.get(e.source) + 1);
    if ((e.type === 'imports' || e.type === 'calls') && e.direction === 'forward') forward.get(e.source).push(e.target);
  }
  const rank = (map, key) => [...nodes].sort((a,b) => map.get(b.id)-map.get(a.id) || a.id.localeCompare(b.id)).slice(0,20).map(n => ({id:n.id,[key]:map.get(n.id),name:n.name}));
  const highOut = new Set(rank(outCount,'fanOut').slice(0,Math.max(1,Math.ceil(nodes.length*.1))).map(x=>x.id));
  const sortedIn=[...inCount.values()].sort((a,b)=>a-b), lowThreshold=sortedIn[Math.max(0,Math.floor(nodes.length*.25)-1)] ?? 0;
  const names = /^(index\.(ts|js)|main\.(ts|js|py|rs|go|c|cpp)|app\.(ts|js|py)|server\.(ts|js)|mod\.rs|manage\.py|wsgi\.py|asgi\.py|run\.py|__main__\.py|Application\.java|Main\.java|Program\.cs|config\.ru|index\.php|App\.swift|Application\.kt)$/;
  const candidates=nodes.map(n=>{let s=0; const p=n.filePath||''; if(names.test(n.name||''))s+=3; if(p.split('/').length<=2)s+=1; if(highOut.has(n.id))s+=1; if((inCount.get(n.id)||0)<=lowThreshold)s+=1; return {id:n.id,score:s,name:n.name,summary:n.summary};}).filter(x=>x.score>0).sort((a,b)=>b.score-a.score||a.id.localeCompare(b.id)).slice(0,5);
  const start=candidates[0]?.id || nodes[0]?.id || null, depthMap={}, order=[], byDepth={};
  if(start){const q=[start]; depthMap[start]=0; for(let i=0;i<q.length;i++){const id=q[i],d=depthMap[id];order.push(id);(byDepth[d]??=[]).push(id);for(const t of forward.get(id)||[])if(depthMap[t]===undefined){depthMap[t]=d+1;q.push(t)}}}
  const reciprocal=[]; for(const a of nodes){for(const b of forward.get(a.id)||[]){if((forward.get(b)||[]).includes(a.id)&&a.id<b){reciprocal.push({nodes:[a.id,b],edgeCount:2})}}}
  const out={scriptCompleted:true,entryPointCandidates:candidates,fanInRanking:rank(inCount,'fanIn'),fanOutRanking:rank(outCount,'fanOut'),bfsTraversal:{startNode:start,order,depthMap,byDepth},nonCodeFiles:{documentation:[],infrastructure:[],data:[],config:[]},clusters:reciprocal.slice(0,10),layers:{count:layers.length,list:layers},nodeSummaryIndex:Object.fromEntries(nodes.map(n=>[n.id,{name:n.name,type:n.type,summary:n.summary}])),totalNodes:nodes.length,totalEdges:edges.length};
  fs.writeFileSync(outputPath, JSON.stringify(out,null,2)+'\n');
} catch (err) { console.error(err.stack || String(err)); process.exit(1); }
