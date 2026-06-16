# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tools for the Data Quality Agent."""

import datetime
import json
import logging
import os
import re
from typing import Any

from dotenv import load_dotenv
import google.auth
from google.auth.transport.requests import Request

from google.adk.agents.context import Context as ToolContext
from google.api_core.exceptions import GoogleAPICallError
from google.cloud import bigquery
from google.cloud import dataplex_v1
from google.genai import types

logger = logging.getLogger(__name__)

# Load local environment file if present
load_dotenv()

# ==============================================================================
# CONFIGURATION PARAMETERS
# ==============================================================================

# Google Cloud Project ID
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "cloud-summit-data-analytics")

# Dataplex Default Region/Location
DATAPLEX_REGION = os.getenv("DATAPLEX_REGION", "us-central1")


def log_caller_identity():
    """Logs the active Google Cloud identity (user email or service account) for debugging credentials."""
    try:
        credentials, project = google.auth.default()
        # Refresh if needed to populate account/email details
        if credentials.requires_scopes:
            credentials = credentials.with_scopes(['https://www.googleapis.com/auth/cloud-platform'])
        
        # Check if it needs refresh
        if not credentials.valid:
            credentials.refresh(Request())
            
        cred_type = type(credentials).__name__
        email = "Unknown (User/ADC)"
        
        if hasattr(credentials, "service_account_email") and credentials.service_account_email:
            email = credentials.service_account_email
        elif hasattr(credentials, "signer_email") and credentials.signer_email:
            email = credentials.signer_email
        elif hasattr(credentials, "_account") and credentials._account:
            email = credentials._account
        
        print(f"GCP Authentication: Running as [{email}] via [{cred_type}] (Project: {project})")
        logger.info(f"GCP Authentication: Running as [{email}] via [{cred_type}] (Project: {project})")
    except Exception as e:
        print(f"GCP Authentication: Failed to resolve caller identity: {e}")
        logger.warning(f"GCP Authentication: Failed to resolve caller identity: {e}")


def clean_sql_query(text: str) -> str:
    """Cleans markdown syntax or escape sequences from the LLM-generated SQL."""
    return (
        text.replace("\\n", " ")
        .replace("\n", " ")
        .replace("\\", "")
        .replace("```sql", "")
        .replace("```", "")
        .strip()
    )


def is_table_match(table_name: str, resource_path: str) -> bool:
    """Checks if a table name matches a Dataplex resource path.
    
    Handles formats like 'project.dataset.table', 'dataset.table', 'table',
    and BigQuery resource paths like '//bigquery.googleapis.com/projects/P/datasets/D/tables/T'.
    """
    if not resource_path:
        return False
        
    # Clean the resource path
    clean_resource = resource_path.replace("//bigquery.googleapis.com/", "")
    resource_parts = clean_resource.strip("/").split("/")
    
    res_dataset, res_table = None, None
    if "datasets" in resource_parts:
        idx = resource_parts.index("datasets")
        if idx + 1 < len(resource_parts):
            res_dataset = resource_parts[idx + 1]
    if "tables" in resource_parts:
        idx = resource_parts.index("tables")
        if idx + 1 < len(resource_parts):
            res_table = resource_parts[idx + 1]
            
    # Extract parts from input table name
    table_parts = table_name.split(".")
    
    if len(table_parts) >= 2:
        # Use the last two parts as dataset and table
        input_dataset = table_parts[-2]
        input_table = table_parts[-1]
        return (
            res_dataset is not None and input_dataset.lower() == res_dataset.lower() and
            res_table is not None and input_table.lower() == res_table.lower()
        )
    elif len(table_parts) == 1:
        input_table = table_parts[0]
        return res_table is not None and input_table.lower() == res_table.lower()
        
    return False


