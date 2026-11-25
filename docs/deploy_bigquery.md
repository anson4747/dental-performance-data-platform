# Running on Google Cloud

The local run uses DuckDB so the project can be tested anywhere. The same
code targets BigQuery without changes.

## 1. Load into BigQuery with dlt

```bash
export DENTAL_DESTINATION=bigquery
export DESTINATION__BIGQUERY__CREDENTIALS__PROJECT_ID=your-gcp-project-id
# service account key or `gcloud auth application-default login`
python ingestion/pipelines.py
```

This creates the `raw_nhsbsa` dataset.

## 2. Build the models with Dataform

1. Set `defaultProject` in `dataform/workflow_settings.yaml`.
2. Then:

```bash
npx dataform init-creds dataform   # once
npx dataform run dataform          # builds every model and runs every assertion
```

Or connect the repository to a Dataform repository in the Google Cloud
console and schedule a workflow.

## 3. Looker Studio

1. Connect a BigQuery data source to `dental_reporting.rpt_group_monthly`.
2. Build one page with:
   * `activity_month` on the time axis;
   * `uda_delivery_vs_pro_rata_target` by `provider_group`;
   * `courses_of_treatment` and `value_of_uda_delivered` as scorecards.
3. Add `rpt_contract_financial_year` as a second source for a contract table
   filtered on `delivery_band`.

## 4. Scheduling (not yet deployed)

The natural next step is to package `ingestion/download.py` and
`ingestion/pipelines.py` as a Cloud Run job, triggered monthly by Cloud
Scheduler after NHSBSA publishes, followed by a Dataform workflow run.
