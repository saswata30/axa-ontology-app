# AXA Insurance · Genie Ontology Explorer

A Databricks App that visualizes the **Genie Ontology** of the governed *AXA Insurance* domain and lets business
users query it in natural language. Ask a question → Genie answers over the governed semantic layer → the
**knowledge graph lights up the exact assets it used**, and **OntoRank** ranks those assets by authority.

> Companion to the [AXA Insurance domain workshop](https://github.com/saswata30/axa-insurance-domain-workshop).
> Built on `serverless_stable_xhky6g_catalog.insurance` (synthetic AXA P&C data).

## Features
- **Natural-language ask** (first-class) — calls Genie via the managed **MCP** endpoint (`/api/2.0/mcp/genie/{space}`), with the Genie Conversations REST API as a fallback. Returns the detailed answer + result table.
- **Dynamic knowledge graph** (Cytoscape, force-directed) — domain, Genie agent, tables, metric views, measures, glossary terms, columns. On each question the assets/measures/columns in Genie's SQL **pulse and highlight** (the inference path); the rest dims.
- **OntoRank from Genie usage** — runs the benchmark questions through Genie, parses the SQL, and ranks assets by how often Genie actually relies on them. Node size ∝ usage.
- **Assets used & authority** — per answer, the assets Genie used, ordered by OntoRank (rank, score, certified), and *how* it reached them (via which measure/column). *(SQL is intentionally not shown.)*
- **Hierarchy / Classification / Business rules / Inference / Assets & Sources** panels, type filters, and a Clear control that resets the panel and re-lays out the graph.

## Architecture
- **Backend** — FastAPI (`app.py`, `server/ontology.py`, `server/dbx.py`). Builds the graph from `information_schema` + metric-view YAML + seeded glossary terms + the domain governed tag. Calls Genie (MCP + REST) and the SQL Statement Execution API as the app's service principal via `WorkspaceClient()`.
- **Frontend** — vanilla JS + Cytoscape (`static/`, vendored — no CDN), served as static files by FastAPI.

## Configuration (`app.yaml`)
| env | value |
|---|---|
| `DATABRICKS_WAREHOUSE_ID` | SQL warehouse used for graph + result queries |
| `GENIE_SPACE_ID` | the Genie agent/space to query |
| `ONTO_CATALOG` / `ONTO_SCHEMA` | the governed schema to introspect |

## Deploy (Databricks Apps)
```bash
P=<cli-profile>
databricks apps create axa-ontology --profile=$P
databricks workspace import-dir . /Workspace/Users/<you>/axa-ontology-src --overwrite --profile=$P
databricks apps deploy axa-ontology \
  --source-code-path /Workspace/Users/<you>/axa-ontology-src --profile=$P
```
Then grant the app's **service principal**: the Genie space `CAN_RUN`, the warehouse `CAN_USE`, and UC
`SELECT`/`USE` on the catalog+schema. The Genie space must have the relevant tables/metric views as sources
(cross-table questions like *loss ratio by customer industry* need the underlying tables added to the agent).

*Synthetic data. Screenshots/behavior reflect the Databricks product UI in a Field Engineering demo workspace.*
