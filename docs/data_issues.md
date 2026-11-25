# Data issues found in the source files

Found while profiling the 19 real NHSBSA files (14 Nov 2026). Each item says
what was found, how it was found, and what the pipeline does with it. Counts
are from the current run; `dental_marts.dq_exceptions` lists every affected
contract.

## 1. Two files are not UTF-8

`uda_contractor_202504.csv` and `uda_contractor_202505.csv` contain a
Windows-1252 byte (`0xBF`) in one provider name ("Stanstead Dental Care ...").
The first load attempt failed on it.

**Handling:** decode as UTF-8, fall back to Windows-1252, record the encoding
per file in `raw_nhsbsa.file_manifest`, raise a `non_utf8_source_file`
exception. **Test:** `test_windows_1252_files_are_decoded_and_logged`.

## 2. The schema changed in April 2026

* `LSOA11_CODE` became `LSOA21_CODE`.
* `BAND_URGENT_DELIVERED` became `BAND_UNSCHEDULED_DELIVERED`.
* `YEAR_MONTH` changed from `202603` to `2026-04`.
* Every field became quoted.

The contract file renamed `RECURRING_IND` to `RECURRING_INDICATOR` and moved
dates from `dd/mm/yyyy` to `yyyy-mm-dd`.

**Handling:** dlt lands all values as text and adds new columns as they
appear. `stg_activity` and `stg_contract_snapshots` map old and new names and
formats into one typed shape. `assert_numeric_fields_parse` fails the build
if a value stops converting. **Test:**
`test_schema_change_in_april_2026_is_absorbed`.

## 3. Header quirks

The April 2025 header has a trailing space (`"BAND_2A_DELIVERED "`).

**Handling:** headers are trimmed and lower cased at read time.

## 4. Contracts listed with no activity

Between 185 and 288 contracts a month (3,770 contract months in total) have
a target and a contract value but every activity field blank. Our assertions
caught these as null UDAs.

**Handling:** rows are kept, flagged `activity_reported = false`, and
activity counts are set to zero, so they still count against target.
Exception: `no_activity_reported`.

## 5. Placeholder UDA targets

Some block funded contracts (dental schools, NHS trusts) carry a UDA target
of 1 against a contract value of over GBP 2 million. The resulting value per
UDA (GBP 2.4 million) inflated one group's yearly UDA value to GBP 579
million before the rule was added.

**Handling:** targets below 100 UDAs are treated as placeholders, and value
per UDA outside GBP 15 to 200 is blanked. Both thresholds are configurable,
and the affected contracts are listed as `no_real_uda_target` (714) and
`implausible_value_per_uda` (56). **Test:**
`test_placeholder_targets_cannot_distort_value_or_delivery`.

## 6. Commissioners merged, contracts changed hands

Commissioners went from 42 to 36 in April 2026, as ICBs merged. 2,457
contracts changed holder name, commissioner or postcode during the 16 months,
including 1,893 commissioner changes.

**Handling:** `dim_contract_history` is an SCD Type 2 dimension built from
the monthly files, and each month's activity is grouped under that month's
holder. **Tests:** `test_icb_mergers_regroup_commissioners`,
`test_change_of_contract_holder_creates_a_new_version`.

## 7. Contracts stop reporting

529 contracts in the March 2026 file are absent from April 2026, and 772 in
total stop reporting before the latest month.

**Handling:** they stay in history and are listed as `stopped_reporting`.
The reason is not in the data and needs the commissioner.

## 8. Republished months

NHSBSA corrected the April and May 2026 files in September 2026.

**Handling:** the activity load merges on contract and month, so loading a
corrected file replaces the old rows. **Test:**
`test_reload_does_not_duplicate_rows`.

## 9. Late claims

`LATE_SUBMITTED_FP17` spikes in some months (9,152 in Nov 2025, 47,961 in
Jul 2026, against about 1,500 to 3,000 normally). These are carried into the
group report for review. The cause is not explained in the data.
