"""Ontology model for the AXA Insurance domain (Genie Ontology).

Builds a knowledge graph (nodes + edges) from:
  - live Unity Catalog structure (information_schema) with a seeded fallback
  - seeded governed business rules (metric-view measure expressions, PK/FK)
  - seeded glossary terms (Discover pages have no REST API)
Also parses Genie-generated SQL to identify which ontology nodes a query uses
(powers highlighting + OntoRank).
"""
import re
from . import dbx

CATALOG = dbx.CATALOG
SCHEMA = dbx.SCHEMA
DOMAIN = "AXA Insurance"

# ---- node id helpers ----
NID_DOMAIN = "domain:axa"
NID_CATALOG = f"cat:{CATALOG}"
NID_SCHEMA = f"schema:{SCHEMA}"
NID_GENIE = "genie:agent"


def tbl_id(t):
    return f"tbl:{t}"


def col_id(t, c):
    return f"col:{t}.{c}"


def measure_id(mv, m):
    return f"measure:{mv}.{m}"


def term_id(t):
    return f"term:{t}"


# ---- seeded structure (fallback if live query fails) ----
TABLE_META = {
    "claims": {"type": "table", "certified": True,
               "desc": "Loss run / claims bordereau — individual claim transactions (incurred, paid, reserves, recovery).",
               "owner": "Insurance Data Steward"},
    "policies": {"type": "table", "certified": True,
                 "desc": "Policy master — written & earned premium by annual policy term.",
                 "owner": "Insurance Data Steward"},
    "customers": {"type": "table", "certified": True,
                  "desc": "Customer master — segment, industry, region.",
                  "owner": "Insurance Data Steward"},
    "premiums": {"type": "table", "certified": False,
                 "desc": "Monthly earned-premium schedule per policy.",
                 "owner": "Insurance Data Steward"},
    "mv_portfolio": {"type": "metric_view", "certified": True,
                     "desc": "Portfolio underwriting metrics: premium, loss ratio, combined ratio, frequency, severity at policy grain.",
                     "owner": "Underwriting Analytics"},
    "mv_claims": {"type": "metric_view", "certified": True,
                  "desc": "Claim-level (loss run) metrics: incurred, paid, reserves, recovery, frequency and severity by cause of loss.",
                  "owner": "Claims Analytics"},
}

SEED_COLUMNS = {
    "claims": ["policy_id", "line_of_business", "loss_date", "report_date", "cause_of_loss",
               "claim_status", "paid_loss", "case_reserve", "incurred_loss", "recovery_amount",
               "net_incurred_loss", "large_loss_flag", "claim_handler", "claim_id", "customer_id",
               "region", "country"],
    "policies": ["policy_id", "customer_id", "line_of_business", "product", "underwriting_year",
                 "inception_date", "expiry_date", "written_premium", "earned_premium", "sum_insured",
                 "deductible", "commission_amount", "other_expense_amount", "broker", "country",
                 "region", "policy_status"],
    "customers": ["customer_id", "customer_name", "industry", "segment", "country", "region", "customer_since"],
    "premiums": ["policy_id", "line_of_business", "region", "earned_month", "earned_premium_month"],
}

COLUMN_COMMENTS = {
    "claims.cause_of_loss": "Peril/cause: Fire, Flood, Collision, Bodily Injury, Cargo Damage, etc.",
    "claims.paid_loss": "Amount already paid on the claim.",
    "claims.case_reserve": "Reserve held for the open portion of the claim (0 when closed).",
    "claims.incurred_loss": "Ultimate incurred loss = paid_loss + case_reserve (before recoveries). A.k.a. ultimate loss.",
    "claims.recovery_amount": "Salvage/subrogation recovered, reducing net loss.",
    "policies.line_of_business": "Product line: Property, Motor, Liability, Marine.",
    "policies.written_premium": "Total premium written for the annual policy term.",
    "policies.earned_premium": "Premium earned to date (pro-rata of written premium). Denominator of the loss ratio.",
}

# ---- metric-view business rules (measure expressions) ----
MV_MEASURES = {
    "mv_portfolio": [
        ("Earned Premium", "SUM(earned_premium)"),
        ("Written Premium", "SUM(written_premium)"),
        ("Incurred Loss", "SUM(incurred_loss)"),
        ("Policy Count", "COUNT(DISTINCT policy_id)"),
        ("Claim Count", "SUM(claim_count)"),
        ("Loss Ratio", "SUM(incurred_loss) / NULLIF(SUM(earned_premium),0)"),
        ("Expense Ratio", "(SUM(commission_amount)+SUM(other_expense_amount)) / NULLIF(SUM(written_premium),0)"),
        ("Combined Ratio", "SUM(incurred_loss)/NULLIF(SUM(earned_premium),0) + (SUM(commission_amount)+SUM(other_expense_amount))/NULLIF(SUM(written_premium),0)"),
        ("Claim Frequency", "SUM(claim_count) / NULLIF(COUNT(DISTINCT policy_id),0)"),
        ("Claim Severity", "SUM(incurred_loss) / NULLIF(SUM(claim_count),0)"),
    ],
    "mv_claims": [
        ("Incurred Loss", "SUM(incurred_loss)"),
        ("Paid Loss", "SUM(paid_loss)"),
        ("Case Reserves", "SUM(case_reserve)"),
        ("Recovery Amount", "SUM(recovery_amount)"),
        ("Net Incurred Loss", "SUM(net_incurred_loss)"),
        ("Claim Count", "COUNT(claim_id)"),
        ("Large Loss Count", "SUM(CASE WHEN large_loss_flag THEN 1 ELSE 0 END)"),
        ("Average Severity", "SUM(incurred_loss) / NULLIF(COUNT(claim_id),0)"),
        ("Open Reserve Ratio", "SUM(case_reserve) / NULLIF(SUM(incurred_loss),0)"),
    ],
}

