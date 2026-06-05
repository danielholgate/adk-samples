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

"""A local script to run the Froyo Product Analysis Agent interactively."""

import asyncio
import json
import os
import sys

# Ensure the agent package is importable
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from froyo_product_analysis.agent import root_agent
from froyo_product_analysis.plugins import reflect_retry_plugin


async def async_main():
    print("Initializing Froyo Product Analysis Agent in local interactive shell...")
    print("----------------------------------------------------------------------")
    print(f"Simulation Mode: {os.getenv('USE_SIMULATION_MODE', 'True')}")
    print("----------------------------------------------------------------------")

    session_service = InMemorySessionService()
    artifacts_service = InMemoryArtifactService()

    # Create a user session
    session = await session_service.create_session(
        state={},
        app_name="froyo-product-analysis",
        user_id="analyst_user"
    )

    runner = Runner(
        app_name="froyo-product-analysis",
        agent=root_agent,
        artifact_service=artifacts_service,
        session_service=session_service,
        plugins=[reflect_retry_plugin],
    )

    print("\nAsk Froyo Product Analysis Agent a question! (e.g. 'What is the relationship between the sales data and the ingredients catalog?')")
    print("Type 'exit' or 'quit' to end.\n")

    try:
        while True:
            try:
                user_query = input("You: ").strip()
            except (KeyboardInterrupt, EOFError):
                break

            if not user_query:
                continue
            if user_query.lower() in ("exit", "quit"):
                break

            print("\nProcessing request...")
            new_message = types.Content(role="user", parts=[types.Part(text=user_query)])

            try:
                events_stream = runner.run_async(
                    session_id=session.id,
                    user_id="analyst_user",
                    new_message=new_message,
                )

                async for event in events_stream:
                    if not event.content:
                        continue

                    author = event.author
                    parts = event.content.parts

                    for part in parts:
                        # 1. Text Responses from Agent
                        if part.text:
                            print(f"\n[{author}]: {part.text}")

                        # 2. Tool / Function Calls
                        elif part.function_call:
                            call = part.function_call
                            print(f"\n[{author} Calling Tool]: {call.name}( {json.dumps(call.args)} )")

                        # 3. Tool / Function Responses
                        elif part.function_response:
                            resp = part.function_response
                            print(f"\n[Tool Response from {resp.name}]:")
                            print(json.dumps(resp.response, indent=2))

            except Exception as e:
                print(f"\nError processing query: {e}")
                import traceback
                traceback.print_exc()

            print("\n" + "="*50 + "\n")

    finally:
        await runner.close()
        print("Goodbye!")


if __name__ == "__main__":
    # Ensure event loop policy supports subprocess/pipes (essential for stdio MCP)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(async_main())
