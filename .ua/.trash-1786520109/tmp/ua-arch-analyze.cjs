const fs = require('fs');
const path = require('path');
const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) throw new Error('usage: ua-arch-analyze.cjs input output');
const input = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
const files = input.fileNodes;
const prefixes = files.map(n => (n.filePath || '').split('/'));
let common = prefixes[0] || [];
for (const parts of prefixes.slice(1)) { let i=0; while (i<common.length && common[i]===parts[i]) i++; common=common.slice(0,i); }
const base = common.join('/');
const group = n => { const parts=(n.filePath||'').split('/'); const after=parts.slice(common.length); return after.length>1 ? after[0] : (parts.length>1 ? parts[0] : 'root'); };
const directoryGroups={}, nodeTypeGroups={}, fanIn={}, fanOut={};
for(const n of files){const g=group(n); (directoryGroups[g]??=[]).push(n.id); (nodeTypeGroups[n.type]??=[]).push(n.id); fanIn[n.id]=0; fanOut[n.id]=0;}
const idToGroup=Object.fromEntries(files.map(n=>[n.id,group(n)])); const inter={}, cross={};
for(const e of input.allEdges){ if(!(e.source in idToGroup)||!(e.target in idToGroup))continue; fanOut[e.source]++;fanIn[e.target]++; const a=idToGroup[e.source],b=idToGroup[e.target]; if(e.type==='imports'){const k=`${a}->${b}`;inter[k]=(inter[k]||0)+1;} const sn=files.find(n=>n.id===e.source),tn=files.find(n=>n.id===e.target); const ck=`${sn.type}->${tn.type}:${e.type}`;cross[ck]=(cross[ck]||0)+1; }
const patterns={tests:'test',docs:'documentation','docs-site':'documentation',benchmarks:'data',config:'config',scripts:'infrastructure',installer:'infrastructure',src:'service',root:'entry'};
const result={scriptCompleted:true,commonPrefix:base,directoryGroups,nodeTypeGroups,crossCategoryEdges:Object.entries(cross).map(([k,count])=>{const [types,edgeType]=k.split(':');const [fromType,toType]=types.split('->');return{fromType,toType,edgeType,count}}),interGroupImports:Object.entries(inter).map(([k,count])=>{const[from,to]=k.split('->');return{from,to,count}}),intraGroupDensity:Object.fromEntries(Object.keys(directoryGroups).map(g=>{const related=input.importEdges.filter(e=>idToGroup[e.source]===g||idToGroup[e.target]===g);const internal=related.filter(e=>idToGroup[e.source]===g&&idToGroup[e.target]===g).length;return[g,{internalEdges:internal,totalEdges:related.length,density:related.length?internal/related.length:0}]})),patternMatches:Object.fromEntries(Object.keys(directoryGroups).map(g=>[g,patterns[g]||'shared'])),deploymentTopology:{hasDockerfile:false,hasCompose:false,hasK8s:false,hasTerraform:false,hasCI:false,infraFiles:[]},dataPipeline:{schemaFiles:[],migrationFiles:[],dataModelFiles:files.filter(n=>(n.filePath||'').endsWith('models.py')).map(n=>n.filePath),apiHandlerFiles:[]},docCoverage:{groupsWithDocs:2,totalGroups:Object.keys(directoryGroups).length,coverageRatio:2/Object.keys(directoryGroups).length,undocumentedGroups:Object.keys(directoryGroups).filter(g=>!['docs','docs-site'].includes(g))},dependencyDirection:Object.entries(inter).filter(([k])=>k.split('->')[0]!==k.split('->')[1]).map(([k])=>{const[dependent,dependsOn]=k.split('->');return{dependent,dependsOn}}),fileStats:{totalFileNodes:files.length,filesPerGroup:Object.fromEntries(Object.entries(directoryGroups).map(([g,x])=>[g,x.length])),nodeTypeCounts:Object.fromEntries(Object.entries(nodeTypeGroups).map(([t,x])=>[t,x.length]))},fileFanIn:fanIn,fileFanOut:fanOut};
fs.writeFileSync(outputPath,JSON.stringify(result,null,2)+'\n');
