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

# Cloud Storage bucket for Dataproc inputs, outputs, and scripts.
GCS_BUCKET_FOR_SPARK = os.getenv("GCS_BUCKET_FOR_SPARK", "froyo-analytics-lake")




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
# 2.5. DATAPROC SERVERLESS SPARK BATCH TOOL
# ==============================================================================

# Serverless Session Template required as kernel/session for running Spark Notebooks/Jobs
SERVERLESS_SESSION_TEMPLATE = os.getenv("SERVERLESS_SESSION_TEMPLATE", "iceberg-federation-template")



def submit_spark_batch(
    pyspark_file_uri: str,
    args: list[str] | None = None,
) -> str:
    """Submits a Serverless Spark batch job (PySpark) directly to Dataproc.

    Must be used for all Spark data processing/joins when a notebook is not needed.

    Args:
        pyspark_file_uri: GCS URI (gs://...) of the PySpark script to execute.
        args: Optional list of command-line arguments to pass to the script.

    Returns:
        JSON string detailing the job execution results and status.
    """
    print(f"Submitting PySpark job '{pyspark_file_uri}' using Dataproc Serverless Template '{SERVERLESS_SESSION_TEMPLATE}'")

    try:
        # Create a Batch client for Dataproc Serverless
        client = dataproc.BatchControllerClient(
            client_options={"api_endpoint": f"{DATAPROC_REGION}-dataproc.googleapis.com:443"}
        )

        # Build execution runtime configs referencing the Iceberg federation template
        runtime_config = dataproc.RuntimeConfig(
            version="2.0",
            properties={
                "spark.dataproc.serverless.session.template": SERVERLESS_SESSION_TEMPLATE,
                "spark.sql.catalog.spark_catalog": "org.apache.iceberg.spark.SparkSessionCatalog",
                "spark.sql.catalog.spark_catalog.type": "hive"
            }
        )

        pyspark_batch = dataproc.PySparkBatch(
            main_python_file_uri=pyspark_file_uri,
            args=args
        )

        # Construct service account dynamically based on project
        worker_sa = os.getenv("DATAPROC_WORKER_SA", f"your-dataproc-worker-sa@{GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com")

        environment_config = dataproc.EnvironmentConfig(
            execution_config=dataproc.ExecutionConfig(
                service_account=worker_sa
            )
        )

        batch = dataproc.Batch(
            pyspark_batch=pyspark_batch,
            runtime_config=runtime_config,
            environment_config=environment_config,
            labels={"submitted_by": "froyo_product_analysis_agent", "template": SERVERLESS_SESSION_TEMPLATE}
        )

        batch_id = f"spark-job-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
        parent = f"projects/{GOOGLE_CLOUD_PROJECT}/locations/{DATAPROC_REGION}"

        operation = client.create_batch(
            parent=parent,
            batch=batch,
            batch_id=batch_id
        )

        print(f"Submitted Dataproc Serverless batch '{batch_id}'. Waiting for completion...")
        response = operation.result()

        return json.dumps({
            "status": "SUCCESS",
            "batch_id": batch_id,
            "state": response.state.name,
            "template_used": SERVERLESS_SESSION_TEMPLATE,
            "message": "Spark job executed successfully via Dataproc Serverless."
        }, indent=2)

    except GoogleAPICallError as e:
        logger.error("GCP Dataproc Serverless Batch call failed: %s", e.message, exc_info=True)
        return json.dumps({
            "status": "ERROR",
            "error_message": f"Failed to run Spark job: {e.message}",
            "hint": f"Ensure Serverless template '{SERVERLESS_SESSION_TEMPLATE}' is configured."
        }, indent=2)
    except Exception as e:
        logger.error("Unexpected error during Spark job execution: %s", e, exc_info=True)
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

        if chart_type == "matplotlib":
            return part

        return f"Successfully generated {chart_type} chart. Saved as artifact ID: {artifact_id}"
    except Exception as e:
        logger.error("Failed to run visualization generation: %s", e)
        return f"Error executing visualization script: {e!s}"
