// Raw tables landed by the dlt pipeline (ingestion/pipelines.py). Every value is text.
declare({
  schema: "raw_nhsbsa",
  name: "activity_monthly",
  description: "English Contractor Monthly General Dental Activity: one row per contract per month, merged on contract_number and file_month so republished months replace earlier loads.",
});
declare({
  schema: "raw_nhsbsa",
  name: "contract_snapshots",
  description: "English Contractor Monthly Contractual Dataset: every contract line in each snapshot file, as published.",
});
declare({
  schema: "raw_nhsbsa",
  name: "file_manifest",
  description: "One row per source file: rows read, encoding used and the header as received.",
});
