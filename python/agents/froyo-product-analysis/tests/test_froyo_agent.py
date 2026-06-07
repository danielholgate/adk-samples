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

"""Unit tests for the Froyo Product Analysis Agent and its tools."""

import json
import unittest
import unittest.mock

from froyo_product_analysis.agent import root_agent
from froyo_product_analysis.tools import (
    execute_bigquery_query,
    submit_spark_batch,
)


class TestFroyoAgent(unittest.TestCase):
    """Test cases for checking Froyo Agent configuration and tool operations."""

    def test_agent_configuration(self):
        """Verifies the agent is correctly named and has all tools registered."""
        self.assertEqual(root_agent.name, "froyo_product_analysis_agent")
        self.assertIsNotNone(root_agent.instruction)

        # Check registered tool names/types
        registered_tools = [tool.__name__ for tool in root_agent.tools if hasattr(tool, "__name__")]
        self.assertIn("execute_bigquery_query", registered_tools)
        self.assertIn("submit_spark_batch", registered_tools)
        self.assertIn("execute_visualization_code", registered_tools)
        self.assertIn("upload_file_to_gcs", registered_tools)

    @unittest.mock.patch("froyo_product_analysis.tools.bigquery.Client")
    def test_bigquery_query(self, mock_client_cls):
        """Verifies the BigQuery tool queries GCP and returns JSON records."""
        mock_client = mock_client_cls.return_value
        mock_query_job = unittest.mock.Mock()
        mock_client.query.return_value = mock_query_job
        
        mock_row = {"product_id": "P001", "product_name": "Original Tart", "price": 4.5}
        mock_query_job.result.return_value = [mock_row]

        query = "SELECT * FROM `froyo-analytics-prod.products.product_dim`"
        result_str = execute_bigquery_query(query)

        self.assertIsNotNone(result_str)
        self.assertNotIn("Error", result_str)

        result_data = json.loads(result_str)
        self.assertIsInstance(result_data, list)
        self.assertEqual(len(result_data), 1)
        self.assertEqual(result_data[0]["product_id"], "P001")
        mock_client.query.assert_called_once()

    @unittest.mock.patch("froyo_product_analysis.tools.dataproc.JobControllerClient")
    def test_dataproc_cluster_job(self, mock_job_client_cls):
        """Verifies Dataproc Spark job runs successfully on a cluster."""
        mock_client = mock_job_client_cls.return_value
        mock_operation = unittest.mock.Mock()
        mock_client.submit_job_as_operation.return_value = mock_operation
        
        mock_response = unittest.mock.Mock()
        mock_response.reference.job_id = "test-job-123"
        mock_response.status.state.name = "DONE"
        mock_operation.result.return_value = mock_response

        pyspark_file_uri = "gs://froyo-analytics-lake/scripts/pdf_customer_join.py"
        result_str = submit_spark_batch(
            pyspark_file_uri=pyspark_file_uri,
            args=["--target-dataset", "cloud_summits_pdfs"]
        )

        self.assertIsNotNone(result_str)
        result_data = json.loads(result_str)

        self.assertEqual(result_data["status"], "SUCCESS")
        self.assertEqual(result_data["state"], "DONE")
        self.assertEqual(result_data["job_id"], "test-job-123")
        self.assertEqual(result_data["cluster_name"], "summit-spark-cluster")
        mock_client.submit_job_as_operation.assert_called_once()


    @unittest.mock.patch("google.adk.tools.mcp_tool.mcp_toolset.McpToolset")
    def test_get_dataplex_mcp_toolset(self, mock_mcp_toolset_cls):
        """Verifies get_dataplex_mcp_toolset configures the local mcp server and returns toolset."""
        mock_toolset = unittest.mock.Mock()
        mock_mcp_toolset_cls.return_value = mock_toolset

        from froyo_product_analysis.mcp import get_dataplex_mcp_toolset
        toolset = get_dataplex_mcp_toolset()

        self.assertEqual(toolset, mock_toolset)
        mock_mcp_toolset_cls.assert_called_once()

    @unittest.mock.patch("froyo_product_analysis.tools.storage.Client")
    def test_upload_file_to_gcs(self, mock_storage_client_cls):
        """Verifies upload_file_to_gcs uploads python code correctly."""
        mock_client = mock_storage_client_cls.return_value
        mock_bucket = unittest.mock.Mock()
        mock_client.bucket.return_value = mock_bucket
        mock_blob = unittest.mock.Mock()
        mock_bucket.blob.return_value = mock_blob

        from froyo_product_analysis.tools import upload_file_to_gcs
        
        content = "print('hello')"
        destination = "scripts/hello.py"
        bucket = "my-test-bucket"

        result = upload_file_to_gcs(content, destination, bucket)

        self.assertEqual(result, f"gs://{bucket}/{destination}")
        mock_client.bucket.assert_called_once_with(bucket)
        mock_bucket.blob.assert_called_once_with(destination)
        mock_blob.upload_from_string.assert_called_once_with(content, content_type="text/x-python")

    @unittest.mock.patch("froyo_product_analysis.tools.plt")
    def test_execute_visualization_matplotlib(self, mock_plt):
        """Verifies execute_visualization_code generates and returns a Matplotlib chart Part."""
        import asyncio
        mock_fig = unittest.mock.Mock()
        mock_plt.figure.return_value = mock_fig
        
        mock_context = unittest.mock.AsyncMock()
        
        from froyo_product_analysis.tools import execute_visualization_code
        
        code = "import matplotlib.pyplot as plt\nfig = plt.figure()"
        result = asyncio.run(execute_visualization_code(
            code=code,
            tool_context=mock_context,
            chart_type="matplotlib",
            filename="chart.png"
        ))
        
        self.assertIsNotNone(result)
        self.assertEqual(result.inline_data.mime_type, "image/png")
        mock_context.save_artifact.assert_called_once()

    def test_execute_visualization_plotly(self):
        """Verifies execute_visualization_code generates and returns a Plotly chart Part."""
        import asyncio
        mock_context = unittest.mock.AsyncMock()
        
        from froyo_product_analysis.tools import execute_visualization_code
        
        code = "import plotly.express as px\nfig = px.scatter(x=[1, 2], y=[3, 4])"
        result = asyncio.run(execute_visualization_code(
            code=code,
            tool_context=mock_context,
            chart_type="plotly",
            filename="chart.html"
        ))
        
        self.assertIsNotNone(result)
        self.assertEqual(result.inline_data.mime_type, "image/png")
        mock_context.save_artifact.assert_called_once()



