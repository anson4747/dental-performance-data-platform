# Metric definitions

Every report uses these definitions and nothing else. If a figure in a
dashboard does not match one of these, the dashboard is wrong.

| Measure | Definition | Where |
|---|---|---|
| Course of treatment | One completed NHS course of treatment claim (FP17). Courses of treatment = Band 1 + Band 2 (2a, 2b, 2c) + Band 3 + Urgent or Unscheduled + Other. | `stg_activity.courses_of_treatment` |
| UDAs delivered | Units of Dental Activity scheduled in the month, as published (`UDA_DELIVERED`). Blank when no claims were submitted; counted as 0 with `activity_reported = false`. | `fct_contract_month.uda_delivered` |
| UDA target (annual) | The contract's UDA performance target for the financial year (`UDA_PERF_TARGET`), as stated in the latest month of that year. | `fct_contract_month.uda_target_annual` |
| Real UDA target | A target of at least `min_real_uda_target` (100). Smaller targets are placeholders on block funded contracts. | `has_real_uda_target` |
| UDA target to date | Annual target x months the contract reported in the year / 12. Blank without a real target. | `rpt_contract_financial_year.uda_target_to_date` |
| Delivery % | UDAs delivered / UDA target to date, for contracts with a real target only. | `delivery_pct`, `uda_delivery_vs_pro_rata_target` |
| Value per UDA | Annual UDA contract value (`UDA_FIN_VAL`) / annual UDA target. Blank outside the configured range (GBP 15 to 200) or without a real target. | `fct_contract_month.value_per_uda` |
| Value of UDAs delivered | UDAs delivered x value per UDA. | `value_of_uda_delivered` |
| UDA shortfall | Greater of (UDA target to date - UDAs delivered) and 0. | `uda_shortfall` |
| Value of UDA shortfall | UDA shortfall x value per UDA. An estimate of contracted activity not delivered, not a contract reconciliation. | `value_of_uda_shortfall` |
| Delivery band | At or above 100%; 96% to 100%; Below 96%; No real UDA target. | `delivery_band` |
| Financial year | NHS year, 1 April to 31 March, labelled FY2025-26. | `financial_year` |
| Dental group | Mapped from the contract holder name in that month through `ref_provider_group`; everything else is "Independent and other". | `provider_group` |

## Rules and thresholds

The thresholds are in `dataform/workflow_settings.yaml` (`vars`) so any
change is visible in review:

* `min_real_uda_target: 100`
* `min_value_per_uda: 15`
* `max_value_per_uda: 200`
