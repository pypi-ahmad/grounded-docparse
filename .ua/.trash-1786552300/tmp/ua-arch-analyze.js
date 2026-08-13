const fs = require('fs');
const [inputPath, outputPath] = process.argv.slice(2);
try {
  const graph = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
  const levelTypes = new Set(['file', 'config', 'document', 'service', 'pipeline', 'table', 'schema', 'resource', 'endpoint']);
  const files = (graph.fileNodes || graph.nodes || []).filter(n => levelTypes.has(n.type));
  const ids = new Set(files.map(n => n.id));
  const edges = (graph.allEdges || graph.edges || []).filter(e => ids.has(e.source) && ids.has(e.target));
  const imports = (graph.importEdges || edges.filter(e => e.type === 'imports')).filter(e => ids.has(e.source) && ids.has(e.target));
  const paths = files.map(n => n.filePath || '').filter(Boolean);
  const split = p => p.split('/').filter(Boolean);
  const parts = paths.map(split);
  let prefix = [];
  for (let i = 0; parts.length && parts[0][i]; i++) { const value = parts[0][i]; if (parts.every(p => p[i] === value)) prefix.push(value); else break; }
  const groupOf = n => { const p = split(n.filePath || ''); const rest = p.slice(prefix.length); return rest.length > 1 ? rest[0] : (p.length > 1 ? p[0] : 'root'); };
  const byId = Object.fromEntries(files.map(n => [n.id, n]));
  const directoryGroups = {}, nodeTypeGroups = {}, fanIn = {}, fanOut = {};
  for (const n of files) { const g = groupOf(n); (directoryGroups[g] ||= []).push(n.id); (nodeTypeGroups[n.type] ||= []).push(n.id); fanIn[n.id] = 0; fanOut[n.id] = 0; }
  const groupPairs = new Map(), groupTotals = {}, groupInternal = {}, cross = new Map();
  for (const e of imports) { fanOut[e.source]++; fanIn[e.target]++; const a = groupOf(byId[e.source]), b = groupOf(byId[e.target]); groupTotals[a] = (groupTotals[a] || 0) + 1; groupTotals[b] = (groupTotals[b] || 0) + 1; if (a === b) groupInternal[a] = (groupInternal[a] || 0) + 1; const k = a+'\u0000'+b; groupPairs.set(k, (groupPairs.get(k)||0)+1); }
  for (const e of edges) { const k = `${byId[e.source].type}\u0000${byId[e.target].type}\u0000${e.type}`; cross.set(k, (cross.get(k)||0)+1); }
  const patternMap = {api:['routes','api','controllers','endpoints','handlers','routers','serializers','blueprints'],service:['services','core','lib','domain','logic','signals'],data:['models','db','data','persistence','repository','entities','migrations','sql','database','schema'],ui:['components','views','pages','ui','layouts','screens'],middleware:['middleware','plugins','interceptors','guards'],utility:['utils','helpers','common','shared','tools','pkg','templatetags'],config:['config','constants','env','settings','management','commands'],test:['__tests__','test','tests','spec','specs'],types:['types','interfaces','schemas','contracts','dtos','dto','request','response'],state:['store','state','reducers','actions','slices'],assets:['assets','static','public'],documentation:['docs','documentation','wiki'],infrastructure:['deploy','deployment','infra','infrastructure','k8s','kubernetes','helm','charts','terraform','tf','docker'], 'ci-cd':['.github','.gitlab','.circleci'],entry:['cmd','bin']};
  const patternMatches = {}; for (const g of Object.keys(directoryGroups)) for (const [label, names] of Object.entries(patternMap)) if (names.includes(g)) { patternMatches[g] = label; break; }
  const pathList = files.map(n => n.filePath || ''); const has = re => pathList.some(p => re.test(p));
  const infraFiles = pathList.filter(p => /(^|\/)(Dockerfile|docker-compose\..*|.*\.tf|.*\.tfvars|\.github\/workflows\/.*|.*\.(ya?ml))$/i.test(p));
  const docsByGroup = new Set(pathList.filter(p => /(^|\/)README\.md$/i.test(p)).map(p => groupOf(files.find(n => n.filePath===p))));
  const dependencyDirection = []; for (const [k,count] of groupPairs) { const [a,b]=k.split('\u0000'); if(a===b) continue; const reverse=groupPairs.get(b+'\u0000'+a)||0; if(count>reverse) dependencyDirection.push({dependent:a,dependsOn:b}); }
  const result = { scriptCompleted:true, directoryGroups, nodeTypeGroups,
    crossCategoryEdges:[...cross].map(([k,count])=>{const [fromType,toType,edgeType]=k.split('\u0000');return {fromType,toType,edgeType,count};}),
    interGroupImports:[...groupPairs].map(([k,count])=>{const [from,to]=k.split('\u0000');return {from,to,count};}),
    intraGroupDensity:Object.fromEntries(Object.keys(directoryGroups).map(g=>[g,{internalEdges:groupInternal[g]||0,totalEdges:groupTotals[g]||0,density:groupTotals[g]?(groupInternal[g]||0)/groupTotals[g]:0}])), patternMatches,
    deploymentTopology:{hasDockerfile:has(/(^|\/)Dockerfile/i),hasCompose:has(/docker-compose/i),hasK8s:has(/(^|\/)(k8s|kubernetes)\//i),hasTerraform:has(/\.tf(vars)?$/i),hasCI:has(/(^|\/)\.github\/workflows\//i),infraFiles},
    dataPipeline:{schemaFiles:pathList.filter(p=>/\.(graphql|gql|proto)$/i.test(p)),migrationFiles:pathList.filter(p=>/migrations?\//i.test(p)),dataModelFiles:pathList.filter(p=>/(models?|data|schema)\//i.test(p)),apiHandlerFiles:pathList.filter(p=>/(routes?|api|controllers?|handlers?)\//i.test(p))},
    docCoverage:{groupsWithDocs:docsByGroup.size,totalGroups:Object.keys(directoryGroups).length,coverageRatio:Object.keys(directoryGroups).length?docsByGroup.size/Object.keys(directoryGroups).length:0,undocumentedGroups:Object.keys(directoryGroups).filter(g=>!docsByGroup.has(g))}, dependencyDirection,
    fileStats:{totalFileNodes:files.length,filesPerGroup:Object.fromEntries(Object.entries(directoryGroups).map(([g,x])=>[g,x.length])),nodeTypeCounts:Object.fromEntries(Object.entries(nodeTypeGroups).map(([t,x])=>[t,x.length]))},fileFanIn:fanIn,fileFanOut:fanOut };
  fs.writeFileSync(outputPath, JSON.stringify(result,null,2));
} catch (err) { console.error(err.stack || err.message); process.exit(1); }
