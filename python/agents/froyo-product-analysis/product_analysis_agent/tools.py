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

"""Tools for the Froyo Product Analysis Agent."""

import datetime
import io
import json
import logging
import os
import re
from typing import Any

from dotenv import load_dotenv
import matplotlib.pyplot as plt
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from google.adk.agents.context import Context as ToolContext
from google.api_core.exceptions import GoogleAPICallError
from google.cloud import bigquery
from google.cloud import dataproc_v1 as dataproc
from google.cloud import storage
from google.genai import types

logger = logging.getLogger(__name__)

# Load local environment file if present
load_dotenv()

# ==============================================================================
# CONFIGURATION PARAMETERS (Configure these variables / environment variables)
# ==============================================================================

# Google Cloud Project ID for running BigQuery and Dataproc.
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "cloud-summit-data-analytics")

# Dataproc settings for running Spark analytics jobs.
DATAPROC_REGION = os.getenv("DATAPROC_REGION", "us-central1")
DATAPROC_CLUSTER_NAME = os.getenv("DATAPROC_CLUSTER_NAME", "summit-spark-cluster")

# Cloud Storage bucket for Dataproc inputs, outputs, and scripts.
GCS_BUCKET_FOR_SPARK = os.getenv("GCS_BUCKET_FOR_SPARK_UPLOAD", "froyo-analytics-lake")




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


def execute_bigquery_query(sql: str) -> str:
    """Executes a BigQuery SQL query to retrieve Froyo dataset records.

    Args:
        sql: The SQL query statement to run.

    Returns:
        JSON string representing the query results.
    """
    cleaned_sql = clean_sql_query(sql)
    print(f"Executing BigQuery query: {cleaned_sql}")

    # Real GCP execution
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
# ==============================================================================
# 2.5. DATAPROC SPARK JOB TOOL
# ==============================================================================


def submit_spark_batch(
    pyspark_file_uri: str,
    args: list[str] | None = None,
) -> str:
    """Submits a Spark job (PySpark) directly to a Dataproc Cluster.

    Must be used for all Spark data processing/joins when a notebook is not needed.

    Args:
        pyspark_file_uri: GCS URI (gs://...) of the PySpark script to execute.
        args: Optional list of command-line arguments to pass to the script.

    Returns:
        JSON string detailing the job execution results and status.
    """
    print(f"Submitting PySpark job '{pyspark_file_uri}' to Dataproc Cluster '{DATAPROC_CLUSTER_NAME}' in region '{DATAPROC_REGION}'")

    try:
        # Create a Job client for Dataproc Cluster
        client = dataproc.JobControllerClient(
            client_options={"api_endpoint": f"{DATAPROC_REGION}-dataproc.googleapis.com:443"}
        )

        # Build execution properties for PySpark job
        properties = {
            "spark.jars.packages": "org.apache.iceberg:iceberg-spark-runtime-3.4_2.12:1.1.0",
            "spark.sql.extensions": "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
            "spark.sql.catalog.cloud_summit_2026_lakehouse": "org.apache.iceberg.spark.SparkSessionCatalog",
            "spark.sql.catalog.cloud_summit_2026_lakehouse.catalog-impl": "org.apache.iceberg.rest.RESTCatalog",
            "spark.sql.catalog.cloud_summit_2026_lakehouse.uri": f"https://{DATAPROC_REGION}-dataplex.cloud.google.com/v1/projects/{GOOGLE_CLOUD_PROJECT}/locations/{DATAPROC_REGION}/lakes/acai-lake/zones/acai-lakehouse-zone/assets/orders/catalogs/iceberg",
            "spark.sql.catalog.cloud_summit_2026_lakehouse.warehouse": "gs://cloud-summit-2026-lakehouse",
            "spark.sql.catalog.spark_catalog": "org.apache.iceberg.spark.SparkSessionCatalog",
            "spark.sql.catalog.spark_catalog.type": "hive"
        }

        job = {
            "placement": {"cluster_name": DATAPROC_CLUSTER_NAME},
            "pyspark_job": {
                "main_python_file_uri": pyspark_file_uri,
                "args": args or [],
                "properties": properties
            },
            "labels": {"submitted_by": "froyo_product_analysis_agent"}
        }

        operation = client.submit_job_as_operation(
            request={"project_id": GOOGLE_CLOUD_PROJECT, "region": DATAPROC_REGION, "job": job}
        )

        print(f"Submitted Dataproc job. Waiting for completion...")
        response = operation.result()

        return json.dumps({
            "status": "SUCCESS",
            "job_id": response.reference.job_id,
            "state": response.status.state.name,
            "cluster_name": DATAPROC_CLUSTER_NAME,
            "message": "Spark job executed successfully via Dataproc Cluster."
        }, indent=2)

    except GoogleAPICallError as e:
        logger.error("GCP Dataproc Job call failed: %s", e.message, exc_info=True)
        return json.dumps({
            "status": "ERROR",
            "error_message": f"Failed to run Spark job on cluster: {e.message}",
            "hint": f"Ensure Dataproc Cluster '{DATAPROC_CLUSTER_NAME}' is running in region '{DATAPROC_REGION}'."
        }, indent=2)
    except Exception as e:
        logger.error("Unexpected error during Spark job execution on cluster: %s", e, exc_info=True)
        return json.dumps({
            "status": "ERROR",
            "error_message": f"Unexpected error: {e!s}"
        }, indent=2)





