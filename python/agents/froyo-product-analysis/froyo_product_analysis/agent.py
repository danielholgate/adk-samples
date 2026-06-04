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

"""Froyo Product Analysis Agent definition."""

import os
import pathlib
import sys
from dotenv import load_dotenv

from google.adk.integrations.agent_registry import AgentRegistry
from google.auth import default

from google.adk.agents import Agent
from froyo_product_analysis.prompt import FROYO_AGENT_INSTRUCTIONS
from froyo_product_analysis.tools import (
    execute_bigquery_query,
    execute_spark_notebook,
    execute_visualization_code,
)

# Load local environment file if present
load_dotenv()

# ==============================================================================
# CONFIGURATION PARAMETERS (Configure these variables / environment variables)
# ==============================================================================

# Gemini model used to power the analysis agent
# Typically "gemini-2.5-flash" or "gemini-2.5-pro"
AGENT_MODEL = os.getenv("AGENT_MODEL", "gemini-2.5-flash")

# Dataplex MCP Server Name deployed in Agent Registry (Knowledge Catalog)
MCP_SERVER_NAME = os.getenv("MCP_SERVER_NAME", "agentregistry-00000000-0000-0000-25d9-2dd6732c5390")

# Google Cloud Location where the Agent Registry MCP Server is deployed
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "global")

# Authenticate and obtain active project credentials
_, default_project_id = default()
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

from a2a.types import TransportProtocol as A2ATransport
from google.adk.integrations.agent_registry.agent_registry import AgentRegistrySingleMcpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

# Initialize the Agent Registry client
registry = AgentRegistry(project_id=default_project_id, location=GOOGLE_CLOUD_LOCATION)

# Fetch remote server details from Agent Registry
mcp_server_resource = f"projects/cloud-summit-data-analytics/locations/{GOOGLE_CLOUD_LOCATION}/mcpServers/{MCP_SERVER_NAME}"
server_details = registry.get_mcp_server(mcp_server_resource)

# Extract connection details
endpoint_uri, _, _ = registry._get_connection_uri(
    server_details, protocol_binding=A2ATransport.jsonrpc
)
if not endpoint_uri:
    endpoint_uri, _, _ = registry._get_connection_uri(
        server_details, protocol_binding=A2ATransport.http_json
    )
if not endpoint_uri:
    raise ValueError(f"MCP Server endpoint URI not found for: {mcp_server_resource}")

mcp_server_id = server_details.get("mcpServerId")
clean_prefix = registry._clean_name(server_details.get("displayName", mcp_server_resource))

# Get authentication headers directly on startup
auth_headers = registry._get_auth_headers()

# Inject authorization headers directly into the connection parameters
connection_params = StreamableHTTPConnectionParams(
    url=endpoint_uri,
    headers=auth_headers
)

# Instantiate the Toolset with static headers
dataplex_mcp_toolset = AgentRegistrySingleMcpToolset(
    destination_resource_id=mcp_server_id,
    connection_params=connection_params,
    tool_name_prefix=clean_prefix
)


# ==============================================================================
# AGENT DEFINITION
# ==============================================================================

root_agent = Agent(
    model=AGENT_MODEL,
    name="froyo_product_analysis_agent",
    description=(
        "Froyo Frozen Yogurt product analytics agent. Accesses BigQuery catalog data, "
        "inspects data relationships in Dataplex, runs Spark jobs on Dataproc, and renders interactive graphs."
    ),
    instruction=FROYO_AGENT_INSTRUCTIONS,
    tools=[
        execute_bigquery_query,
        execute_spark_notebook,
        execute_visualization_code,
        dataplex_mcp_toolset,
    ],
)