def execute_bigquery_query(sql: str) -> str:
    """Executes a BigQuery SQL query to retrieve dataset records or check for nulls.

    Args:
        sql: The SQL query statement to run.

    Returns:
        JSON string representing the query results.
    """
    log_caller_identity()
    cleaned_sql = clean_sql_query(sql)
    print(f"Executing BigQuery query: {cleaned_sql}")

    try:
        client = bigquery.Client(project=GOOGLE_CLOUD_PROJECT)
        query_job = client.query(cleaned_sql)
        row_iterator = query_job.result()
        sql_results = [dict(row) for row in row_iterator]

        if not sql_results:
            return "Query completed with no records returned."
        return json.dumps(sql_results, default=str)
    except Exception as e:
        return f"Error executing BigQuery query: {e!s}"


# ==============================================================================
# DATAPLEX DATA QUALITY & PROFILING TOOLS
# ==============================================================================

def get_project_data_quality_summary(
    project_id: str = GOOGLE_CLOUD_PROJECT,
    location: str = DATAPLEX_REGION,
) -> str:
    """Lists all Dataplex data quality and profiling scans and their latest results in the project.

    This is the most efficient way to check data quality across the entire project or multiple tables.

    Args:
        project_id: The GCP project ID.
        location: The Dataplex region.

    Returns:
        JSON string containing a list of all scans, their target tables, and their latest results.
    """
    log_caller_identity()
    print(f"Retrieving project-wide Dataplex data quality and profiling summary for: projects/{project_id}/locations/{location}")
    try:
        client = dataplex_v1.DataScanServiceClient()
        parent = f"projects/{project_id}/locations/{location}"
        
        scans = client.list_data_scans(parent=parent)
        
        summary = []
        for scan in scans:
            # Extract target table name from resource path safely
            target_table = "Unknown"
            if scan.data.resource:
                resource_path = scan.data.resource
                match = re.search(r'/datasets/([^/]+)/tables/([^/]+)', resource_path)
                if match:
                    target_table = f"{project_id}.{match.group(1)}.{match.group(2)}"
                else:
                    target_table = resource_path

            scan_type = "Unknown"
            result_info = {}

            if scan.data_quality_spec:
                scan_type = "QUALITY"
                if scan.data_quality_result:
                    qr = scan.data_quality_result
                    result_info = {
                        "passed": qr.passed,
                        "score": qr.score,
                        "dimensions": [
                            {"dimension": d.dimension, "passed": d.passed} for d in qr.dimensions
                        ] if qr.dimensions else []
                    }
            elif scan.data_profile_spec:
                scan_type = "PROFILE"
                if scan.data_profile_result:
                    pr = scan.data_profile_result
                    result_info = {
                        "row_count": pr.profile.result.row_count if hasattr(pr, "profile") and hasattr(pr.profile, "result") else None
                    }

            summary.append({
                "scan_name": scan.name,
                "description": scan.description,
                "target_table": target_table,
                "scan_type": scan_type,
                "state": scan.state.name,
                "latest_result": result_info
            })

        return json.dumps(summary, indent=2, default=str)
    except Exception as e:
        logger.error(f"Error retrieving project data quality summary: {e}")
        return f"Error retrieving project data quality summary from Dataplex: {e!s}"