# ==============================================================================
# 3. INTERACTIVE VISUALIZATION / CHART GENERATOR TOOL
# ==============================================================================


async def execute_visualization_code(
    code: str,
    tool_context: ToolContext,
    chart_type: str = "plotly",
    filename: str = "froyo_chart.html",
) -> Any:
    """Executes Python code containing a Plotly/Matplotlib definition and saves the result as an ADK artifact.

    The code MUST assign the resulting chart object to a variable named 'fig'.
    Imports available: 'pd', 'px', 'go', 'plt'.

    Args:
        code: The Python script execution code.
        tool_context: Context containing artifact saving operations.
        chart_type: The visualization library: 'plotly' or 'matplotlib'.
        filename: Target name for the chart file.

    Returns:
        The generated chart Part object (if matplotlib) or a status message containing the registered artifact ID.
    """
    try:
        local_vars: dict[str, Any] = {
            "pd": pd,
            "px": px,
            "go": go,
            "plt": plt,
            "fig": None,
        }

        # Safe execution of generated plot plotting logic
        exec(code, {}, local_vars)
        fig = local_vars.get("fig")

        if fig is None:
            return "Error: Visualization code did not set a chart object to the variable 'fig'."

        if chart_type == "plotly":
            chart_html = fig.to_html(include_plotlyjs="cdn", full_html=False)
            artifact_data = chart_html.encode("utf-8")
            mime_type = "text/html"
        else:
            buf = io.BytesIO()
            plt.savefig(buf, format="png")
            plt.close(fig)
            artifact_data = buf.getvalue()
            mime_type = "image/png"

        # Write to local file directory for dev UI usage
        output_dir = "/tmp/output"
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "wb") as f:
            f.write(artifact_data)

        # Save to ADK Artifact Service
        artifact_id = filename.replace(".", "_")
        part = types.Part.from_bytes(data=artifact_data, mime_type=mime_type)
        await tool_context.save_artifact(
            artifact_id,
            part,
        )

        if chart_type == "plotly":
            # For Plotly, generate a static PNG representation and return it so it renders inline in the chat
            img_bytes = fig.to_image(format="png")
            img_part = types.Part.from_bytes(data=img_bytes, mime_type="image/png")
            return img_part

        return part
    except Exception as e:
        logger.error("Failed to run visualization generation: %s", e)
        return f"Error executing visualization script: {e!s}"


def upload_file_to_gcs(
    content: str,
    destination_blob_name: str,
    bucket_name: str = GCS_BUCKET_FOR_SPARK,
) -> str:
    """Uploads a string file content to a Google Cloud Storage bucket path.

    This tool is used to write PySpark scripts or other code resources to Cloud Storage
    prior to running Spark jobs.

    Args:
        content: Required. The string content (e.g. PySpark Python code) to write to the file.
        destination_blob_name: Required. The GCS path (blob name) where the file should be saved (e.g. 'scripts/my_job.py').
        bucket_name: The GCS bucket name. Defaults to the configured Spark bucket.

    Returns:
        The full GCS URI of the uploaded file (e.g. 'gs://bucket-name/scripts/my_job.py') or an error message.
    """
    try:
        storage_client = storage.Client(project=GOOGLE_CLOUD_PROJECT)
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_string(content, content_type="text/x-python")
        
        gcs_uri = f"gs://{bucket_name}/{destination_blob_name}"
        print(f"Successfully uploaded file to GCS: {gcs_uri}")
        return gcs_uri
    except Exception as e:
        logger.error(f"Failed to upload file to GCS: {e}")
        return f"Error uploading file to GCS: {e}"
