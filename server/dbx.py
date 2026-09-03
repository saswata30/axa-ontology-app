"""Databricks helpers: SQL statement execution + auth for Genie (MCP & REST)."""
import os
import json
import time
import httpx
from databricks.sdk import WorkspaceClient

WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "4159f49475be8677")
GENIE_SPACE_ID = os.environ.get("GENIE_SPACE_ID", "01f1a6263ecd1549a5569138a6f8be81")
CATALOG = os.environ.get("ONTO_CATALOG", "serverless_stable_xhky6g_catalog")
SCHEMA = os.environ.get("ONTO_SCHEMA", "insurance")

_w = None


def w() -> WorkspaceClient:
    global _w
    if _w is None:
        _w = WorkspaceClient()
    return _w


def host() -> str:
    h = w().config.host or os.environ.get("DATABRICKS_HOST", "")
    if h and not h.startswith("http"):
        h = "https://" + h
    return h.rstrip("/")


def auth_headers() -> dict:
    # Works for both app service-principal OAuth and local U2M.
    return w().config.authenticate()


def run_sql(statement: str, timeout: str = "50s") -> dict:
    """Execute SQL via the Statement Execution API. Returns {columns, rows}."""
    resp = w().statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID, statement=statement, wait_timeout=timeout
    )
    # poll if still running
    status = resp.status.state.value if resp.status and resp.status.state else "SUCCEEDED"
    sid = resp.statement_id
    for _ in range(30):
        if status in ("SUCCEEDED", "FAILED", "CANCELED", "CLOSED"):
            break
        time.sleep(1.5)
        resp = w().statement_execution.get_statement(sid)
        status = resp.status.state.value if resp.status and resp.status.state else ""
    if status != "SUCCEEDED":
        msg = ""
        try:
            msg = resp.status.error.message
        except Exception:
            pass
        raise RuntimeError(f"SQL {status}: {msg}")
    cols = []
    if resp.manifest and resp.manifest.schema and resp.manifest.schema.columns:
        cols = [c.name for c in resp.manifest.schema.columns]
    rows = []
    if resp.result and resp.result.data_array:
        rows = resp.result.data_array
    return {"columns": cols, "rows": rows}


# ----------------- Genie via managed MCP endpoint -----------------

def _parse_mcp_body(text: str) -> dict:
    """Handle both plain JSON and SSE (data: {...}) streamable-HTTP bodies."""
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    payload = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
    if payload:
        return json.loads(payload)
    raise RuntimeError("Unparseable MCP body: " + text[:200])


def _mcp_url() -> str:
    return f"{host()}/api/2.0/mcp/genie/{GENIE_SPACE_ID}"


def _mcp_rpc(method: str, params: dict) -> dict:
    headers = {
        **auth_headers(),
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    with httpx.Client(timeout=120) as c:
        r = c.post(_mcp_url(), headers=headers, json=body)
        r.raise_for_status()
        return _parse_mcp_body(r.text)


def _extract_structured(rpc_result: dict) -> dict:
    res = rpc_result.get("result", {})
    if "structuredContent" in res:
        return res["structuredContent"]
    # fallback: parse text content
    for item in res.get("content", []):
        if item.get("type") == "text":
            try:
                return json.loads(item["text"])
            except Exception:
                pass
    return res


def genie_ask_mcp(question: str) -> dict:
    """Ask Genie via MCP. Returns {answer, sql, description, conversation_id}."""
    tool = f"query_space_{GENIE_SPACE_ID}"
    poll_tool = f"poll_response_{GENIE_SPACE_ID}"
    out = _extract_structured(_mcp_rpc("tools/call", {"name": tool, "arguments": {"query": question}}))
    conv_id = out.get("conversationId")
    msg_id = out.get("messageId")
    status = out.get("status", "")
    for _ in range(40):
        if str(status).upper() in ("COMPLETED", "FAILED", "CANCELLED", "QUERY_RESULT_EXPIRED"):
            break
        time.sleep(2)
        out = _extract_structured(
            _mcp_rpc("tools/call", {"name": poll_tool, "arguments": {"conversation_id": conv_id, "message_id": msg_id}})
        )
        status = out.get("status", "")
    content = out.get("content", {}) or {}
    sql, desc = "", ""
    for qa in content.get("queryAttachments", []) or []:
        if qa.get("query"):
            sql = qa["query"]
            desc = qa.get("description", "")
            break
    answer = ""
    texts = content.get("textAttachments", []) or []
    if texts:
        answer = texts[0] if isinstance(texts[0], str) else str(texts[0])
    return {"answer": answer, "sql": sql, "description": desc,
            "conversation_id": conv_id, "status": status}


# ----------------- Genie via REST (used for OntoRank batch) -----------------

def genie_ask_rest(question: str) -> dict:
    base = f"{host()}/api/2.0/genie/spaces/{GENIE_SPACE_ID}"
    headers = {**auth_headers(), "Content-Type": "application/json"}
    with httpx.Client(timeout=120) as c:
        r = c.post(f"{base}/start-conversation", headers=headers, json={"content": question})
        r.raise_for_status()
        d = r.json()
        conv = d["conversation_id"]
        msg = d["message_id"]
        status = d.get("message", {}).get("status", "")
        for _ in range(40):
            if str(status).upper() == "COMPLETED":
                break
            time.sleep(2)
            r = c.get(f"{base}/conversations/{conv}/messages/{msg}", headers=headers)
            r.raise_for_status()
            d = r.json()
            status = d.get("status", "")
    sql, desc, answer = "", "", ""
    for a in d.get("attachments", []) or []:
        if a.get("query") and not sql:
            sql = a["query"].get("query", "")
            desc = a["query"].get("description", "")
        if a.get("text") and not answer:
            answer = a["text"].get("content", "")
    return {"answer": answer, "sql": sql, "description": desc,
            "conversation_id": conv, "status": status}
