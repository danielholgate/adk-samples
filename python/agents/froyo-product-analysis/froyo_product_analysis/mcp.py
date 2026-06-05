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

"""Local MCP Toolset configuration for Froyo Product Analysis Agent."""

import functools
import inspect
import logging
import os
import sys

logger = logging.getLogger(__name__)


def get_dataplex_mcp_toolset():
    """
    Connects to the local Dataplex MCP server via Stdio.
    """
    try:
        from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
        from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
        from mcp import StdioServerParameters

        import pathlib
        import site
        package_parent_dir = str(pathlib.Path(__file__).parent.parent.resolve())

        site_paths = []
        try:
            site_paths.extend(site.getsitepackages())
        except AttributeError:
            pass
        try:
            user_site = site.getusersitepackages()
            if user_site:
                site_paths.append(user_site)
        except AttributeError:
            pass

        all_paths = [package_parent_dir] + site_paths

        env = dict(os.environ)
        existing_pythonpath = env.get("PYTHONPATH", "")
        if existing_pythonpath:
            all_paths.append(existing_pythonpath)

        env["PYTHONPATH"] = os.pathsep.join(all_paths)

        connection_params = StdioConnectionParams(
            server_params=StdioServerParameters(
                command=sys.executable,
                args=["-m", "froyo_product_analysis.local_mcp_server"],
                env=env,
            ),
            timeout=20.0,
        )

        logger.info("Connecting to local Dataplex MCP server...")
        mcp_toolset = McpToolset(connection_params=connection_params)

        # Wrap get_tools with logging to indicate connection status
        original_get_tools = mcp_toolset.get_tools

        async def logged_get_tools(*args, **kwargs):
            logger.info("Establishing communication with local Dataplex MCP server...")
            try:
                tools = await original_get_tools(*args, **kwargs)
                
                # Filter to only allow read-only lookup/search tools
                allowed_tool_names = {
                    "search_entries",
                    "lookup_entry",
                    "lookup_context"
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
                logger.error(f"Failed to establish communication with Dataplex MCP server: {e}", exc_info=True)
                raise e

        mcp_toolset.get_tools = logged_get_tools
        return mcp_toolset
    except Exception as e:
        logger.error(f"Failed to connect to MCP server or retrieve tools: {e}", exc_info=True)
        logger.warning("Continuing without MCP tools.")
        return None
