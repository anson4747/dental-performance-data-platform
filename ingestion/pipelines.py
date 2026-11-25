"""dlt pipeline that lands NHSBSA dental open data in the warehouse.

Sources (NHS Business Services Authority Open Data Portal, Open Government
Licence 3.0):

  uda_contractor_YYYYMM.csv    English Contractor Monthly General Dental Activity
                               one row per dental contract per month
  contract_annual_YYYYMM.csv   English Contractor Monthly General Dental and
                               Orthodontic Contractual Dataset, a snapshot of
                               every contract line at that month

What this pipeline deals with, all found in the real files:

  * Two activity files (Apr and May 2025) are Windows-1252, not UTF-8.
    Each file is decoded as UTF-8 first, then Windows-1252, and the
    encoding used is recorded in the file manifest.
  * Header formatting varies between files (quoted, unquoted, a trailing
    space in "BAND_2A_DELIVERED "). Headers are trimmed and lower cased.
  * Columns change over time (LSOA11_CODE -> LSOA21_CODE,
    BAND_URGENT_DELIVERED -> BAND_UNSCHEDULED_DELIVERED,
    RECURRING_IND -> RECURRING_INDICATOR). Every value lands as text and
    dlt adds new columns as they appear; typing and renaming happen in
    Dataform staging, where the rules are visible and tested.
  * NHSBSA republishes corrected months. Activity merges on contract and
    month, so a corrected file replaces the earlier load instead of
    duplicating it.

Destination is DuckDB by default (local runs and CI). Set
DENTAL_DESTINATION=bigquery plus the usual dlt BigQuery credentials to load
into BigQuery instead.
"""

from __future__ import annotations

import csv
import io
import os
import re
from pathlib import Path

import dlt

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = ROOT / "data" / "raw"
DEFAULT_DUCKDB = ROOT / "data" / "warehouse.duckdb"

ACTIVITY_PATTERN = re.compile(r"uda_contractor_(\d{6})\.csv$")
CONTRACT_PATTERN = re.compile(r"contract_annual_(\d{6})\.csv$")


def read_csv_any_encoding(path: Path) -> tuple[list[dict], str]:
    """Return the rows of a CSV as dicts of strings, plus the encoding used."""
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - cp1252 decodes any byte sequence we have seen
        raise ValueError(f"Cannot decode {path.name}")
    reader = csv.reader(io.StringIO(text, newline=""))
    header = [h.strip().lower() for h in next(reader)]
    rows = []
    for values in reader:
        if not any(v.strip() for v in values):
            continue
        rows.append({h: (v.strip() if v.strip() != "" else None) for h, v in zip(header, values)})
    return rows, ("utf-8" if encoding == "utf-8-sig" else encoding)


@dlt.source(name="nhsbsa_dental")
def nhsbsa_dental(source_dir: Path = DEFAULT_SOURCE_DIR):
    # Read every file once up front, so the manifest is complete before
    # anything is yielded (dlt may interleave resources while extracting).
    files = {"activity": [], "contracts": []}
    manifest: list[dict] = []
    for path in sorted(source_dir.glob("*.csv")):
        for dataset, pattern in (("activity", ACTIVITY_PATTERN), ("contracts", CONTRACT_PATTERN)):
            match = pattern.search(path.name)
            if not match:
                continue
            rows, encoding = read_csv_any_encoding(path)
            files[dataset].append((path.name, match.group(1), rows))
            manifest.append({
                "source_file": path.name, "dataset": dataset, "file_month": match.group(1),
                "rows_in_file": len(rows), "encoding": encoding,
                "columns": ",".join(rows[0].keys()) if rows else "",
            })

    @dlt.resource(name="activity_monthly", write_disposition="merge",
                  primary_key=["contract_number", "file_month"])
    def activity_monthly():
        for name, file_month, rows in files["activity"]:
            for row in rows:
                yield {**row, "file_month": file_month, "source_file": name}

    @dlt.resource(name="contract_snapshots", write_disposition="merge",
                  primary_key=["source_file", "row_number"])
    def contract_snapshots():
        for name, file_month, rows in files["contracts"]:
            for i, row in enumerate(rows, start=1):
                yield {**row, "file_month": file_month, "source_file": name, "row_number": i}

    @dlt.resource(name="file_manifest", write_disposition="merge", primary_key="source_file")
    def file_manifest():
        yield from manifest

    return activity_monthly, contract_snapshots, file_manifest


def _destination():
    target = os.getenv("DENTAL_DESTINATION", "duckdb")
    if target == "duckdb":
        return dlt.destinations.duckdb(os.getenv("DENTAL_DUCKDB_PATH", str(DEFAULT_DUCKDB)))
    if target == "bigquery":
        return dlt.destinations.bigquery(location=os.getenv("DENTAL_BQ_LOCATION", "europe-west2"))
    raise ValueError(f"Unknown DENTAL_DESTINATION {target!r}")


def run(source_dir: Path = DEFAULT_SOURCE_DIR):
    pipeline = dlt.pipeline(
        pipeline_name="nhsbsa_dental_to_warehouse",
        destination=_destination(),
        dataset_name="raw_nhsbsa",
        pipelines_dir=os.getenv("DENTAL_DLT_DIR"),
    )
    return pipeline.run(nhsbsa_dental(source_dir))


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Load NHSBSA dental files with dlt")
    ap.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    print(run(ap.parse_args().source_dir))
