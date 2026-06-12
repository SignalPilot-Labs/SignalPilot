---
name: domain-healthcare
description: "Healthcare data science rules: encounter-based grain, clinical coding hierarchies, cost allocation, NULL semantics in clinical data."
---

# Healthcare Data Science

## Driving Table

When aggregating clinical metrics, drive FROM the fact/event table (encounters, procedures, diagnoses), not the dimension table (patients, providers). Patients with zero encounters MUST NOT appear in utilization reports - they have no data to aggregate.

## Encounter-Based Grain

One patient encounter generates multiple diagnoses, procedures, medications, and cost entries. The grain of clinical fact tables is the EVENT (diagnosis, procedure), not the encounter or patient.

Do NOT aggregate to patient level without first verifying whether the task asks for patient-level or encounter-level output. Premature patient-level aggregation destroys per-encounter detail.

## Clinical Code Hierarchies

Healthcare coding systems are hierarchical - a parent code rolls up child codes:

- **ICD** (International Classification of Diseases) - diagnoses and conditions
- **CPT** (Current Procedural Terminology) - physician procedures
- **HCPCS** (Healthcare Common Procedure Coding System) - equipment, supplies, non-physician services
- **SNOMED CT** - clinical terms (conditions, procedures, substances)
- **DRG** (Diagnosis Related Groups) - inpatient payment grouping (MS-DRG for Medicare, APR-DRG for all-payer)
- **NUCC** (National Uniform Claim Committee) - provider taxonomy/specialty codes
- **LOINC** - lab tests and clinical observations
- **NDC** (National Drug Codes) - drug/medication identifiers
- **RxNorm** - normalized drug names
- **NPI** (National Provider Identifier) - provider identification
- **APC** (Ambulatory Payment Classification) - outpatient payment grouping
- **Revenue Codes** - facility billing line items
- **Place of Service Codes** - where care was delivered

When the task asks for a "condition" or "procedure category," check whether the project maps to a specific hierarchy level. Use the mapping table's grain, not a substring of the code.

When multiple codes map to one encounter, the encounter appears multiple times in the fact table - this is correct grain, not a duplicate.

## Taxonomy and Crosswalk Tables

When building a mapping between a complete taxonomy (all codes) and a partial crosswalk (only some codes have mappings), drive FROM the complete taxonomy table. LEFT JOIN the crosswalk onto it. Codes without a crosswalk mapping get NULL - that is correct, they are unmapped codes.

Driving from the crosswalk drops all codes that have no mapping, producing an incomplete taxonomy.

## Cost Allocation

Healthcare costs are allocated across diagnoses and procedures within an encounter. SUM(cost) across all rows for a patient double-counts shared encounter costs.

When the task asks for "total cost," verify whether costs are pre-allocated (sum is correct) or shared (need to deduplicate by encounter first).

## NULL Semantics

In clinical data, NULL means "not recorded," which is clinically different from "not present." A NULL diagnosis does NOT mean the patient is healthy - it means the data is incomplete.

NEVER filter NULL clinical columns unless the task explicitly excludes incomplete records. Filtering NULLs in clinical data silently drops patients with missing documentation.
