"""End to end and unit tests.

The end to end fixture loads the real NHSBSA files with dlt, compiles the
Dataform project and runs every model and assertion on DuckDB, once per test
session. The tests then check behaviour that matters to the people using the
reports, using facts found in the source files.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingestion.pipelines import read_csv_any_encoding  # noqa: E402
from scripts import run_local  # noqa: E402

RAW = ROOT / "data" / "raw"


@pytest.fixture(scope="session")
def warehouse():
    exit_code = run_local.main(skip_load=False)
    con = duckdb.connect(str(run_local.WAREHOUSE), read_only=True)
    yield exit_code, con
    con.close()


def scalar(con, sql):
    return con.execute(sql).fetchone()[0]


# --- whole pipeline -------------------------------------------------------

def test_every_assertion_passes(warehouse):
    exit_code, _ = warehouse
    results = json.loads((ROOT / "output" / "run_results.json").read_text())
    failed = [r["action"] for r in results if r["status"] == "FAIL"]
    assert failed == []
    assert exit_code == 0


def test_all_sixteen_months_loaded_once(warehouse):
    _, con = warehouse
    assert scalar(con, "select count(distinct activity_month) from dental_marts.fct_contract_month") == 16
    assert scalar(con, "select count(*) from raw_nhsbsa.activity_monthly") == scalar(
        con, "select sum(rows_in_file) from raw_nhsbsa.file_manifest where dataset = 'activity'")


def test_financial_year_uda_matches_files_read_independently(warehouse):
    """Recompute FY2025-26 UDAs straight from the CSVs in Python, without SQL."""
    _, con = warehouse
    expected = 0.0
    for month in ["202504", "202505", "202506", "202507", "202508", "202509",
                  "202510", "202511", "202512", "202601", "202602", "202603"]:
        rows, _ = read_csv_any_encoding(RAW / f"uda_contractor_{month}.csv")
        expected += sum(float(r["uda_delivered"]) for r in rows if r["uda_delivered"])
    actual = scalar(con, "select sum(uda_delivered) from dental_reporting.rpt_contract_financial_year "
                         "where financial_year = 'FY2025-26'")
    assert actual == pytest.approx(expected, abs=0.01)


# --- problems found in the real files ---------------------------------------

def test_windows_1252_files_are_decoded_and_logged(warehouse):
    _, con = warehouse
    files = [r[0] for r in con.execute(
        "select source_file from raw_nhsbsa.file_manifest where encoding = 'cp1252' order by 1").fetchall()]
    assert files == ["uda_contractor_202504.csv", "uda_contractor_202505.csv"]
    name = scalar(con, "select provider_name from dental_staging.stg_activity "
                       "where contract_number = '3603410001' and activity_month = '2025-04-01'")
    assert name.startswith("Stanstead Dental Care")


def test_schema_change_in_april_2026_is_absorbed(warehouse):
    _, con = warehouse
    vintages = dict(con.execute(
        "select activity_month >= '2026-04-01', any_value(lsoa_vintage) from dental_staging.stg_activity "
        "where activity_reported group by 1").fetchall())
    assert vintages == {False: "2011", True: "2021"}
    # the renamed urgent / unscheduled band still carries values after the rename
    after = scalar(con, "select sum(band_urgent_unscheduled) from dental_staging.stg_activity "
                        "where activity_month = '2026-04-01'")
    before = scalar(con, "select sum(band_urgent_unscheduled) from dental_staging.stg_activity "
                         "where activity_month = '2026-03-01'")
    assert before > 0 and after > 0


def test_icb_mergers_regroup_commissioners(warehouse):
    _, con = warehouse
    assert scalar(con, "select count(distinct commissioner_code) from dental_marts.fct_contract_month "
                       "where activity_month = '2026-03-01'") == 42
    assert scalar(con, "select count(distinct commissioner_code) from dental_marts.fct_contract_month "
                       "where activity_month = '2026-04-01'") == 36


def test_change_of_contract_holder_creates_a_new_version(warehouse):
    _, con = warehouse
    versions = con.execute(
        "select provider_name, valid_from, valid_to, is_current from dental_marts.dim_contract_history "
        "where contract_number = '1000080000' order by version").fetchall()
    assert [v[0] for v in versions] == ["Raby Road Dental Centre", "Luke Sergeant"]
    assert str(versions[1][1]) == "2025-06-01" and versions[1][3] is True
    assert versions[0][2] == versions[1][1]


def test_blank_activity_rows_count_as_zero_and_are_flagged(warehouse):
    _, con = warehouse
    blank = scalar(con, "select count(*) from dental_marts.fct_contract_month where not activity_reported")
    assert blank > 0
    assert scalar(con, "select max(uda_delivered) from dental_marts.fct_contract_month "
                       "where not activity_reported") == 0
    assert scalar(con, "select count(*) from dental_marts.dq_exceptions "
                       "where exception_type = 'no_activity_reported'") > 0


def test_placeholder_targets_cannot_distort_value_or_delivery(warehouse):
    _, con = warehouse
    # dental school contracts carry a UDA target of 1 against millions of pounds
    assert scalar(con, "select count(*) from dental_marts.fct_contract_month "
                       "where uda_target_annual = 1 and value_per_uda is not null") == 0
    assert scalar(con, "select max(value_per_uda) from dental_marts.fct_contract_month") <= 200
    assert scalar(con, "select count(*) from dental_reporting.rpt_contract_financial_year "
                       "where not has_real_uda_target and delivery_pct is not null") == 0


def test_reload_does_not_duplicate_rows(warehouse):
    _, con = warehouse
    before = scalar(con, "select count(*) from raw_nhsbsa.activity_monthly")
    con.close()
    from ingestion.pipelines import run
    run()
    with duckdb.connect(str(run_local.WAREHOUSE), read_only=True) as again:
        assert scalar(again, "select count(*) from raw_nhsbsa.activity_monthly") == before


# --- units ------------------------------------------------------------------

def test_reader_falls_back_to_cp1252_and_trims_headers(tmp_path):
    path = tmp_path / "uda_contractor_209901.csv"
    path.write_bytes(b'CONTRACT_NUMBER,"BAND_2A_DELIVERED ",PROVIDER_NAME\r\n1,5,"Caf\xe9 Dental"\r\n')
    rows, encoding = read_csv_any_encoding(path)
    assert encoding == "cp1252"
    assert rows == [{"contract_number": "1", "band_2a_delivered": "5", "provider_name": "Café Dental"}]


def test_bigquery_date_parsing_translates_to_duckdb():
    sql = run_local.to_duckdb("select safe.parse_date('%d/%m/%Y', d) from `proj.ds.t`")
    assert "TRY_STRPTIME" in sql and "proj" not in sql
    with duckdb.connect() as con:
        assert str(con.execute(run_local.to_duckdb(
            "select safe.parse_date('%d/%m/%Y', '01/04/2025')")).fetchone()[0]) == "2025-04-01"
        assert con.execute(run_local.to_duckdb(
            "select safe.parse_date('%d/%m/%Y', '2025-04-01')")).fetchone()[0] is None
