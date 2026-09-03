"""AXA Insurance Genie Ontology — FastAPI backend + static React frontend."""
import os
import threading
import traceback
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from server import dbx, ontology

app = FastAPI(title="AXA Insurance Genie Ontology")

_GRAPH_CACHE = {"graph": None}
_ONTORANK_CACHE = {"data": None}
_LOCK = threading.Lock()

BENCHMARK_QUESTIONS = [
    "What is our overall loss ratio?",
    "Loss ratio by line of business",
    "What was the combined ratio in 2024?",
    "Total incurred loss for Motor",
    "Average claim severity by cause of loss",
    "Which region has the highest loss ratio?",
    "Show the loss run for the UK",
]


def get_graph():
    if _GRAPH_CACHE["graph"] is None:
        _GRAPH_CACHE["graph"] = ontology.build_graph(live=True)
    return _GRAPH_CACHE["graph"]


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/ontology")
def api_ontology():
    try:
        return get_graph()
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})


class AskReq(BaseModel):
    question: str


@app.post("/api/ask")
def api_ask(req: AskReq):
    try:
        res = dbx.genie_ask_mcp(req.question)
    except Exception as e:
        traceback.print_exc()
        # fall back to REST if MCP transport fails
        try:
            res = dbx.genie_ask_rest(req.question)
        except Exception as e2:
            return JSONResponse(status_code=500, content={"error": f"{e} / {e2}"})

    sql = res.get("sql", "")
    nodes_used = ontology.parse_sql_nodes(sql)
    columns, rows = [], []
    if sql:
        try:
            r = dbx.run_sql(sql)
            columns, rows = r["columns"], r["rows"]
        except Exception as e:
            print("result exec failed:", e)
    return {
        "answer": res.get("answer", ""),
        "sql": sql,
        "description": res.get("description", ""),
        "columns": columns,
        "rows": rows,
        "nodes_used": nodes_used,
        "status": res.get("status", ""),
    }


def compute_ontorank():
    # asset id -> {score, questions:[], nodes:set}
    scores = {}
    per_question = []
    for q in BENCHMARK_QUESTIONS:
        try:
            res = dbx.genie_ask_rest(q)
            sql = res.get("sql", "")
            nodes = ontology.parse_sql_nodes(sql)
        except Exception as e:
            print("ontorank q failed", q, e)
            sql, nodes = "", []
        per_question.append({"question": q, "sql": sql, "nodes": nodes})
        # attribute to assets (tables/metric views) and their measures
        assets_hit = set()
        for n in nodes:
            if n.startswith("tbl:"):
                assets_hit.add(n)
            if n.startswith("measure:"):
                mv = n.split(":", 1)[1].split(".", 1)[0]
                assets_hit.add(ontology.tbl_id(mv))
            if n.startswith("col:"):
                t = n.split(":", 1)[1].split(".", 1)[0]
                assets_hit.add(ontology.tbl_id(t))
        for a in assets_hit:
            s = scores.setdefault(a, {"score": 0, "questions": []})
            s["score"] += 1
            s["questions"].append(q)

    # node-level usage counts (for graph node sizing)
    node_counts = {}
    for pq in per_question:
        for n in pq["nodes"]:
            node_counts[n] = node_counts.get(n, 0) + 1

    meta = {a: ontology.TABLE_META.get(a.split(":", 1)[1], {}) for a in scores}
    ranked = []
    for a, s in scores.items():
        name = a.split(":", 1)[1]
        m = ontology.TABLE_META.get(name, {})
        ranked.append({
            "id": a, "name": name, "score": s["score"],
            "questions": s["questions"],
            "certified": m.get("certified", False),
            "is_metric_view": m.get("type") == "metric_view",
            "asset_type": "Metric view" if m.get("type") == "metric_view" else "Table",
        })
    ranked.sort(key=lambda x: (x["score"], x["certified"], x["is_metric_view"]), reverse=True)
    return {"ranked": ranked, "node_counts": node_counts,
            "per_question": per_question, "questions": BENCHMARK_QUESTIONS}


@app.get("/api/ontorank")
def api_ontorank():
    if _ONTORANK_CACHE["data"] is None:
        with _LOCK:
            if _ONTORANK_CACHE["data"] is None:
                _ONTORANK_CACHE["data"] = compute_ontorank()
    return _ONTORANK_CACHE["data"]


@app.post("/api/ontorank/recompute")
def api_ontorank_recompute():
    with _LOCK:
        _ONTORANK_CACHE["data"] = compute_ontorank()
    return _ONTORANK_CACHE["data"]


# ---- static frontend (build-free vanilla JS + Cytoscape) ----
STATIC = Path(__file__).parent / "static"
if STATIC.exists():
    # API routes are registered above, so this catch-all only serves non-API paths.
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
