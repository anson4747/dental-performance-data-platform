"""Download the source files from the NHSBSA Open Data Portal.

Uses the portal's CKAN API (package_show) to list each dataset's monthly
resources, then downloads the months requested into data/raw/.

  python ingestion/download.py --from 202504 --to 202607 --contract-months 202503 202603 202607

The files used in this repository were downloaded on 14 Nov 2026.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import requests

API = "https://opendata.nhsbsa.net/api/3/action/package_show"
ACTIVITY = "english-contractor-monthly-general-dental-activity"
CONTRACTS = "english-contractor-monthly-general-dental-and-orthodontic-contractual-dataset"
ROOT = Path(__file__).resolve().parents[1]


def resources(dataset: str) -> list[dict]:
    response = requests.get(API, params={"id": dataset}, timeout=60)
    response.raise_for_status()
    return response.json()["result"]["resources"]


def download(dataset: str, keep, out_dir: Path) -> list[Path]:
    saved = []
    for res in resources(dataset):
        name = res["url"].rsplit("/", 1)[-1]
        month = re.search(r"_(\d{6})\.csv$", name)
        if not month or not keep(month.group(1)):
            continue
        path = out_dir / name
        with requests.get(res["url"], timeout=300, stream=True) as r:
            r.raise_for_status()
            with path.open("wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        saved.append(path)
        print("saved", name)
    return saved


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default="202504")
    ap.add_argument("--to", dest="end", default="202607")
    ap.add_argument("--contract-months", nargs="*", default=["202503", "202603", "202607"])
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "raw")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    download(ACTIVITY, lambda m: a.start <= m <= a.end, a.out)
    download(CONTRACTS, lambda m: m in a.contract_months, a.out)
