"use strict";
cytoscape.use(cytoscapeFcose);

const TYPE_COLORS = {
  domain: "#ff3621", genie_agent: "#ff6a4d", table: "#00a6b2", metric_view: "#f5b841",
  measure: "#d98a2b", column: "#4a6274", glossary: "#a78bfa", schema: "#6b7280", catalog: "#6b7280",
};
const TYPE_LABELS = {
  domain: "Domain", genie_agent: "Genie", table: "Tables", metric_view: "Metric views",
  measure: "Measures", column: "Columns", glossary: "Glossary", schema: "Schema", catalog: "Catalog",
};
const EDGE_COLORS = { contains: "#2c3648", fk: "#00a6b2", defines: "#f5b841", means: "#a78bfa", tagged: "#ff3621", uses: "#ff6a4d" };
const FILTER_TYPES = ["domain", "genie_agent", "table", "metric_view", "measure", "column", "glossary", "schema"];
const EXAMPLES = [
  "Show loss ratio, combined ratio, claim frequency and claim severity by line of business",
  "Compare earned premium, incurred loss and loss ratio by region",
  "For each cause of loss, show claim count, incurred loss, case reserves and average severity",
  "List the 10 largest claims with line of business, cause of loss, paid loss and case reserve",
  "What is the loss ratio by customer industry?",
];
const TABS = [["ask", "Ask"], ["detail", "Detail"], ["assets", "Assets"], ["rules", "Business Rules"], ["glossary", "Glossary"], ["hierarchy", "Hierarchy"], ["ontorank", "OntoRank"]];

const S = { graph: null, ontorank: null, usage: {}, tab: "ask", selected: null, loading: false, ask: null,
  filters: Object.fromEntries(FILTER_TYPES.map(t => [t, true])), recomputing: false };
let cy = null, pulseTimer = null;

const esc = s => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const mdBold = s => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\n/g, "<br/>");
const $ = id => document.getElementById(id);

function nodeSize(ntype, usage) {
  const base = { domain: 78, genie_agent: 62, table: 42, metric_view: 44, measure: 24, column: 18, glossary: 30, schema: 36, catalog: 36 };
  return (base[ntype] || 26) + Math.min(usage * 9, 46);
}

function buildStyle() {
  return [
    { selector: "node", style: {
      "background-color": n => TYPE_COLORS[n.data("ntype")] || "#888",
      width: n => n.data("size") || 26, height: n => n.data("size") || 26,
      label: "data(label)", color: "#dfe4ee",
      "font-size": n => { const t = n.data("ntype"); if (t === "domain" || t === "genie_agent") return 13; if (t === "table" || t === "metric_view") return 11; return 8; },
      "text-valign": "center", "text-halign": "center",
      "text-margin-y": n => { const t = n.data("ntype"); return (t === "column" || t === "measure") ? 0 : (n.data("size") || 26) / 2 + 8; },
      "text-outline-color": "#0b0e14", "text-outline-width": 2, "text-wrap": "wrap", "text-max-width": "120px",
      "overlay-color": "#f5b841", "overlay-opacity": 0, "overlay-padding": 8, "border-width": 0,
      shape: n => { const t = n.data("ntype"); if (t === "domain") return "hexagon"; if (t === "genie_agent") return "diamond"; if (t === "metric_view" || t === "table") return "round-rectangle"; if (t === "glossary") return "tag"; return "ellipse"; },
    }},
    { selector: "edge", style: {
      width: e => (e.data("etype") === "contains" ? 1 : 1.6),
      "line-color": e => EDGE_COLORS[e.data("etype")] || "#333",
      "target-arrow-color": e => EDGE_COLORS[e.data("etype")] || "#333",
      "target-arrow-shape": e => (["fk", "means", "uses"].includes(e.data("etype")) ? "triangle" : "none"),
      "curve-style": "bezier", opacity: 0.55,
      "line-style": e => (e.data("etype") === "tagged" ? "dashed" : "solid"),
    }},
    { selector: "node.faded", style: { opacity: 0.12 } },
    { selector: "edge.faded", style: { opacity: 0.04 } },
    { selector: "node.hl", style: { "border-width": 4, "border-color": "#ff3621", "z-index": 999, opacity: 1 } },
    { selector: "edge.hl-edge", style: { "line-color": "#ff3621", "target-arrow-color": "#ff3621", width: 4, opacity: 1, "z-index": 999 } },
  ];
}