MV_DIMENSIONS = {
    "mv_portfolio": ["Line of Business", "Region", "Underwriting Year", "Broker", "Policy Status"],
    "mv_claims": ["Line of Business", "Region", "Cause of Loss", "Claim Status", "Large Loss", "Loss Year", "Loss Month"],
}

# ---- PK / FK constraints ----
CONSTRAINTS = [
    {"name": "pk_policies", "type": "PRIMARY KEY", "table": "policies", "columns": ["policy_id"]},
    {"name": "pk_customers", "type": "PRIMARY KEY", "table": "customers", "columns": ["customer_id"]},
    {"name": "fk_claims_policy", "type": "FOREIGN KEY", "table": "claims",
     "columns": ["policy_id"], "ref_table": "policies", "ref_columns": ["policy_id"]},
    {"name": "fk_policy_customer", "type": "FOREIGN KEY", "table": "policies",
     "columns": ["customer_id"], "ref_table": "customers", "ref_columns": ["customer_id"]},
]

# ---- glossary terms -> field/measure mappings (inference) ----
GLOSSARY = [
    {"key": "loss_ratio", "term": "Loss Ratio", "synonyms": ["LR", "loss cost ratio"],
     "definition": "Incurred loss as a proportion of earned premium.",
     "target": measure_id("mv_portfolio", "Loss Ratio")},
    {"key": "combined_ratio", "term": "Combined Ratio", "synonyms": ["COR"],
     "definition": "Loss ratio plus expense ratio; > 100% = underwriting loss.",
     "target": measure_id("mv_portfolio", "Combined Ratio")},
    {"key": "incurred_loss", "term": "Incurred Loss", "synonyms": ["ultimate loss", "incurred"],
     "definition": "Paid loss + case reserve, before recoveries.",
     "target": col_id("claims", "incurred_loss")},
    {"key": "earned_premium", "term": "Earned Premium", "synonyms": ["EP", "earned"],
     "definition": "Premium earned to date; denominator of loss ratio.",
     "target": col_id("policies", "earned_premium")},
    {"key": "loss_run", "term": "Loss Run", "synonyms": ["claims bordereau", "loss listing"],
     "definition": "Detailed listing of individual claims.",
     "target": tbl_id("claims")},
    {"key": "claim_frequency", "term": "Claim Frequency", "synonyms": ["frequency"],
     "definition": "Claim count per policy.",
     "target": measure_id("mv_portfolio", "Claim Frequency")},
    {"key": "claim_severity", "term": "Claim Severity", "synonyms": ["average severity", "severity"],
     "definition": "Average incurred loss per claim.",
     "target": measure_id("mv_portfolio", "Claim Severity")},
    {"key": "case_reserve", "term": "Case Reserve", "synonyms": ["outstanding", "OS reserve"],
     "definition": "Reserve held for the open portion of a claim.",
     "target": col_id("claims", "case_reserve")},
]

ASSETS = ["claims", "policies", "customers", "premiums", "mv_portfolio", "mv_claims"]


def _fetch_live_columns():
    q = (f"SELECT table_name, column_name, data_type, comment "
         f"FROM {CATALOG}.information_schema.columns "
         f"WHERE table_schema='{SCHEMA}' ORDER BY table_name, ordinal_position")
    res = dbx.run_sql(q)
    cols = {}
    for r in res["rows"]:
        t, c, dt, cm = r[0], r[1], r[2], r[3]
        cols.setdefault(t, []).append({"name": c, "data_type": dt, "comment": cm})
    return cols


