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

"""Local Stdio MCP server for Google Cloud Dataplex Universal Catalog."""

import os
import json
import logging
from mcp.server.fastmcp import FastMCP
from google.cloud import dataplex_v1

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("local_mcp_server")

mcp = FastMCP("Local Dataplex Catalog Server")
client = dataplex_v1.CatalogServiceClient()

@mcp.tool()
def search_entries(query: str, project_id: str = "cloud-summit-data-analytics", location: str = "global") -> str:
    """Searches for entries matching a query within the Dataplex Universal Catalog.

    Args:
        query: Required. The query string to search for.
        project_id: The project ID to which the request should be attributed.
        location: The location to which the request should be attributed.
    """
    try:
        parent = f"projects/{project_id}/locations/{location}"
        logger.info(f"Searching entries under {parent} with query: {query}")
        response = client.search_entries(name=parent, query=query)
        results = []
        for result in response:
            results.append(type(result).to_dict(result))
        return json.dumps(results, indent=2, default=str)
    except Exception as e:
        logger.error(f"Error in search_entries: {e}")
        return f"Error: {e}"

@mcp.tool()
def lookup_entry(entry: str, project_id: str = "cloud-summit-data-analytics", location: str = "global") -> str:
    """Looks up an entry by either resource name or fully qualified name in the Dataplex Universal Catalog.

    Args:
        entry: Required. The resource name of the Entry to lookup.
        project_id: The project ID to which the request should be attributed.
        location: The location to which the request should be attributed.
    """
    try:
        parent = f"projects/{project_id}/locations/{location}"
        logger.info(f"Looking up entry {entry} under {parent}")
        response = client.lookup_entry(name=parent, entry=entry)
        return type(response).to_json(response)
    except Exception as e:
        logger.error(f"Error in lookup_entry: {e}")
        return f"Error: {e}"

@mcp.tool()
def lookup_context(entry: str, project_id: str = "cloud-summit-data-analytics", location: str = "global") -> str:
    """Looks up the context (lineage and glossary) of a data asset or entry in the Dataplex Universal Catalog.

    Args:
        entry: Required. The resource name of the entry itself to lookup context for.
        project_id: The project ID to which the request should be attributed.
        location: The location to which the request should be attributed.
    """
    try:
        parent = f"projects/{project_id}/locations/{location}"
        logger.info(f"Looking up context for entry {entry} under {parent}")
        response = client.lookup_context(name=parent, resources=[entry])
        return type(response).to_json(response)
    except Exception as e:
        logger.error(f"Error in lookup_context: {e}")
        return f"Error: {e}"

if __name__ == "__main__":
    mcp.run()