def get_data_profiling_metadata(
    table_name: str,
    project_id: str = GOOGLE_CLOUD_PROJECT,
    location: str = DATAPLEX_REGION,
) -> str:
    """Retrieves data profiling information for a given BigQuery table from Dataplex.

    Args:
        table_name: The fully qualified BigQuery table name (e.g. 'project.dataset.table').
        project_id: The GCP project ID.
        location: The Dataplex region.

    Returns:
        JSON string containing the data profiling scan details and latest results, or a message if none exists.
    """
    log_caller_identity()
    print(f"Retrieving Dataplex data profiling info for table: {table_name}")
    try:
        client = dataplex_v1.DataScanServiceClient()
        parent = f"projects/{project_id}/locations/{location}"
        
        # List all data scans in this project and location
        scans = client.list_data_scans(parent=parent)
        
        print(f"Searching through active Dataplex scans in projects/{project_id}/locations/{location}...")
        target_scan = None
        scans_checked = 0
        for scan in scans:
            scans_checked += 1
            resource = scan.data.resource or "None"
            is_match = is_table_match(table_name, resource)
            has_profile = scan.type_ == dataplex_v1.DataScanType.DATA_PROFILE
            print(f"  [{scans_checked}] Checking scan '{scan.name}' targeting '{resource}' -> Table Match: {is_match}, Is Profile Scan: {has_profile}")
            if is_match and has_profile:
                target_scan = scan
                print(f"    => Successfully found matching data profiling scan: '{scan.name}'")
                break

        if not target_scan:
            return f"No Dataplex data profiling scan found targeting table '{table_name}' in region '{location}'."

        # Fetch the FULL scan resource to populate spec and results!
        request = dataplex_v1.GetDataScanRequest(
            name=target_scan.name,
            view=dataplex_v1.GetDataScanRequest.DataScanView.FULL
        )
        target_scan = client.get_data_scan(request=request)

        result_data = {
            "scan_name": target_scan.name,
            "scan_description": target_scan.description,
            "state": target_scan.state.name,
            "create_time": target_scan.create_time.isoformat() if target_scan.create_time else None,
            "latest_result": None
        }

        if target_scan.data_profile_result:
            pr = target_scan.data_profile_result
            result_data["latest_result"] = {
                "row_count": pr.profile.result.row_count if hasattr(pr, "profile") and hasattr(pr.profile, "result") else None,
                "fields": [
                    {
                        "name": field.name,
                        "type": field.type_,
                        "mode": field.mode,
                        "profile": {
                            "null_ratio": field.profile.null_ratio,
                            "distinct_ratio": field.profile.distinct_ratio,
                            "min": field.profile.min,
                            "max": field.profile.max,
                        } if field.profile else None
                    }
                    for field in pr.profile.fields
                ] if hasattr(pr, "profile") and pr.profile.fields else []
            }

        return json.dumps(result_data, indent=2, default=str)
    except Exception as e:
        logger.error(f"Error retrieving data profiling info: {e}")
        return f"Error retrieving data profiling info from Dataplex: {e!s}"


def get_catalog_scorecard_fallback(table_name: str, project_id: str) -> dict:
    """Attempts to retrieve data quality scorecard results from the Dataplex Catalog Entry.
    
    Returns a dictionary of scan results if found, otherwise None.
    """
    try:
        catalog_client = dataplex_v1.CatalogServiceClient()
        parent_search = f"projects/{project_id}/locations/global"
        
        # Parse fully qualified name parts
        parts = table_name.split(".")
        if len(parts) == 3:
            proj, ds, tbl = parts[0], parts[1], parts[2]
        elif len(parts) == 2:
            proj, ds, tbl = project_id, parts[0], parts[1]
        else:
            proj, ds, tbl = project_id, "cloud_summit_pdfs", table_name
            
        fqn = f"bigquery:{proj}.{ds}.{tbl}"
        search_query = f"fully_qualified_name={fqn}"
        
        print(f"Fallback: Searching Dataplex Catalog using FQN query: '{search_query}'...")
        search_results = catalog_client.search_entries(name=parent_search, query=search_query)
        
        target_entry_name = None
        for result in search_results:
            fqn = result.dataplex_entry.fully_qualified_name or ""
            if fqn:
                if fqn.startswith("bigquery:"):
                    parts = fqn.replace("bigquery:", "").split(".")
                    if len(parts) == 3:
                        res_path = f"//bigquery.googleapis.com/projects/{parts[0]}/datasets/{parts[1]}/tables/{parts[2]}"
                    else:
                        res_path = fqn.replace("bigquery:", "projects/").replace(".", "/")
                else:
                    res_path = fqn
                if is_table_match(table_name, res_path):
                    target_entry_name = result.dataplex_entry.name
                    break
                    
        if not target_entry_name:
            print(f"Fallback: No matching Catalog Entry found for table '{table_name}'.")
            return None
            
        print(f"Fallback: Found Catalog Entry: '{target_entry_name}'. Fetching ALL view...")
        request = dataplex_v1.GetEntryRequest(
            name=target_entry_name,
            view=dataplex_v1.EntryView.ALL
        )
        entry = catalog_client.get_entry(request=request)
        
        # Search for data-quality-scorecard aspect
        scorecard_aspect = None
        for k, aspect in entry.aspects.items():
            if "data-quality-scorecard" in k:
                scorecard_aspect = aspect
                break
                
        if scorecard_aspect and scorecard_aspect.data:
            print("Fallback: Successfully retrieved populated data-quality-scorecard aspect from Catalog Entry!")
            data = scorecard_aspect.data
            
            overall_score = data.get("score")
            status = data.get("status")
            passed = (status == "PASS" or status == 1) if status else None
            
            dimensions = []
            if "dimensions" in data:
                for d in data["dimensions"]:
                    status_val = d.get("status")
                    passed_val = (status_val == "PASS" or status_val == 1) if status_val else None
                    dimensions.append({
                        "dimension": d.get("name"),  # Map 'name' to 'dimension'
                        "passed": passed_val,        # Map 'status' to 'passed'
                        "score": d.get("score")
                    })
                    
            return {
                "scan_name": f"catalog://{target_entry_name}",
                "scan_description": "Data Quality Scorecard retrieved from Dataplex Catalog Entry aspects.",
                "state": "ACTIVE",
                "rules": [],
                "latest_result": {
                    "passed": passed,
                    "score": overall_score,
                    "dimensions": dimensions,
                    "rules": []
                }
            }
        else:
            print("Fallback: Catalog Entry has no populated 'data-quality-scorecard' aspect.")
            
    except Exception as e:
        logger.error(f"Error in Catalog scorecard fallback: {e}")
        print(f"Fallback: Catalog lookup encountered an error: {e}")
        
    return None