def build_graph(live=True):
    nodes, edges = [], []

    def add_node(nid, label, ntype, **data):
        nodes.append({"data": {"id": nid, "label": label, "ntype": ntype, **data}})

    def add_edge(s, t, etype, label=""):
        edges.append({"data": {"id": f"{s}__{etype}__{t}", "source": s, "target": t,
                                "etype": etype, "label": label}})

    # domain / catalog / schema
    add_node(NID_DOMAIN, DOMAIN, "domain", desc="Governed business domain (governed tag applied to all assets).")
    add_node(NID_CATALOG, CATALOG, "catalog", desc="Unity Catalog")
    add_node(NID_SCHEMA, SCHEMA, "schema", desc="Insurance schema")
    add_edge(NID_CATALOG, NID_SCHEMA, "contains")
    add_node(NID_GENIE, "Genie Agent", "genie_agent",
             desc="Insurance Claims & Underwriting Analytics Genie space — resolves NL questions to governed SQL.")

    # live columns (with seeded fallback)
    live_cols = None
    if live:
        try:
            live_cols = _fetch_live_columns()
        except Exception as e:
            live_cols = None
            print("live column fetch failed, using seed:", e)

    for t in ASSETS:
        meta = TABLE_META[t]
        add_node(tbl_id(t), t, meta["type"], desc=meta["desc"], certified=meta["certified"],
                 owner=meta["owner"], source=f"{CATALOG}.{SCHEMA}",
                 asset_type=("Metric view" if meta["type"] == "metric_view" else "Table"))
        add_edge(NID_SCHEMA, tbl_id(t), "contains")
        add_edge(tbl_id(t), NID_DOMAIN, "tagged", DOMAIN)  # domain membership (governed tag)
        add_edge(NID_GENIE, tbl_id(t), "uses")

    # columns for base tables
    for t in ["claims", "policies", "customers", "premiums"]:
        if live_cols and t in live_cols:
            for c in live_cols[t]:
                cm = c["comment"] or COLUMN_COMMENTS.get(f"{t}.{c['name']}", "")
                add_node(col_id(t, c["name"]), c["name"], "column", data_type=c["data_type"],
                         comment=cm, parent=t)
                add_edge(tbl_id(t), col_id(t, c["name"]), "contains")
        else:
            for cn in SEED_COLUMNS[t]:
                cm = COLUMN_COMMENTS.get(f"{t}.{cn}", "")
                add_node(col_id(t, cn), cn, "column", comment=cm, parent=t)
                add_edge(tbl_id(t), col_id(t, cn), "contains")

    # metric view measures (business rules) + dimensions
    for mv, measures in MV_MEASURES.items():
        for name, expr in measures:
            add_node(measure_id(mv, name), name, "measure", expr=expr, parent=mv)
            add_edge(tbl_id(mv), measure_id(mv, name), "defines")

    # FK edges
    for con in CONSTRAINTS:
        if con["type"] == "FOREIGN KEY":
            src = col_id(con["table"], con["columns"][0])
            dst = col_id(con["ref_table"], con["ref_columns"][0])
            add_edge(src, dst, "fk", con["name"])

    # glossary terms (inference edges)
    for g in GLOSSARY:
        add_node(term_id(g["key"]), g["term"], "glossary", definition=g["definition"],
                 synonyms=g["synonyms"], target=g["target"])
        add_edge(term_id(g["key"]), g["target"], "means", "maps to")

    return {"nodes": nodes, "edges": edges,
            "constraints": CONSTRAINTS, "glossary": GLOSSARY,
            "measures": MV_MEASURES, "dimensions": MV_DIMENSIONS,
            "domain": DOMAIN, "catalog": CATALOG, "schema": SCHEMA}


# ---- SQL -> ontology node parser (highlight + OntoRank) ----
_MEASURE_RE = re.compile(r"MEASURE\(\s*`([^`]+)`\s*\)", re.IGNORECASE)
_BACKTICK_RE = re.compile(r"`([^`]+)`")


def _measure_owner(measure_name, referenced_tables):
    # attribute a measure to the mv referenced in the query
    for mv in ["mv_portfolio", "mv_claims"]:
        if mv in referenced_tables and any(m[0] == measure_name for m in MV_MEASURES[mv]):
            return mv
    # else first mv that defines it
    for mv in ["mv_portfolio", "mv_claims"]:
        if any(m[0] == measure_name for m in MV_MEASURES[mv]):
            return mv
    return None


def parse_sql_nodes(sql: str):
    """Return list of ontology node ids referenced by a SQL string."""
    if not sql:
        return []
    used = set()
    low = sql.lower()

    # tables / metric views
    referenced_tables = set()
    for t in ASSETS:
        if re.search(rf"[.`\s]{re.escape(t)}[`\s.]|\b{re.escape(t)}\b", low):
            if re.search(rf"\b{re.escape(t)}\b", low):
                referenced_tables.add(t)
                used.add(tbl_id(t))

    # measures via MEASURE(`..`)
    for m in _MEASURE_RE.findall(sql):
        mv = _measure_owner(m, referenced_tables)
        if mv:
            used.add(measure_id(mv, m))
            used.add(tbl_id(mv))
            referenced_tables.add(mv)

    # backticked identifiers that match measures (some SQL aliases measures)
    for ident in _BACKTICK_RE.findall(sql):
        for mv in referenced_tables:
            if mv in MV_MEASURES and any(mm[0] == ident for mm in MV_MEASURES[mv]):
                used.add(measure_id(mv, ident))

    # columns: match known columns of referenced base tables
    for t in ["claims", "policies", "customers", "premiums"]:
        if t in referenced_tables:
            for cn in SEED_COLUMNS[t]:
                if re.search(rf"\b{re.escape(cn)}\b", low):
                    used.add(col_id(t, cn))
    return sorted(used)
