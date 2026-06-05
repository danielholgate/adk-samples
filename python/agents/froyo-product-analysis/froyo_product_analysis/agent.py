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

from google.adk.agents import Agent
from froyo_product_analysis.mcp import get_dataplex_mcp_toolset
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

os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"


# ==============================================================================
# AGENT DEFINITION
# ==============================================================================

agent_tools = [
    execute_bigquery_query,
    execute_spark_notebook,
    execute_visualization_code,
]

mcp_toolset = get_dataplex_mcp_toolset()
if mcp_toolset:
    agent_tools.append(mcp_toolset)

root_agent = Agent(
    model=AGENT_MODEL,
    name="froyo_product_analysis_agent",
    description=(
        "Froyo Frozen Yogurt product analytics agent. Accesses BigQuery data, dataplex catalog, "
        "runs Spark jobs on Dataproc, and renders interactive graphs."
    ),
    instruction=FROYO_AGENT_INSTRUCTIONS,
    tools=agent_tools,
)