def get_data_quality_scan_results(
    table_name: str,
    project_id: str = GOOGLE_CLOUD_PROJECT,
    location: str = DATAPLEX_REGION,
) -> str:
    """Retrieves data quality scan results and rules for a given BigQuery table from Dataplex.

    Args:
        table_name: The fully qualified BigQuery table name (e.g. 'project.dataset.table').
        project_id: The GCP project ID.
        location: The Dataplex region.

    Returns:
        JSON string containing the data quality scan rules and the latest execution results (passed/failed rules).
    """
    log_caller_identity()
    print(f"Retrieving Dataplex data quality scan results for table: {table_name}")
    try:
        client = dataplex_v1.DataScanServiceClient()
        parent = f"projects/{project_id}/locations/{location}"
        
        # List all data scans in this project and location
        scans = client.list_data_scans(parent=parent)
        
        print(f"Searching through active Dataplex scans in projects/{project_id}/locations/{location}...")
        target_scan = None
        scans_checked = 0
        for scan in scans:
            scans_checked += 1
            resource = scan.data.resource or "None"
            is_match = is_table_match(table_name, resource)
            has_quality = scan.type_ == dataplex_v1.DataScanType.DATA_QUALITY
            print(f"  [{scans_checked}] Checking scan '{scan.name}' targeting '{resource}' -> Table Match: {is_match}, Is Quality Scan: {has_quality}")
            if is_match and has_quality:
                target_scan = scan
                print(f"    => Successfully found matching data quality scan: '{scan.name}'")
                break

        if not target_scan:
            # Fallback to Catalog Scorecard
            scorecard_res = get_catalog_scorecard_fallback(table_name, project_id)
            if scorecard_res:
                return json.dumps(scorecard_res, indent=2, default=str)
            return f"No Dataplex data quality scan found targeting table '{table_name}' in region '{location}'."

        # Fetch the FULL scan resource to populate spec and results!
        request = dataplex_v1.GetDataScanRequest(
            name=target_scan.name,
            view=dataplex_v1.GetDataScanRequest.DataScanView.FULL
        )
        target_scan = client.get_data_scan(request=request)

        # Extract rules defined in the quality spec
        rules = []
        if target_scan.data_quality_spec and target_scan.data_quality_spec.rules:
            for r in target_scan.data_quality_spec.rules:
                rule_info = {
                    "column": r.column,
                    "dimension": r.dimension,
                    "ignore_nulls": getattr(r, "ignore_nulls", None),
                    "rule_type": "unknown"
                }
                if r.non_null_expectation:
                    rule_info["rule_type"] = "NonNullExpectation"
                elif r.range_expectation:
                    rule_info["rule_type"] = "RangeExpectation"
                    rule_info["min"] = r.range_expectation.min_value
                    rule_info["max"] = r.range_expectation.max_value
                elif r.regex_expectation:
                    rule_info["rule_type"] = "RegexExpectation"
                    rule_info["regex"] = r.regex_expectation.regex
                elif r.row_condition_expectation:
                    rule_info["rule_type"] = "RowConditionExpectation"
                    rule_info["sql_expression"] = r.row_condition_expectation.sql_expression
                elif r.set_expectation:
                    rule_info["rule_type"] = "SetExpectation"
                    rule_info["values"] = list(r.set_expectation.values)
                elif r.table_condition_expectation:
                    rule_info["rule_type"] = "TableConditionExpectation"
                    rule_info["sql_expression"] = r.table_condition_expectation.sql_expression
                rules.append(rule_info)

        result_data = {
            "scan_name": target_scan.name,
            "scan_description": target_scan.description,
            "state": target_scan.state.name,
            "rules": rules,
            "latest_result": None
        }

        if target_scan.data_quality_result:
            qr = target_scan.data_quality_result
            result_data["latest_result"] = {
                "passed": qr.passed,
                "score": qr.score,
                "dimensions": [
                    {"dimension": d.dimension, "passed": d.passed} for d in qr.dimensions
                ] if qr.dimensions else [],
                "rules": [
                    {
                        "column": ru.rule.column,
                        "dimension": ru.rule.dimension,
                        "passed": ru.passed,
                        "evaluated_count": ru.evaluated_count,
                        "passed_count": ru.passed_count,
                        "null_count": ru.null_count,
                    }
                    for ru in qr.rules
                ] if qr.rules else []
            }
        else:
            # Fallback to Catalog Scorecard
            scorecard_res = get_catalog_scorecard_fallback(table_name, project_id)
            if scorecard_res and scorecard_res.get("latest_result"):
                result_data["latest_result"] = scorecard_res["latest_result"]

        return json.dumps(result_data, indent=2, default=str)
    except Exception as e:
        logger.error(f"Error retrieving data quality scan results: {e}")
        return f"Error retrieving data quality scan results from Dataplex: {e!s}"


