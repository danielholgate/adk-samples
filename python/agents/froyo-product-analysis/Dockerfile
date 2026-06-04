FROM python:3.12-slim

# Prevents Python from buffering stdout and stderr
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install all project dependencies into the system Python.
# We copy pyproject.toml + app/ first (app/ is needed because the project
# is defined as a package in pyproject.toml and must be installable).
# uv pip install --system targets /usr/local/lib/python3.11/ directly,
# making packages available to KFP's executor without activating a venv.
COPY pyproject.toml README.md uv.lock* ./
RUN uv pip install --system --no-cache .

# Copy the project files
COPY . .

# Upgrade pip and install the package and its dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Expose the default Cloud Run port
EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
