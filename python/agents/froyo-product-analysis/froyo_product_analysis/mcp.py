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

"""MCP Toolset configuration for Froyo Product Analysis Agent via Google Cloud Agent Registry."""

import functools
import inspect
import logging
import os
from google.adk.integrations.agent_registry import AgentRegistry
from google.auth import default

logger = logging.getLogger(__name__)


def get_dataplex_mcp_toolset():
    """
    Connects to the Dataplex MCP server via Google Cloud Agent Registry.
    """
    mcp_server_name = os.environ.get("MCP_SERVER_NAME")
    if not mcp_server_name:
        logger.info(
            "MCP_SERVER_NAME not configured. Skipping MCP toolset registration."
        )
        return None

    try:
        # Use credentials from the environment default auth
        credentials, default_project_id = default()
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", default_project_id)
        location = os.environ.get("MCP_SERVER_LOCATION", "global")

        if not project_id:
            logger.error("Failed to determine Google Cloud Project ID.")
            return None

        registry = AgentRegistry(project_id=project_id, location=location)
        mcp_server_path = f"projects/{project_id}/locations/{location}/mcpServers/{mcp_server_name}"
        logger.info(f"Retrieving MCP Toolset for server: {mcp_server_path}")

        mcp_toolset = registry.get_mcp_toolset(mcp_server_path)

        # Wrap get_tools with logging to indicate connection status
        original_get_tools = mcp_toolset.get_tools

        async def logged_get_tools(*args, **kwargs):
            logger.info(f"Establishing communication with Dataplex MCP server at {mcp_server_path}...")
            try:
                tools = await original_get_tools(*args, **kwargs)
                
                # Filter to only allow read-only lookup/search tools
                allowed_tool_names = {
                    "search_entries",
                    "lookup_entry",
                    "lookup_context",
                    "get_data_product",
                    "get_data_asset",
                    "list_data_products",
                    "list_data_assets",
                }
                tools = [t for t in tools if getattr(t, "name", getattr(t, "__name__", "")) in allowed_tool_names]

                tool_names = [getattr(t, "name", getattr(t, "__name__", str(t))) for t in tools]
                logger.info(
                    f"Successfully established communication with Dataplex MCP server. "
                    f"Registered {len(tools)} tools: {', '.join(tool_names)}"
                )

                # Wrap each tool with logging to track executions and exceptions
                wrapped_tools = []
                for tool in tools:
                    tool_name = getattr(tool, "name", getattr(tool, "__name__", str(tool)))
                    if hasattr(tool, "run_async"):
                        original_run_async = tool.run_async
                        async def logged_run_async(self, *w_args, **w_kwargs):
                            logger.info(f"MCP Tool '{tool_name}' execution started. Inputs: {w_kwargs.get('args') or w_args}")
                            try:
                                result = await original_run_async(*w_args, **w_kwargs)
                                logger.info(f"MCP Tool '{tool_name}' executed successfully.")
                                logger.debug(f"MCP Tool '{tool_name}' return value: {result}")
                                return result
                            except Exception as err:
                                logger.error(f"MCP Tool '{tool_name}' failed during execution: {err}", exc_info=True)
                                raise err
                        import types
                        tool.run_async = types.MethodType(logged_run_async, tool)
                        wrapped_tools.append(tool)
                    elif inspect.iscoroutinefunction(tool):
                        @functools.wraps(tool)
                        async def async_wrapper(*w_args, **w_kwargs):
                            logger.info(f"MCP Tool '{tool_name}' called with args: {w_args}, kwargs: {w_kwargs}")
                            try:
                                result = await tool(*w_args, **w_kwargs)
                                logger.info(f"MCP Tool '{tool_name}' returned successfully.")
                                logger.debug(f"MCP Tool '{tool_name}' return value: {result}")
                                return result
                            except Exception as err:
                                logger.error(f"MCP Tool '{tool_name}' failed with error: {err}", exc_info=True)
                                raise err
                        wrapped_tools.append(async_wrapper)
                    else:
                        @functools.wraps(tool)
                        def sync_wrapper(*w_args, **w_kwargs):
                            logger.info(f"MCP Tool '{tool_name}' called with args: {w_args}, kwargs: {w_kwargs}")
                            try:
                                result = tool(*w_args, **w_kwargs)
                                logger.info(f"MCP Tool '{tool_name}' returned successfully.")
                                logger.debug(f"MCP Tool '{tool_name}' return value: {result}")
                                return result
                            except Exception as err:
                                logger.error(f"MCP Tool '{tool_name}' failed with error: {err}", exc_info=True)
                                raise err
                        wrapped_tools.append(sync_wrapper)
                return wrapped_tools
            except Exception as e:
                logger.error(f"Failed to establish communication with Dataplex MCP server: {e}")
                raise e

        mcp_toolset.get_tools = logged_get_tools
        return mcp_toolset
    except Exception as e:
        logger.error(f"Failed to connect to MCP server or retrieve tools: {e}")
        logger.warning("Continuing without MCP tools.")
        return None