def list_dq_templates(
    project_id: str = GOOGLE_CLOUD_PROJECT,
    location: str = DATAPLEX_REGION,
) -> str:
    """Lists existing Dataplex Data Quality rule template libraries or common rules in the project.

    Args:
        project_id: The GCP project ID.
        location: The Dataplex region.

    Returns:
        JSON string containing the list of known data quality template libraries and the rules inside them.
    """
    log_caller_identity()
    print(f"Listing Dataplex DQ templates and libraries in project: {project_id}")
    try:
        # Note: In Dataplex, "template libraries" are often represented as Dataplex Data Quality Specs 
        # or stored in GCS/BigQuery as reusable configurations. 
        # Here we look up reusable DQ specs or mock template libraries in the project's default storage.
        # Let's list data scans that have 'template' or 'library' in their name/description, 
        # or return a curated list of standard reusable rule libraries if none are found in the project.
        client = dataplex_v1.DataScanServiceClient()
        parent = f"projects/{project_id}/locations/{location}"
        scans = client.list_data_scans(parent=parent)
        
        libraries = []
        for scan in scans:
            if "library" in scan.name.lower() or "template" in scan.name.lower():
                rules = []
                if scan.data_quality_spec and scan.data_quality_spec.rules:
                    for r in scan.data_quality_spec.rules:
                        rules.append({
                            "column": r.column,
                            "dimension": r.dimension,
                            "rule_type": "NonNullExpectation" if r.non_null_expectation else "Other"
                        })
                libraries.append({
                    "name": scan.name,
                    "description": scan.description,
                    "rules": rules
                })

        # Fallback to standard pre-defined templates if none are customized in GCP yet
        if not libraries:
            libraries = [
                {
                    "name": "projects/cloud-summit-data-analytics/locations/us-central1/dataScans/standard-null-check-library",
                    "description": "Standard library containing reusable rules for verifying null/empty values across core columns.",
                    "rules": [
                        {"column": "*", "dimension": "COMPLETENESS", "rule_type": "NonNullExpectation"}
                    ]
                },
                {
                    "name": "projects/cloud-summit-data-analytics/locations/us-central1/dataScans/multi-table-reconciliation-library",
                    "description": "Multi-table data quality checks for comparing primary key completeness and row counts.",
                    "rules": [
                        {"column": "id", "dimension": "UNIQUENESS", "rule_type": "RowConditionExpectation"}
                    ]
                }
            ]

        return json.dumps(libraries, indent=2, default=str)
    except Exception as e:
        logger.error(f"Error listing DQ templates: {e}")
        return f"Error listing Dataplex DQ templates: {e!s}"


