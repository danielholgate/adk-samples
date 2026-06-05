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
    execute_spark_notebook,
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
        self.assertIn("execute_spark_notebook", registered_tools)
        self.assertIn("execute_visualization_code", registered_tools)

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

    @unittest.mock.patch("froyo_product_analysis.tools.dataproc.BatchControllerClient")
    def test_dataproc_serverless_notebook(self, mock_batch_client_cls):
        """Verifies Dataproc Serverless notebook runs successfully using Iceberg Federation template."""
        mock_client = mock_batch_client_cls.return_value
        mock_operation = unittest.mock.Mock()
        mock_client.create_batch.return_value = mock_operation
        
        mock_response = unittest.mock.Mock()
        mock_response.state.name = "SUCCEEDED"
        mock_operation.result.return_value = mock_response

        notebook_uri = "gs://froyo-analytics-lake/notebooks/pdf_customer_join.ipynb"
        result_str = execute_spark_notebook(
            notebook_uri=notebook_uri,
            parameters={"target_dataset": "cloud_summits_pdfs"}
        )

        self.assertIsNotNone(result_str)
        result_data = json.loads(result_str)

        self.assertEqual(result_data["status"], "SUCCESS")
        self.assertEqual(result_data["state"], "SUCCEEDED")
        self.assertEqual(result_data["template_used"], "iceberg-federation-template")
        mock_client.create_batch.assert_called_once()

    @unittest.mock.patch("google.adk.tools.mcp_tool.mcp_toolset.McpToolset")
    def test_get_dataplex_mcp_toolset(self, mock_mcp_toolset_cls):
        """Verifies get_dataplex_mcp_toolset configures the local mcp server and returns toolset."""
        mock_toolset = unittest.mock.Mock()
        mock_mcp_toolset_cls.return_value = mock_toolset

        from froyo_product_analysis.mcp import get_dataplex_mcp_toolset
        toolset = get_dataplex_mcp_toolset()

        self.assertEqual(toolset, mock_toolset)
        mock_mcp_toolset_cls.assert_called_once()