function initCy() {
  cy = cytoscape({
    container: $("cy"),
    elements: { nodes: S.graph.nodes, edges: S.graph.edges },
    style: buildStyle(),
    layout: { name: "fcose", quality: "proof", animate: true, randomize: true, nodeRepulsion: 9000, idealEdgeLength: 90, nestingFactor: 0.9 },
    wheelSensitivity: 0.2,
  });
  cy.on("tap", "node", e => { S.selected = e.target.data(); S.tab = "detail"; renderTabs(); renderBody(); });
  cy.on("dbltap", "node", e => { cy.animate({ fit: { eles: e.target.closedNeighborhood(), padding: 60 }, duration: 500 }); });
  setTimeout(applySizes, 400);
}

function applySizes() {
  if (!cy) return;
  cy.nodes().forEach(n => { const u = S.usage[n.id()] || 0; n.data("usage", u); n.data("size", nodeSize(n.data("ntype"), u)); });
}

function applyFilters() {
  if (!cy) return;
  cy.nodes().forEach(n => { const t = n.data("ntype"); const show = S.filters[t] !== false || t === "catalog"; n.style("display", show ? "element" : "none"); });
}

function stopPulse() { if (pulseTimer) { clearInterval(pulseTimer); pulseTimer = null; } }
function clearHighlight() { if (!cy) return; stopPulse(); cy.elements().removeClass("hl faded hl-edge"); cy.nodes().style("overlay-opacity", 0); }
function resetView() { if (!cy) return; clearHighlight(); cy.animate({ fit: { eles: cy.elements(), padding: 40 }, duration: 500 }); }
function relayout() { if (!cy) return; cy.layout({ name: "fcose", quality: "proof", animate: true, randomize: true, nodeRepulsion: 9000, idealEdgeLength: 90 }).run(); }

function highlight(ids) {
  if (!cy || !ids || !ids.length) return;
  stopPulse();
  let used = cy.collection();
  ids.forEach(id => { const n = cy.getElementById(id); if (n && n.length) used = used.union(n); });
  if (used.length === 0) return;
  const idset = new Set(ids);
  const between = cy.edges().filter(ed => idset.has(ed.source().id()) && idset.has(ed.target().id()));
  cy.elements().addClass("faded");
  used.removeClass("faded").addClass("hl");
  between.removeClass("faded").addClass("hl-edge");
  let on = false;
  pulseTimer = setInterval(() => { on = !on; used.animate({ style: { "overlay-opacity": on ? 0.45 : 0.12 } }, { duration: 480 }); }, 520);
  cy.animate({ fit: { eles: used.union(between), padding: 90 }, duration: 650 });
}

async function runAsk(q) {
  const query = (q != null ? q : $("q").value).trim();
  if (!query || S.loading) return;
  $("q").value = query;
  S.loading = true; S.ask = null; S.tab = "ask"; clearHighlight();
  renderTabs(); renderBody(); $("askBtn").disabled = true; $("askBtn").textContent = "Asking Genie…";
  try {
    const r = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: query }) });
    const data = await r.json();
    S.ask = data;
    (data.nodes_used || []).forEach(id => { S.usage[id] = (S.usage[id] || 0) + 1; });
    applySizes();
    highlight(data.nodes_used || []);
  } catch (e) {
    S.ask = { answer: "Error: " + e.message, sql: "", columns: [], rows: [], nodes_used: [] };
  } finally {
    S.loading = false; $("askBtn").disabled = false; $("askBtn").textContent = "Ask Genie"; renderBody();
  }
}

async function recompute() {
  S.recomputing = true; renderBody();
  try {
    const d = await (await fetch("/api/ontorank/recompute", { method: "POST" })).json();
    S.ontorank = d;
    if (d.node_counts) { S.usage = Object.assign({}, d.node_counts); applySizes(); }
  } finally { S.recomputing = false; renderBody(); }
}