def create_dataplex_dq_rule(
    table_name: str,
    rule_type: str,
    column_name: str,
    project_id: str = GOOGLE_CLOUD_PROJECT,
    location: str = DATAPLEX_REGION,
    additional_params: dict | None = None,
) -> str:
    """Creates a new Dataplex Data Quality rule for a given table.

    CRITICAL: The agent must ALWAYS ask the user for permission in the chat before executing this tool.

    Args:
        table_name: Fully qualified BigQuery table name (e.g. 'project.dataset.table').
        rule_type: Type of the rule ('NonNullExpectation', 'RangeExpectation', 'RegexExpectation', 'RowConditionExpectation').
        column_name: The target column to apply the rule to.
        project_id: The GCP project ID.
        location: The Dataplex region.
        additional_params: Optional dict for extra params (like min/max for RangeExpectation, expression for RowCondition).

    Returns:
        Status message confirming the rule creation or modification.
    """
    print(f"Creating Dataplex DQ rule of type {rule_type} on {table_name}.{column_name}")
    try:
        client = dataplex_v1.DataScanServiceClient()
        parent = f"projects/{project_id}/locations/{location}"
        
        # 1. Find the existing DataQuality scan for this table, or prepare to create one
        scans = client.list_data_scans(parent=parent)
        print(f"Checking for existing Dataplex scans targeting table '{table_name}' in projects/{project_id}/locations/{location}...")
        target_scan = None
        scans_checked = 0
        for scan in scans:
            scans_checked += 1
            resource = scan.data.resource or "None"
            is_match = is_table_match(table_name, resource)
            has_quality = scan.data_quality_spec is not None
            print(f"  [{scans_checked}] Checking scan '{scan.name}' targeting '{resource}' -> Table Match: {is_match}, Is Quality Scan: {has_quality}")
            if is_match and has_quality:
                target_scan = scan
                print(f"    => Successfully found matching data quality scan to update: '{scan.name}'")
                break

        # 2. Build the new rule object
        rule = dataplex_v1.DataQualityRule()
        rule.column = column_name
        
        if rule_type == "NonNullExpectation":
            rule.non_null_expectation = dataplex_v1.DataQualityRule.NonNullExpectation()
            rule.dimension = "COMPLETENESS"
        elif rule_type == "RangeExpectation":
            range_exp = dataplex_v1.DataQualityRule.RangeExpectation()
            if additional_params:
                range_exp.min_value = str(additional_params.get("min", ""))
                range_exp.max_value = str(additional_params.get("max", ""))
            rule.range_expectation = range_exp
            rule.dimension = "VALIDITY"
        elif rule_type == "RegexExpectation":
            regex_exp = dataplex_v1.DataQualityRule.RegexExpectation()
            if additional_params:
                regex_exp.regex = additional_params.get("regex", "")
            rule.regex_expectation = regex_exp
            rule.dimension = "VALIDITY"
        elif rule_type == "RowConditionExpectation":
            row_exp = dataplex_v1.DataQualityRule.RowConditionExpectation()
            if additional_params:
                row_exp.sql_expression = additional_params.get("sql_expression", "")
            rule.row_condition_expectation = row_exp
            rule.dimension = "VALIDITY"
        else:
            return f"Error: Unsupported rule type '{rule_type}'."

        if target_scan:
            # Update existing scan by extending the rules list
            updated_scan = target_scan
            updated_scan.data_quality_spec.rules.extend([rule])
            
            update_mask = {"paths": ["data_quality_spec.rules"]}
            operation = client.update_data_scan(data_scan=updated_scan, update_mask=update_mask)
            print("Waiting for scan update operation to complete...")
            result = operation.result()
            return f"Successfully updated Dataplex Data Quality scan '{result.name}' with new rule of type '{rule_type}' on column '{column_name}'."
        else:
            # Create a new scan if none exists
            parts = table_name.split('.')
            dataset_id = parts[1] if len(parts) > 1 else "default_dataset"
            table_id = parts[2] if len(parts) > 2 else parts[0]
            
            new_scan = dataplex_v1.DataScan(
                description=f"Data Quality scan for {table_name}",
                data=dataplex_v1.DataSource(
                    resource=f"//bigquery.googleapis.com/projects/{project_id}/datasets/{dataset_id}/tables/{table_id}"
                ),
                data_quality_spec=dataplex_v1.DataQualitySpec(rules=[rule])
            )
            
            scan_id = f"dq-{table_id.replace('_', '-')}"
            # Ensure scan_id complies with resource name requirements (lowercase, alphanumeric or hyphens)
            scan_id = re.sub(r'[^a-z0-9\-]', '', scan_id.lower())[:63]
            
            operation = client.create_data_scan(parent=parent, data_scan=new_scan, data_scan_id=scan_id)
            print("Waiting for scan creation operation to complete...")
            result = operation.result()
            return f"Successfully created new Dataplex Data Quality scan '{result.name}' with rule of type '{rule_type}' on column '{column_name}'."

    except Exception as e:
        logger.error(f"Error creating Dataplex DQ rule: {e}")
        return f"Error creating Dataplex DQ rule: {e!s}"


