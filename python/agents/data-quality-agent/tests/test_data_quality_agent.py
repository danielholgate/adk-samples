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

"""Unit tests for the Data Quality Agent and its tools."""

import json
import unittest
import unittest.mock

from google.cloud import dataplex_v1

from data_quality_agent.agent import root_agent
from data_quality_agent.tools import (
    execute_bigquery_query,
    get_project_data_quality_summary,
    get_data_profiling_metadata,
    get_data_quality_scan_results,
    list_dq_templates,
    create_dataplex_dq_rule,
    create_dq_template,
)


class TestDataQualityAgent(unittest.TestCase):
    """Test cases for checking Data Quality Agent configuration and tool operations."""

    def test_agent_configuration(self):
        """Verifies the agent is correctly named and has all tools registered."""
        self.assertEqual(root_agent.name, "data_quality_agent")
        self.assertIsNotNone(root_agent.instruction)

        # Check registered tool names/types
        registered_tools = [tool.__name__ for tool in root_agent.tools if hasattr(tool, "__name__")]
        self.assertIn("execute_bigquery_query", registered_tools)
        self.assertIn("get_project_data_quality_summary", registered_tools)
        self.assertIn("get_data_profiling_metadata", registered_tools)
        self.assertIn("get_data_quality_scan_results", registered_tools)
        self.assertIn("list_dq_templates", registered_tools)
        self.assertIn("create_dataplex_dq_rule", registered_tools)
        self.assertIn("create_dq_template", registered_tools)

    @unittest.mock.patch("data_quality_agent.tools.bigquery.Client")
    def test_bigquery_query(self, mock_client_cls):
        """Verifies the BigQuery tool queries GCP and returns JSON records."""
        mock_client = mock_client_cls.return_value
        mock_query_job = unittest.mock.Mock()
        mock_client.query.return_value = mock_query_job
        
        mock_row = {"column_name": "customer_id", "null_count": 0}
        mock_query_job.result.return_value = [mock_row]

        query = "SELECT 'customer_id' as column_name, COUNT(1) - COUNT(customer_id) as null_count FROM `project.dataset.customers`"
        result_str = execute_bigquery_query(query)

        self.assertIsNotNone(result_str)
        self.assertNotIn("Error", result_str)

        result_data = json.loads(result_str)
        self.assertIsInstance(result_data, list)
        self.assertEqual(len(result_data), 1)
        self.assertEqual(result_data[0]["column_name"], "customer_id")
        mock_client.query.assert_called_once()

    @unittest.mock.patch("data_quality_agent.tools.dataplex_v1.DataScanServiceClient")
    def test_get_project_data_quality_summary(self, mock_client_cls):
        """Verifies retrieving project-wide data quality summary."""
        mock_client = mock_client_cls.return_value
        
        mock_scan1 = unittest.mock.Mock()
        mock_scan1.name = "projects/test-project/locations/us-central1/dataScans/dq-orders"
        mock_scan1.description = "DQ scan for orders"
        mock_scan1.data.resource = "//bigquery.googleapis.com/projects/test-project/datasets/sales/tables/orders"
        mock_scan1.data_quality_spec = unittest.mock.Mock()
        mock_scan1.data_profile_spec = None
        mock_scan1.state.name = "ACTIVE"
        
        mock_qr = unittest.mock.Mock()
        mock_qr.passed = True
        mock_qr.score = 98.5
        mock_qr.dimensions = []
        mock_scan1.data_quality_result = mock_qr

        mock_scan2 = unittest.mock.Mock()
        mock_scan2.name = "projects/test-project/locations/us-central1/dataScans/prof-customers"
        mock_scan2.description = "Profiling scan for customers"
        mock_scan2.data.resource = "//bigquery.googleapis.com/projects/test-project/datasets/crm/tables/customers"
        mock_scan2.data_quality_spec = None
        mock_scan2.data_profile_spec = unittest.mock.Mock()
        mock_scan2.state.name = "ACTIVE"
        
        mock_pr = unittest.mock.Mock()
        mock_pr.profile.result.row_count = 5000
        mock_scan2.data_profile_result = mock_pr
        
        mock_client.list_data_scans.return_value = [mock_scan1, mock_scan2]

        result_str = get_project_data_quality_summary("test-project", "us-central1")
        self.assertIsNotNone(result_str)
        
        result_data = json.loads(result_str)
        self.assertEqual(len(result_data), 2)
        self.assertEqual(result_data[0]["target_table"], "test-project.sales.orders")
        self.assertEqual(result_data[0]["scan_type"], "QUALITY")
        self.assertEqual(result_data[0]["latest_result"]["passed"], True)
        self.assertEqual(result_data[0]["latest_result"]["score"], 98.5)
        
        self.assertEqual(result_data[1]["target_table"], "test-project.crm.customers")
        self.assertEqual(result_data[1]["scan_type"], "PROFILE")
        self.assertEqual(result_data[1]["latest_result"]["row_count"], 5000)

    @unittest.mock.patch("data_quality_agent.tools.dataplex_v1.DataScanServiceClient")
    def test_get_data_profiling_metadata(self, mock_client_cls):
        """Verifies retrieving data profiling info from Dataplex."""
        mock_client = mock_client_cls.return_value
        
        mock_scan = unittest.mock.Mock()
        mock_scan.name = "projects/test-project/locations/us-central1/dataScans/test-scan"
        mock_scan.description = "Test profiling scan"
        mock_scan.data.resource = "//bigquery.googleapis.com/projects/test-project/datasets/test-dataset/tables/test-table"
        mock_scan.data_profile_spec = unittest.mock.Mock()
        mock_scan.state.name = "ACTIVE"
        mock_scan.create_time = None
        mock_scan.type_ = dataplex_v1.DataScanType.DATA_PROFILE
        
        mock_data_profile_result = unittest.mock.Mock()
        mock_field = unittest.mock.Mock()
        mock_field.name = "id"
        mock_field.type_ = "INTEGER"
        mock_field.mode = "REQUIRED"
        mock_field.profile.null_ratio = 0.0
        mock_field.profile.distinct_ratio = 1.0
        mock_field.profile.min = "1"
        mock_field.profile.max = "100"
        
        mock_data_profile_result.profile.fields = [mock_field]
        mock_data_profile_result.profile.result.row_count = 100
        mock_scan.data_profile_result = mock_data_profile_result
        
        mock_client.list_data_scans.return_value = [mock_scan]
        mock_client.get_data_scan.return_value = mock_scan

        result_str = get_data_profiling_metadata("test-table", "test-project", "us-central1")
        self.assertIsNotNone(result_str)
        
        result_data = json.loads(result_str)
        self.assertEqual(result_data["state"], "ACTIVE")
        self.assertEqual(result_data["latest_result"]["row_count"], 100)
        self.assertEqual(len(result_data["latest_result"]["fields"]), 1)
        self.assertEqual(result_data["latest_result"]["fields"][0]["name"], "id")

    @unittest.mock.patch("data_quality_agent.tools.dataplex_v1.DataScanServiceClient")
    def test_get_data_quality_scan_results(self, mock_client_cls):
        """Verifies retrieving data quality scan results from Dataplex."""
        mock_client = mock_client_cls.return_value
        
        mock_scan = unittest.mock.Mock()
        mock_scan.name = "projects/test-project/locations/us-central1/dataScans/test-dq"
        mock_scan.description = "Test DQ scan"
        mock_scan.data.resource = "//bigquery.googleapis.com/projects/test-project/datasets/test-dataset/tables/test-table"
        mock_scan.data_quality_spec.rules = []
        mock_scan.state.name = "ACTIVE"
        mock_scan.type_ = dataplex_v1.DataScanType.DATA_QUALITY
        
        mock_data_quality_result = unittest.mock.Mock()
        mock_data_quality_result.passed = True
        mock_data_quality_result.score = 100.0
        mock_data_quality_result.dimensions = []
        mock_data_quality_result.rules = []
        
        mock_scan.data_quality_result = mock_data_quality_result
        mock_client.list_data_scans.return_value = [mock_scan]
        mock_client.get_data_scan.return_value = mock_scan

        result_str = get_data_quality_scan_results("test-table", "test-project", "us-central1")
        self.assertIsNotNone(result_str)
        
        result_data = json.loads(result_str)
        self.assertEqual(result_data["latest_result"]["passed"], True)
        self.assertEqual(result_data["latest_result"]["score"], 100.0)

    @unittest.mock.patch("data_quality_agent.tools.dataplex_v1.CatalogServiceClient")
    @unittest.mock.patch("data_quality_agent.tools.dataplex_v1.DataScanServiceClient")
    def test_get_data_quality_scan_results_fallback(self, mock_scan_client_cls, mock_catalog_client_cls):
        """Verifies fallback to Catalog scorecard aspect if scan result is not found in DataScan."""
        mock_scan_client = mock_scan_client_cls.return_value
        mock_catalog_client = mock_catalog_client_cls.return_value
        
        # No scan is found targeting the table
        mock_scan_client.list_data_scans.return_value = []
        
        # Mock Catalog Entry Search
        mock_search_result = unittest.mock.Mock()
        mock_search_result.dataplex_entry.name = "projects/test-project/locations/us-central1/entryGroups/@bigquery/entries/test-entry"
        mock_search_result.dataplex_entry.fully_qualified_name = "bigquery:test-project.test-dataset.test-table"
        mock_catalog_client.search_entries.return_value = [mock_search_result]
        
        # Mock Catalog Get Entry
        mock_entry = unittest.mock.Mock()
        mock_entry.name = "projects/test-project/locations/us-central1/entryGroups/@bigquery/entries/test-entry"
        
        mock_aspect = unittest.mock.Mock()
        mock_aspect.aspect_type = "projects/655216118709/locations/global/aspectTypes/data-quality-scorecard"
        mock_aspect.data = {
            "score": 95,
            "status": "PASS",
            "dimensions": [
                {"name": "COMPLETENESS", "status": "PASS", "score": 95}
            ]
        }
        
        mock_entry.aspects = {"655216118709.global.data-quality-scorecard": mock_aspect}
        mock_catalog_client.get_entry.return_value = mock_entry
        
        result_str = get_data_quality_scan_results("test-table", "test-project", "us-central1")
        self.assertIsNotNone(result_str)
        
        result_data = json.loads(result_str)
        self.assertEqual(result_data["latest_result"]["score"], 95)
        self.assertEqual(result_data["latest_result"]["passed"], True)
        self.assertEqual(len(result_data["latest_result"]["dimensions"]), 1)
        self.assertEqual(result_data["latest_result"]["dimensions"][0]["dimension"], "COMPLETENESS")

    @unittest.mock.patch("data_quality_agent.tools.dataplex_v1.DataScanServiceClient")
    def test_list_dq_templates(self, mock_client_cls):
        """Verifies standard template libraries are listed."""
        mock_client = mock_client_cls.return_value
        mock_client.list_data_scans.return_value = []

        result_str = list_dq_templates("test-project", "us-central1")
        self.assertIsNotNone(result_str)
        
        result_data = json.loads(result_str)
        self.assertTrue(len(result_data) > 0)
        self.assertIn("library", result_data[0]["name"])

    @unittest.mock.patch("data_quality_agent.tools.dataplex_v1.DataScanServiceClient")
    def test_create_dataplex_dq_rule(self, mock_client_cls):
        """Verifies creating a data quality rule targets Dataplex API."""
        mock_client = mock_client_cls.return_value
        mock_operation = unittest.mock.Mock()
        mock_client.create_data_scan.return_value = mock_operation
        mock_client.list_data_scans.return_value = []
        
        mock_scan_res = unittest.mock.Mock()
        mock_scan_res.name = "projects/test-project/locations/us-central1/dataScans/dq-test-table"
        mock_operation.result.return_value = mock_scan_res

        result_str = create_dataplex_dq_rule(
            table_name="project.dataset.test_table",
            rule_type="NonNullExpectation",
            column_name="email",
            project_id="test-project",
            location="us-central1"
        )
        
        self.assertIsNotNone(result_str)
        self.assertIn("Successfully created new Dataplex Data Quality scan", result_str)
        mock_client.create_data_scan.assert_called_once()


if __name__ == "__main__":
    unittest.main()
