const fs = require("fs");

function fail(error) {
  process.stderr.write(`${error instanceof Error ? error.message : error}\n`);
  process.exit(1);
}

try {
  const [inputPath, outputPath] = process.argv.slice(2);
  if (!inputPath || !outputPath) fail("Usage: ua-tour-analyze.js INPUT OUTPUT");
  const graph = JSON.parse(fs.readFileSync(inputPath, "utf8"));
  if (!Array.isArray(graph.nodes) || !Array.isArray(graph.edges) || !Array.isArray(graph.layers)) {
    fail("Input must contain nodes, edges, and layers arrays");
  }

  const nodes = graph.nodes;
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const inbound = new Map(nodes.map((node) => [node.id, 0]));
  const outbound = new Map(nodes.map((node) => [node.id, 0]));
  const forward = new Map(nodes.map((node) => [node.id, []]));
  for (const edge of graph.edges) {
    if (!byId.has(edge.source) || !byId.has(edge.target)) continue;
    outbound.set(edge.source, outbound.get(edge.source) + 1);
    inbound.set(edge.target, inbound.get(edge.target) + 1);
    if (edge.type === "imports" || edge.type === "calls") forward.get(edge.source).push(edge.target);
  }
  const ranked = (counts, field) => nodes.map((node) => ({ id: node.id, [field]: counts.get(node.id), name: node.name }))
    .sort((a, b) => b[field] - a[field] || a.id.localeCompare(b.id)).slice(0, 20);
  const fanInRanking = ranked(inbound, "fanIn");
  const fanOutRanking = ranked(outbound, "fanOut");
  const outs = [...outbound.values()].sort((a, b) => a - b);
  const ins = [...inbound.values()].sort((a, b) => a - b);
  const highOut = outs[Math.max(0, Math.ceil(outs.length * 0.9) - 1)] ?? 0;
  const lowIn = ins[Math.min(ins.length - 1, Math.floor(ins.length * 0.25))] ?? 0;
  const names = new Set(["index.ts", "index.js", "main.ts", "main.js", "app.ts", "app.js", "server.ts", "server.js", "mod.rs", "main.go", "main.py", "main.rs", "manage.py", "app.py", "wsgi.py", "asgi.py", "run.py", "__main__.py", "Application.java", "Main.java", "Program.cs", "config.ru", "index.php", "App.swift", "Application.kt", "main.cpp", "main.c"]);
  const entryPointCandidates = nodes.map((node) => {
    const path = node.filePath || "";
    const depth = path.split("/").length;
    let score = 0;
    if (node.type === "file") {
      if (names.has(node.name)) score += 3;
      if (depth <= 2) score += 1;
      if ((outbound.get(node.id) ?? 0) >= highOut) score += 1;
      if ((inbound.get(node.id) ?? 0) <= lowIn) score += 1;
    }
    if (node.type === "document") {
      if (path === "README.md") score += 5;
      else if (/^[^/]+\.md$/i.test(path)) score += 2;
    }
    return { id: node.id, score, name: node.name, summary: node.summary };
  }).filter((candidate) => candidate.score > 0)
    .sort((a, b) => b.score - a.score || a.id.localeCompare(b.id)).slice(0, 5);
  const start = entryPointCandidates.find((candidate) => byId.get(candidate.id)?.type === "file")?.id || null;
  const order = [], depthMap = {}, byDepth = {};
  if (start) {
    const queue = [[start, 0]], seen = new Set([start]);
    while (queue.length) {
      const [id, depth] = queue.shift();
      order.push(id); depthMap[id] = depth; (byDepth[depth] ||= []).push(id);
      for (const target of forward.get(id) || []) if (!seen.has(target)) { seen.add(target); queue.push([target, depth + 1]); }
    }
  }
  const nonCodeFiles = { documentation: [], infrastructure: [], data: [], config: [] };
  for (const node of nodes) {
    const item = { id: node.id, name: node.name, type: node.type, summary: node.summary };
    if (node.type === "document") nonCodeFiles.documentation.push(item);
    else if (["service", "pipeline", "resource"].includes(node.type)) nonCodeFiles.infrastructure.push(item);
    else if (["table", "schema", "endpoint"].includes(node.type)) nonCodeFiles.data.push(item);
    else if (node.type === "config") nonCodeFiles.config.push(item);
  }
  const pairCounts = new Map();
  const directed = new Set(graph.edges.filter((edge) => byId.has(edge.source) && byId.has(edge.target))
    .map((edge) => `${edge.type}:${edge.source}->${edge.target}`));
  for (const edge of graph.edges) {
    if (!["imports", "calls"].includes(edge.type)) continue;
    if (!directed.has(`${edge.type}:${edge.target}->${edge.source}`)) continue;
    const pair = [edge.source, edge.target].sort().join("|");
    pairCounts.set(pair, (pairCounts.get(pair) || 0) + 1);
  }
  const clusters = [...pairCounts].map(([pair, edgeCount]) => ({ nodes: pair.split("|"), edgeCount }))
    .sort((a, b) => b.edgeCount - a.edgeCount).slice(0, 10);
  const nodeSummaryIndex = Object.fromEntries(nodes.map((node) => [node.id, { name: node.name, type: node.type, summary: node.summary }]));
  fs.writeFileSync(outputPath, JSON.stringify({ scriptCompleted: true, entryPointCandidates, fanInRanking, fanOutRanking, bfsTraversal: { startNode: start, order, depthMap, byDepth }, nonCodeFiles, clusters, layers: { count: graph.layers.length, list: graph.layers.map(({ id, name, description }) => ({ id, name, description })) }, nodeSummaryIndex, totalNodes: nodes.length, totalEdges: graph.edges.length }, null, 2));
} catch (error) { fail(error); }
