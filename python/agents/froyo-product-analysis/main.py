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

"""FastAPI application for Froyo Product Analysis Agent.

Used for local web UI serving and GCP Cloud Run deployment.
"""

import os
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from google.adk.cli.fast_api import get_fast_api_app

# Load environment variables from .env file
load_dotenv()

AGENT_DIR = os.path.dirname(os.path.abspath(__file__))

# Get session service URI from environment variables (e.g. Firestore / DB)
session_uri = os.getenv("SESSION_SERVICE_URI", None)

# Enable Web interface serving flag from environment variables
web_interface_enabled = os.getenv("SERVE_WEB_INTERFACE", "True").lower() in (
    "true",
    "1",
)

# Normalize ADK_DEFAULT_APP_NAME if it's set with hyphens, or set it to default
default_app = os.getenv("ADK_DEFAULT_APP_NAME")
if default_app:
    os.environ["ADK_DEFAULT_APP_NAME"] = default_app.replace("-", "_")
else:
    os.environ["ADK_DEFAULT_APP_NAME"] = "froyo_product_analysis"

# Enable tracing / OpenTelemetry options from environment variables
trace_to_cloud = os.getenv("TRACE_TO_CLOUD", "True").lower() in ("true", "1")
otel_to_cloud = os.getenv("OTEL_TO_CLOUD", "False").lower() in ("true", "1")

# Prepare arguments for get_fast_api_app
app_args = {
    "agents_dir": AGENT_DIR,
    "web": web_interface_enabled,
    "trace_to_cloud": trace_to_cloud,
    "otel_to_cloud": otel_to_cloud,
}

# Only include session_service_uri if it's provided, otherwise default to in-memory session service
if session_uri:
    app_args["session_service_uri"] = session_uri

# Create FastAPI app with appropriate arguments
app: FastAPI = get_fast_api_app(**app_args)

app.title = "froyo_product_analysis"
app.description = "Froyo Frozen Yogurt Product Analysis Agent API"

if __name__ == "__main__":
    # Use the PORT environment variable provided by Cloud Run, defaulting to 8080
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