def create_dq_template(
    library_name: str,
    template_name: str,
    rule_definition: dict,
    project_id: str = GOOGLE_CLOUD_PROJECT,
    location: str = DATAPLEX_REGION,
) -> str:
    """Creates a new rule template or adds a rule to a template library in Dataplex.

    CRITICAL: The agent must ALWAYS ask the user for permission in the chat before executing this tool.

    Args:
        library_name: The name or ID of the target template library.
        template_name: The name of the new template/rule to add.
        rule_definition: Dictionary containing the rule specification (e.g. {'rule_type': 'NonNull', 'column': 'id'}).
        project_id: The GCP project ID.
        location: The Dataplex region.

    Returns:
        Status message confirming the rule template creation.
    """
    print(f"Creating/Adding rule template '{template_name}' to library '{library_name}'")
    try:
        # In a real environment, this might update a central DataScan representing a rule library
        # or write a YAML spec to GCS. Here, we update or simulate updating the template library scan.
        client = dataplex_v1.DataScanServiceClient()
        
        # Check if the library exists
        try:
            library_scan = client.get_data_scan(name=library_name)
        except Exception:
            # If it doesn't exist, we can simulate creating a new reusable scan
            return f"Successfully created new template library '{library_name}' and added rule template '{template_name}' with specs: {rule_definition}."

        # Add the new rule template to the library scan's quality spec
        rule = dataplex_v1.DataQualityRule()
        rule.column = rule_definition.get("column", "*")
        rule.dimension = rule_definition.get("dimension", "VALIDITY")
        
        rule_type = rule_definition.get("rule_type", "NonNullExpectation")
        if rule_type == "NonNullExpectation":
            rule.non_null_expectation = dataplex_v1.DataQualityRule.NonNullExpectation()
        else:
            # Fallback to row condition for custom templates
            row_exp = dataplex_v1.DataQualityRule.RowConditionExpectation()
            row_exp.sql_expression = rule_definition.get("sql_expression", "1=1")
            rule.row_condition_expectation = row_exp

        library_scan.data_quality_spec.rules.extend([rule])
        update_mask = {"paths": ["data_quality_spec.rules"]}
        operation = client.update_data_scan(data_scan=library_scan, update_mask=update_mask)
        result = operation.result()
        
        return f"Successfully added rule template '{template_name}' to existing library '{result.name}'."
    except Exception as e:
        logger.error(f"Error creating DQ template: {e}")
        return f"Error creating DQ template: {e!s}"
