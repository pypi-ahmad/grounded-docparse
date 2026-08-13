const fs = require('fs');
try {
  const [inputPath, outputPath] = process.argv.slice(2);
  if (!inputPath || !outputPath) throw new Error('Expected input and output paths');
  const { fileNodes, importEdges, allEdges } = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
  const ids = new Set(fileNodes.map(n => n.id));
  const commonParts = fileNodes.map(n => n.filePath.split('/'));
  let prefix = []; for (let i = 0; ; i++) { const v = commonParts[0]?.[i]; if (!v || !commonParts.every(p => p[i] === v)) break; prefix.push(v); }
  const group = n => { const p = n.filePath.split('/'); const rest = p.slice(prefix.length); return rest.length > 1 ? rest[0] : (p.length > 1 ? p[0] : 'root'); };
  const directoryGroups = {}, nodeTypeGroups = {}, nodeGroup = {};
  for (const n of fileNodes) { const g=group(n); (directoryGroups[g]??=[]).push(n.id); (nodeTypeGroups[n.type]??=[]).push(n.id); nodeGroup[n.id]=g; }
  const fanIn={}, fanOut={}; for(const n of fileNodes){fanIn[n.id]=0;fanOut[n.id]=0;}
  const inter={}, intra={}; for(const g of Object.keys(directoryGroups)) intra[g]={internalEdges:0,totalEdges:0,density:0};
  for(const e of importEdges.filter(e=>ids.has(e.source)&&ids.has(e.target))){fanOut[e.source]++;fanIn[e.target]++; const a=nodeGroup[e.source],b=nodeGroup[e.target],k=`${a}->${b}`;inter[k]=(inter[k]||0)+1;intra[a].totalEdges++;intra[b].totalEdges++;if(a===b)intra[a].internalEdges++;}
  for(const x of Object.values(intra))x.density=x.totalEdges?Number((x.internalEdges/x.totalEdges).toFixed(2)):0;
  const types={}; for(const e of allEdges){const a=fileNodes.find(n=>n.id===e.source),b=fileNodes.find(n=>n.id===e.target);if(a&&b){const k=`${a.type}|${b.type}|${e.type}`;types[k]=(types[k]||0)+1;}}
  const crossCategoryEdges=Object.entries(types).map(([k,count])=>{const [fromType,toType,edgeType]=k.split('|');return{fromType,toType,edgeType,count};});
  const labels={tests:'test',docs:'documentation','docs-site':'documentation',benchmarks:'data',config:'config',scripts:'infrastructure',installer:'infrastructure',src:'service',components:'ui',app_pages:'ui',root:'root',presentations:'documentation','paddle-runtime':'infrastructure'};
  const patternMatches={};for(const g of Object.keys(directoryGroups))patternMatches[g]=labels[g]||'root';
  const paths=fileNodes.map(n=>n.filePath), has=p=>paths.some(p); const infraFiles=paths.filter(p=>/\.github\/workflows|installer\/|scripts\/wsl|\.iss$/.test(p));
  const dataPipeline={schemaFiles:paths.filter(p=>/schema|\.schema\.json$/.test(p)),migrationFiles:paths.filter(p=>/migration/.test(p)),dataModelFiles:paths.filter(p=>/models\.py$/.test(p)),apiHandlerFiles:paths.filter(p=>/cli\.py$/.test(p))};
  const docGroups=new Set(fileNodes.filter(n=>n.type==='document').map(n=>nodeGroup[n.id])); const allGroups=Object.keys(directoryGroups);
  const direction=[];for(const [k,count] of Object.entries(inter)){const[a,b]=k.split('->');if(a!==b&&count>(inter[`${b}->${a}`]||0))direction.push({dependent:a,dependsOn:b});}
  const out={scriptCompleted:true,directoryGroups,nodeTypeGroups,crossCategoryEdges,interGroupImports:Object.entries(inter).map(([k,count])=>{const[from,to]=k.split('->');return{from,to,count};}),intraGroupDensity:intra,patternMatches,deploymentTopology:{hasDockerfile:false,hasCompose:false,hasK8s:false,hasTerraform:false,hasCI:paths.some(p=>p.startsWith('.github/')),infraFiles},dataPipeline,docCoverage:{groupsWithDocs:docGroups.size,totalGroups:allGroups.length,coverageRatio:Number((docGroups.size/allGroups.length).toFixed(2)),undocumentedGroups:allGroups.filter(g=>!docGroups.has(g))},dependencyDirection:direction,fileStats:{totalFileNodes:fileNodes.length,filesPerGroup:Object.fromEntries(Object.entries(directoryGroups).map(([k,v])=>[k,v.length])),nodeTypeCounts:Object.fromEntries(Object.entries(nodeTypeGroups).map(([k,v])=>[k,v.length]))},fileFanIn:fanIn,fileFanOut:fanOut};
  fs.writeFileSync(outputPath, JSON.stringify(out,null,2));
} catch (err) { console.error(err.stack || err.message); process.exit(1); }