// ---------- panels ----------
function nodeById(id) { const n = (S.graph.nodes || []).find(x => x.data.id === id); return n ? n.data : null; }

// map any used node id -> its owning asset id (table / metric view)
function assetOf(id) {
  if (!id) return null;
  if (id.startsWith("tbl:")) return id;
  if (id.startsWith("measure:")) return "tbl:" + id.slice(8).split(".")[0];
  if (id.startsWith("col:")) return "tbl:" + id.slice(4).split(".")[0];
  return null;
}
// global OntoRank position + score for an asset id
function ontorankInfo(assetId) {
  const ranked = (S.ontorank && S.ontorank.ranked) || [];
  const idx = ranked.findIndex(r => r.id === assetId);
  return idx < 0 ? null : Object.assign({ rank: idx + 1, total: ranked.length }, ranked[idx]);
}

function panelAsk() {
  if (S.loading) return `<div class="loading"><span class="spinner"></span>Genie is answering — resolving the question over the governed ontology…</div>`;
  if (!S.ask) return `<div class="hint">Ask a natural-language question above. Genie answers over the governed ontology; you'll see the <b>detailed answer</b>, the <b>assets</b> it used, and <b>how OntoRank ranks those assets by authority</b> — and the graph lights up the exact path.</div>`;
  const a = S.ask;

  // ----- which assets did Genie use, and what sub-nodes (measures/cols) of each -----
  const byAsset = {};
  (a.nodes_used || []).forEach(id => {
    const asset = assetOf(id);
    if (!asset) return;
    (byAsset[asset] = byAsset[asset] || { subs: [] });
    if (id !== asset) byAsset[asset].subs.push(id);
  });
  const assets = Object.keys(byAsset).map(aid => {
    const info = ontorankInfo(aid);
    const n = nodeById(aid);
    return { id: aid, label: n ? n.label : aid.replace(/^tbl:/, ""), subs: byAsset[aid].subs, info };
  });
  // order by OntoRank rank (ranked assets first, best rank first)
  assets.sort((x, y) => (x.info ? x.info.rank : 999) - (y.info ? y.info.rank : 999));

  let h = "";

  // 1) Assets used + how OntoRank ranked them
  if (assets.length) {
    h += `<h3 class="sec">Assets used &amp; OntoRank authority (${assets.length})</h3>`;
    h += `<div class="hint" style="margin-bottom:8px">The assets Genie relied on to answer, ordered by OntoRank — authority scored by how often each asset is used across the benchmark questions.</div>`;
    h += assets.map(as => {
      const info = as.info;
      const rankPill = info
        ? `<span class="rank-pill" title="OntoRank position by Genie usage">#${info.rank}<span class="of">/${info.total}</span></span>`
        : `<span class="rank-pill pending" title="OntoRank still computing">#—</span>`;
      const typeBadge = info
        ? `<span class="badge ${info.asset_type === "Metric view" ? "gold" : "teal"}">${esc(info.asset_type)}</span>`
        : "";
      const cert = info && info.certified ? `<span class="badge green">Certified</span>` : "";
      const score = info ? `<span class="score">OntoRank score ${info.score}</span>` : "";
      const subs = as.subs.length
        ? `<div class="subs">via ${as.subs.map(id => { const sn = nodeById(id); return `<span class="badge grey link" data-node="${esc(id)}">${esc(sn ? sn.label : id)}</span>`; }).join(" ")}</div>`
        : "";
      return `<div class="card asset-row">
        ${rankPill}
        <div class="asset-main">
          <div class="asset-name"><span class="link" data-node="${esc(as.id)}">${esc(as.label)}</span> ${typeBadge} ${cert}</div>
          ${score}
          ${subs}
        </div>
      </div>`;
    }).join("");
    if (!S.ontorank) h += `<div class="hint"><span class="spinner"></span> OntoRank is still computing — rankings will fill in shortly.</div>`;
  }

  // 2) The detailed answer
  h += `<h3 class="sec">Detailed answer</h3><div class="card answer">${mdBold(a.answer || "(no answer)")}</div>`;
  if (a.description) h += `<div class="hint" style="margin-bottom:12px">${esc(a.description)}</div>`;
  if (a.columns && a.columns.length) {
    h += `<div class="card" style="overflow-x:auto;margin-top:10px"><table class="tbl"><thead><tr>${a.columns.map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${(a.rows || []).slice(0, 40).map(r => `<tr>${r.map(v => `<td>${esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }
  return h;
}

function panelDetail() {
  const n = S.selected;
  if (!n) return `<div class="hint">Click any node in the graph to inspect it.</div>`;
  let h = `<h3 class="sec">${esc(TYPE_LABELS[n.ntype] || n.ntype)}</h3><div class="card"><div style="font-size:16px;font-weight:700;margin-bottom:8px">${esc(n.label)}</div>`;
  if (n.asset_type) h += `<span class="badge ${n.asset_type === "Metric view" ? "gold" : "teal"}">${esc(n.asset_type)}</span>`;
  if (n.certified) h += `<span class="badge green">Certified</span>`;
  if (n.ntype === "table" || n.ntype === "metric_view") h += `<span class="badge purple">tag: AXA Insurance</span>`;
  if (n.desc) h += `<p style="margin-top:10px">${esc(n.desc)}</p>`;
  if (n.comment) h += `<p style="margin-top:10px">${esc(n.comment)}</p>`;
  if (n.definition) h += `<p style="margin-top:10px">${esc(n.definition)}</p>`;
  if (n.owner) h += `<div class="kv"><span class="k">Owner</span><span>${esc(n.owner)}</span></div>`;
  if (n.source) h += `<div class="kv"><span class="k">Source</span><span class="mono">${esc(n.source)}</span></div>`;
  if (n.data_type) h += `<div class="kv"><span class="k">Type</span><span class="mono">${esc(n.data_type)}</span></div>`;
  if (n.parent) h += `<div class="kv"><span class="k">Parent</span><span class="mono">${esc(n.parent)}</span></div>`;
  if (n.synonyms) h += `<div class="kv"><span class="k">Synonyms</span><span>${esc(n.synonyms.join(", "))}</span></div>`;
  if (typeof n.usage === "number") h += `<div class="kv"><span class="k">Genie usage</span><span>${n.usage}</span></div>`;
  h += `</div>`;
  if (n.expr) h += `<h3 class="sec">Measure expression (business rule)</h3><div class="card expr mono">${esc(n.expr)}</div>`;
  return h;
}

function panelAssets() {
  const g = S.graph; const assets = g.nodes.filter(n => n.data.ntype === "table" || n.data.ntype === "metric_view").map(n => n.data);
  let h = `<h3 class="sec">Assets &amp; Sources (${assets.length})</h3><div class="card" style="overflow-x:auto"><table class="tbl"><thead><tr><th>Asset</th><th>Type</th><th>Certified</th><th>Owner</th></tr></thead><tbody>`;
  h += assets.map(a => `<tr><td class="mono link" data-node="${esc(a.id)}">${esc(a.label)}</td><td>${esc(a.asset_type)}</td><td>${a.certified ? '<span class="badge green">Yes</span>' : '<span class="badge grey">No</span>'}</td><td>${esc(a.owner)}</td></tr>`).join("");
  h += `</tbody></table></div><h3 class="sec">Classification</h3><div class="card hint">Domain: <b>${esc(g.domain)}</b> · Source: <span class="mono">${esc(g.catalog)}.${esc(g.schema)}</span><br/>All ${assets.length} assets carry the governed tag <span class="badge purple">AXA Insurance</span>. Asset types: Table, Metric view, plus 8 Glossary pages and 1 Genie space.</div>`;
  return h;
}

function panelRules() {
  const g = S.graph; let h = `<h3 class="sec">Metric-view measures (KPI math)</h3>`;
  for (const mv of Object.keys(g.measures)) {
    h += `<div class="card"><div style="font-weight:700;margin-bottom:8px" class="mono">${esc(mv)}</div>`;
    h += g.measures[mv].map(([name, expr]) => `<div style="margin-bottom:8px"><div style="font-size:13px;margin-bottom:3px">${esc(name)}</div><div class="expr mono">${esc(expr)}</div></div>`).join("");
    h += `</div>`;
  }
  h += `<h3 class="sec">Constraints (PK / FK)</h3><div class="card">`;
  h += g.constraints.map(c => `<div class="kv"><span class="badge grey">${esc(c.type)}</span><span class="mono">${esc(c.name)}: ${esc(c.table)}(${esc(c.columns.join(","))})${c.ref_table ? " → " + esc(c.ref_table) + "(" + esc(c.ref_columns.join(",")) + ")" : ""}</span></div>`).join("");
  h += `</div>`;
  return h;
}

function panelGlossary() {
  const g = S.graph;
  let h = `<h3 class="sec">Business glossary → field mapping (inference)</h3><div class="hint" style="margin-bottom:10px">How business language resolves to governed fields &amp; measures. Click "resolve" to see Genie infer it live.</div>`;
  h += g.glossary.map(gl => { const t = nodeById(gl.target); return `<div class="card"><div style="font-weight:700">${esc(gl.term)} <span class="link" style="font-size:12px" data-ask="${esc(gl.term)}">· resolve</span></div><div class="hint" style="margin:4px 0">synonyms: ${esc(gl.synonyms.join(", "))}</div><div style="font-size:13px">${esc(gl.definition)}</div><div class="kv" style="margin-top:6px"><span class="k">maps to</span><span class="badge teal link" data-node="${esc(gl.target)}">${esc(t ? t.label : gl.target)}</span></div></div>`; }).join("");
  return h;
}

function panelHierarchy() {
  const g = S.graph;
  const tables = g.nodes.filter(n => n.data.ntype === "table");
  const mvs = g.nodes.filter(n => n.data.ntype === "metric_view");
  const colsOf = t => g.nodes.filter(n => n.data.ntype === "column" && n.data.parent === t);
  const measOf = t => g.nodes.filter(n => n.data.ntype === "measure" && n.data.parent === t);
  let h = `<h3 class="sec">Containment hierarchy</h3><div class="card tree"><div class="lvl1">📚 ${esc(g.catalog)}</div><div class="lvl2">▸ ${esc(g.schema)}</div>`;
  tables.forEach(t => { h += `<div class="lvl3">▪ ${esc(t.data.label)} (table)</div>` + colsOf(t.data.label).map(c => `<div class="lvl3" style="padding-left:50px;color:#5b6577">· ${esc(c.data.label)}</div>`).join(""); });
  mvs.forEach(t => { h += `<div class="lvl3" style="color:var(--gold)">◆ ${esc(t.data.label)} (metric view)</div>` + measOf(t.data.label).map(m => `<div class="lvl3" style="padding-left:50px;color:#8a7530">ƒ ${esc(m.data.label)}</div>`).join(""); });
  h += `</div><h3 class="sec">Domain membership</h3><div class="card tree"><div class="lvl1" style="color:var(--accent)">⬢ ${esc(g.domain)}</div>`;
  h += tables.concat(mvs).map(t => `<div class="lvl2">▸ ${esc(t.data.label)}</div>`).join("") + `</div>`;
  return h;
}

function panelOntorank() {
  const d = S.ontorank;
  if (!d) return `<div class="loading"><span class="spinner"></span>Computing OntoRank from Genie usage (running benchmark questions)…</div>`;
  const ranked = d.ranked || []; const max = Math.max(1, ...ranked.map(r => r.score));
  let h = `<h3 class="sec">OntoRank — authority by Genie usage</h3><div class="hint" style="margin-bottom:10px">Ranked by how often each asset is referenced across ${(d.questions || []).length} benchmark questions run through Genie. Ties broken by certified, then metric-view. <span class="link" data-recompute="1">${S.recomputing ? "· recomputing…" : "· recompute"}</span></div>`;
  h += ranked.map(r => `<div class="bar-row"><div class="bar-label mono">${esc(r.name)}</div><div class="bar-track"><div class="bar-fill" style="width:${(r.score / max) * 100}%"></div></div><div class="bar-val">${r.score}</div></div>`).join("");
  h += `<h3 class="sec">Detail</h3><div class="card" style="overflow-x:auto"><table class="tbl"><thead><tr><th>Asset</th><th>Type</th><th>Cert.</th><th>Score</th></tr></thead><tbody>`;
  h += ranked.map(r => `<tr><td class="mono">${esc(r.name)}</td><td>${esc(r.asset_type)}</td><td>${r.certified ? "✓" : ""}</td><td>${r.score}</td></tr>`).join("");
  h += `</tbody></table></div><h3 class="sec">Benchmark questions</h3><div class="card">`;
  h += (d.questions || []).map(q => `<div class="hint" style="margin-bottom:4px"><span class="link" data-ask="${esc(q)}">▸ ${esc(q)}</span></div>`).join("");
  h += `</div>`;
  return h;
}

function renderBody() {
  const map = { ask: panelAsk, detail: panelDetail, assets: panelAssets, rules: panelRules, glossary: panelGlossary, hierarchy: panelHierarchy, ontorank: panelOntorank };
  $("tabBody").innerHTML = S.graph || S.tab === "ask" ? (map[S.tab] ? map[S.tab]() : "") : `<div class="loading"><span class="spinner"></span>Loading ontology…</div>`;
}

function renderTabs() {
  $("tabs").innerHTML = TABS.map(([k, l]) => `<button class="${S.tab === k ? "active" : ""}" data-tab="${k}">${l}</button>`).join("");
}

function renderControls() {
  let h = `<button data-ctl="reset">Reset view</button><button data-ctl="clear">Clear highlight</button><button data-ctl="relayout">Re-layout</button>`;
  h += FILTER_TYPES.map(t => `<button class="filter-btn ${S.filters[t] ? "" : "off"}" data-filter="${t}"><span class="swatch" style="background:${TYPE_COLORS[t]}"></span>${TYPE_LABELS[t]}</button>`).join("");
  $("controls").innerHTML = h;
  $("examples").innerHTML = `<span>Try:</span>` + EXAMPLES.map(ex => `<span class="chip" data-ask="${esc(ex)}">${esc(ex)}</span>`).join("");
}

// ---------- event delegation ----------
document.addEventListener("click", e => {
  const el = e.target.closest("[data-tab],[data-ask],[data-node],[data-ctl],[data-filter],[data-recompute]");
  if (!el) return;
  if (el.dataset.tab) { S.tab = el.dataset.tab; renderTabs(); renderBody(); }
  else if (el.dataset.ask != null) { runAsk(el.dataset.ask); }
  else if (el.dataset.node) { const n = nodeById(el.dataset.node); if (n) { S.selected = n; S.tab = "detail"; renderTabs(); renderBody(); const cn = cy && cy.getElementById(el.dataset.node); if (cn && cn.length) cy.animate({ center: { eles: cn }, duration: 400 }); } }
  else if (el.dataset.ctl === "reset") resetView();
  else if (el.dataset.ctl === "clear") clearHighlight();
  else if (el.dataset.ctl === "relayout") relayout();
  else if (el.dataset.filter) { const t = el.dataset.filter; S.filters[t] = !S.filters[t]; renderControls(); applyFilters(); }
  else if (el.dataset.recompute) recompute();
});
function clearAsk() {
  $("q").value = "";
  S.ask = null; S.tab = "ask";
  clearHighlight();
  relayout();
  renderTabs(); renderBody();
  $("q").focus();
}

$("askBtn").addEventListener("click", () => runAsk());
$("clearBtn").addEventListener("click", clearAsk);
$("q").addEventListener("keydown", e => { if (e.key === "Enter") runAsk(); });

// ---------- boot ----------
renderControls(); renderTabs(); renderBody();
fetch("/api/ontology").then(r => r.json()).then(g => { S.graph = g; initCy(); renderBody(); });
fetch("/api/ontorank").then(r => r.json()).then(d => { S.ontorank = d; if (d.node_counts) { S.usage = Object.assign({}, d.node_counts); applySizes(); } if (S.tab === "ontorank") renderBody(); }).catch(() => {});
