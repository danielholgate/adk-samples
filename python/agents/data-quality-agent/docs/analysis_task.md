# Task 1: Data Quality Analysis and Profiling Discovery

This document describes how the **Data Quality Agent** conducts data quality assessments and analyses within a Google Cloud Project. It details the methodologies, tools, and protocols the agent employs to discover profiling metadata, detect null values, and identify failing tables.

---

## 📋 Task Overview

The agent performs comprehensive discovery and analysis to understand the health and structure of tables inside a project's datasets. Specifically, the analysis is designed to answer three key questions:
1. **Is there data profiling information in Google Cloud Dataplex (Knowledge Catalog)?**
2. **Are there columns with high rates of null values?**
3. **Are there tables with failing data quality scores based on current Dataplex Data Quality scans?**

---

## 🛠️ Tools Employed

To execute this task, the agent integrates with the following tool suite:
*   **Dataplex Catalog Client (MCP Server)**: Uses `search_entries` and `get_entry_detail` to locate datasets, tables, and views, and inspect their schemas.
*   **Dataplex Quality & Profiling Client**:
    *   `get_project_data_quality_summary`: **[Highly Efficient]** Lists all quality and profiling scans and their latest results across the entire project in a single API call.
    *   `get_data_profiling_metadata`: Directly fetches the latest profiling results (e.g., null ratios, distinct counts, min/max values) for a specific table.
    *   `get_data_quality_scan_results`: Retrieves rule-by-rule success rates and overall data quality scores for a specific table.
*   **BigQuery Client (`execute_bigquery_query`)**: Performs direct SQL analysis (e.g., counting nulls, finding statistical anomalies) if profiling is unavailable.

---

## 📋 Step-by-Step Execution Protocol

The agent is designed to be highly efficient when handling requests, distinguishing between project-wide audits and single-table deep dives.

### Phase 1: Resource Discovery & Project-Wide Scan
1. **Project-Wide or Multi-Table Queries**:
   * When asked to analyze the entire project, a dataset, or multiple tables, the agent **always** calls `get_project_data_quality_summary` first.
   * This retrieves all scans and their latest results (scores, pass/fail status, row counts) in **one API call**.
   * The agent matches the project's tables against this summary to instantly identify which tables are passing, which are failing, and which lack scans.
2. **Single-Table Queries**:
   * If a specific table is requested, the agent searches for it using `search_entries` (with `project_id=cloud-summit-data-analytics`) and gets its schema via `get_entry_detail`.

### Phase 2: Dataplex Profiling Check
1. For target tables, the agent checks if there is active data profiling in Dataplex:
   * It reads this from the project summary, or calls `get_data_profiling_metadata` for a single table.
2. If profiling results exist, the agent extracts:
   * **Total Row Count**
   * **Null Ratio** for each column
   * **Distinct Ratio** (cardinality) for each column
3. If no profiling metadata is found in Dataplex, the agent skips direct query calculations and proceeds immediately to Phase 3 to check for quality scan metrics.

### Phase 3: Detailed Data Quality Scan Analysis
1. For target tables, the agent performs a deep-dive check on existing scan results by calling `get_data_quality_scan_results`.
2. It analyzes the scan results to check:
    * **Overall Data Quality Score** (e.g., 0% to 100%).
    * **Scan Status** (Passed vs. Failed).
    * **Failed Rules**: Which specific rules failed (e.g., a non-null rule on a column that now has nulls) and the count of violating rows.

### Phase 4: Direct Null Analysis (BigQuery - Fallback Only)
1. **Strict Fallback Policy**: The agent **only** queries BigQuery directly using `execute_bigquery_query` if:
   * Dataplex profiling is completely absent and no data quality scans exist for the table, OR
   * The user explicitly requests a real-time fresh query check.
2. The query calculates null counts and percentages for each column:
   ```sql
   SELECT 
     'column_name' as col,
     COUNT(*) - COUNT(column_name) as null_count,
     (COUNT(*) - COUNT(column_name)) / COUNT(*) * 100 as null_percentage
   FROM `project.dataset.table`
   ```
3. The agent formats the query results into a clean, readable Markdown table, explaining to the user that it fell back to direct query analysis due to missing Dataplex assets.

---

## 📊 Expected Output Format

The agent delivers a structured report containing:
1. **Summary Header**: Showing Table Name, Row Count, Dataplex Profiling Status, and Data Quality Scan Score.
2. **Metadata Catalog Context**: Details about the table's purpose.
3. **Data Profiling & Null Analysis Table**:
   | Column Name | Data Type | Null Count | Null Ratio | Distinct Ratio | Status / Risk |
   | :--- | :--- | :--- | :--- | :--- | :--- |
   | `customer_id` | STRING | 0 | 0.0% | 1.00 | ✅ Perfect |
   | `email` | STRING | 245 | 4.9% | 0.92 | ⚠️ Low Risk |
   | `phone` | STRING | 3,120 | 62.4% | 0.35 | 🚨 High Risk (Nulls) |
4. **Data Quality Scan Breakdown**: A list of defined rules, their dimensions (e.g., COMPLETENESS, VALIDITY), and their pass/fail status.
5. **Remediation Recommendation**: Actionable suggestions on which columns require new or stricter quality rules.

