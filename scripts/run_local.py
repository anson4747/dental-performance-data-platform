"""Run the whole platform locally, end to end, with no cloud account.

  1. Load the NHSBSA files in data/raw with dlt into a local DuckDB warehouse.
  2. Compile the Dataform project (the same SQLX that runs in BigQuery).
  3. Execute the compiled graph on DuckDB in dependency order, translating
     BigQuery SQL to DuckDB with sqlglot, then run every assertion.
  4. Write the reporting tables to output/ and draw a preview chart.

In BigQuery the same project runs with `dataform run`. This script exists so
the SQL and its tests run on any laptop and in CI.

Usage:  python scripts/run_local.py [--skip-load]
Exit code is 1 if any assertion returns rows.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from graphlib import TopologicalSorter
from pathlib import Path

import duckdb
import sqlglot
from sqlglot import exp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingestion.pipelines import run as run_dlt  # noqa: E402

DATA = ROOT / "data"
OUTPUT = ROOT / "output"
WAREHOUSE = DATA / "warehouse.duckdb"


def compile_dataform() -> dict:
    cli = shutil.which("dataform") or str(ROOT / "node_modules" / ".bin" / "dataform")
    result = subprocess.run([cli, "compile", str(ROOT / "dataform"), "--json"],
                            capture_output=True, text=True, check=True)
    graph = json.loads(result.stdout)
    if graph.get("graphErrors", {}).get("compilationErrors"):
        raise RuntimeError(graph["graphErrors"])
    return graph


def _key(target: dict) -> str:
    return f'{target["schema"]}.{target["name"]}'


def _strptime(node: exp.StrToDate, safe: bool) -> exp.Expression:
    fn = "TRY_STRPTIME" if safe else "STRPTIME"
    call = exp.Anonymous(this=fn, expressions=[node.this, node.args["format"]])
    return exp.Cast(this=call, to=exp.DataType.build("DATE"))


def to_duckdb(bigquery_sql: str) -> str:
    """Translate one compiled BigQuery statement to DuckDB.

    Drops the project (catalog) from table names and maps PARSE_DATE and
    SAFE.PARSE_DATE straight onto DuckDB's STRPTIME and TRY_STRPTIME.
    """
    tree = sqlglot.parse_one(bigquery_sql, read="bigquery")

    def rewrite(node):
        if isinstance(node, exp.Table) and node.args.get("catalog") is not None:
            node.set("catalog", None)
            return node
        if isinstance(node, exp.SafeFunc) and isinstance(node.this, exp.StrToDate):
            return _strptime(node.this, safe=True)
        if isinstance(node, exp.StrToDate):
            return _strptime(node, safe=False)
        return node

    return tree.transform(rewrite).sql(dialect="duckdb")


def execute_graph(con: duckdb.DuckDBPyConnection, graph: dict) -> list[dict]:
    actions = {}
    for t in graph.get("tables", []):
        actions[_key(t["target"])] = ("table" if t["enumType"] == "TABLE" else "view", t)
    for a in graph.get("assertions", []):
        actions[_key(a["target"])] = ("assertion", a)
    deps = {k: {_key(d) for d in v[1].get("dependencyTargets", []) if _key(d) in actions}
            for k, v in actions.items()}

    results = []
    for key in TopologicalSorter(deps).static_order():
        kind, action = actions[key]
        schema, name = action["target"]["schema"], action["target"]["name"]
        sql = to_duckdb(action["query"])
        if kind in ("table", "view"):
            con.execute(f"create schema if not exists {schema}")
            existing = con.execute(
                "select 'view' from duckdb_views() where schema_name = ? and view_name = ? "
                "union all select 'table' from duckdb_tables() where schema_name = ? and table_name = ?",
                [schema, name, schema, name]).fetchone()
            if existing:
                con.execute(f"drop {existing[0]} {schema}.{name}")
            con.execute(f"create {kind} {schema}.{name} as {sql}")
            rows = con.execute(f"select count(*) from {schema}.{name}").fetchone()[0]
            results.append({"action": key, "type": kind, "rows": rows, "status": "ok"})
        else:
            failing = con.execute(f"select count(*) from ({sql})").fetchone()[0]
            results.append({"action": key, "type": "assertion", "rows": failing,
                            "status": "pass" if failing == 0 else "FAIL"})
    return results


def draw_preview(con: duckdb.DuckDBPyConnection) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    df = con.execute("""
        select activity_month, provider_group, uda_delivery_vs_pro_rata_target
        from dental_reporting.rpt_group_monthly
        where provider_group <> 'Independent and other'
        order by 1
    """).df()
    fig, ax = plt.subplots(figsize=(10, 5))
    for group, part in df.groupby("provider_group"):
        ax.plot(part["activity_month"], part["uda_delivery_vs_pro_rata_target"] * 100, label=group)
    ax.axhline(100, color="black", linewidth=0.8)
    ax.set_ylabel("UDA delivered as % of monthly target")
    ax.set_title("Dental groups (by contract holder name): monthly UDA delivery against target, England")
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(OUTPUT / "group_delivery_preview.png", dpi=120)


def main(skip_load: bool = False) -> int:
    os.environ.setdefault("DENTAL_DESTINATION", "duckdb")
    os.environ.setdefault("RUNTIME__DLTHUB_TELEMETRY", "false")
    os.environ.setdefault("DENTAL_DLT_DIR", str(DATA / ".dlt_pipelines"))
    if not skip_load:
        if WAREHOUSE.exists():
            WAREHOUSE.unlink()
        shutil.rmtree(os.environ["DENTAL_DLT_DIR"], ignore_errors=True)
        run_dlt()
        print("Loaded raw_nhsbsa with dlt")

    graph = compile_dataform()
    con = duckdb.connect(str(WAREHOUSE))
    results = execute_graph(con, graph)

    width = max(len(r["action"]) for r in results)
    for r in results:
        print(f'{r["action"]:<{width}}  {r["type"]:<9}  {r["status"]:<4}  rows={r["rows"]}')

    OUTPUT.mkdir(exist_ok=True)
    for table in ("dental_reporting.rpt_group_monthly", "dental_reporting.rpt_contract_financial_year",
                  "dental_marts.dq_exceptions"):
        out = OUTPUT / f'{table.split(".")[1]}.csv'
        con.execute(f"copy (select * from {table} order by all) to '{out}' (header)")
    (OUTPUT / "run_results.json").write_text(json.dumps(results, indent=2))
    draw_preview(con)
    con.close()

    failed = [r for r in results if r["status"] == "FAIL"]
    n_assert = sum(r["type"] == "assertion" for r in results)
    print(f"{len(results) - n_assert} models built, {n_assert - len(failed)} of {n_assert} assertions passed")
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-load", action="store_true")
    sys.exit(main(ap.parse_args().skip_load))
