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

"""Data Quality Agent definition."""

import logging
import os
import pathlib
import sys
from dotenv import load_dotenv

from google.adk.agents import Agent
from google.genai import types

from data_quality_agent.mcp_config import get_dataplex_mcp_toolset
from data_quality_agent.prompt import DATA_QUALITY_AGENT_INSTRUCTIONS
from data_quality_agent.tools import (
    execute_bigquery_query,
    get_project_data_quality_summary,
    get_data_profiling_metadata,
    get_data_quality_scan_results,
    list_dq_templates,
    create_dataplex_dq_rule,
    create_dq_template,
)

logger = logging.getLogger(__name__)

# Load local environment file if present
load_dotenv()

# ==============================================================================
# CONFIGURATION PARAMETERS
# ==============================================================================

# Gemini model used to power the agent
AGENT_MODEL = os.getenv("AGENT_MODEL", "gemini-2.5-flash")

os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"


# ==============================================================================
# AGENT DEFINITION
# ==============================================================================

agent_tools = [
    execute_bigquery_query,
    get_project_data_quality_summary,
    get_data_profiling_metadata,
    get_data_quality_scan_results,
    list_dq_templates,
    create_dataplex_dq_rule,
    create_dq_template,
]

mcp_toolset = get_dataplex_mcp_toolset()
if mcp_toolset:
    logger.info("Dataplex MCP toolset successfully registered in agent tools.")
    agent_tools.append(mcp_toolset)
else:
    logger.warning("Dataplex MCP toolset is not configured or failed to initialize. Proceeding without MCP tools.")

config = types.GenerateContentConfig(
    temperature=1.0
)

root_agent = Agent(
    model=AGENT_MODEL,
    name="data_quality_agent",
    description=(
        "Data Quality Agent that analyzes data quality issues, inspects data profiling information, "
        "and manages Dataplex data quality rules and templates."
    ),
    generate_content_config=config,
    instruction=DATA_QUALITY_AGENT_INSTRUCTIONS,
    tools=agent_tools,
)
