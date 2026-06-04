FROM python:3.12-slim

# Prevents Python from buffering stdout and stderr
ENV PYTHONUNBUFFERED=1

# Configure Poetry
ENV POETRY_VERSION=1.2.0
ENV POETRY_HOME=/opt/poetry
ENV POETRY_VENV=/opt/poetry-venv
ENV POETRY_CACHE_DIR=/opt/.cache

# Install poetry separated from system interpreter
RUN python3 -m venv $POETRY_VENV \
    && $POETRY_VENV/bin/pip install -U pip setuptools \
    && $POETRY_VENV/bin/pip install poetry==${POETRY_VERSION}

# Add `poetry` to PATH
ENV PATH="${PATH}:${POETRY_VENV}/bin"

WORKDIR /app

# Install dependencies
COPY poetry.lock pyproject.toml ./
RUN poetry install

# Copy the project files
COPY . .

# Upgrade pip and install the package and its dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Expose the default Cloud Run port
EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
