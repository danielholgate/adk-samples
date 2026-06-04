FROM python:3.12-slim

# Prevents Python from buffering stdout and stderr
ENV PYTHONUNBUFFERED=1

# Install uv for fast dependency resolution (pinned version for reproducibility)
RUN pip install --no-cache-dir uv==0.8.13

WORKDIR /app

# Install all project dependencies into the system Python.
# We copy pyproject.toml, README.md, and the package directory first to cache this layer.
COPY pyproject.toml README.md uv.lock* ./
COPY froyo_product_analysis/ ./froyo_product_analysis/
RUN uv pip install --system --no-cache-dir .

# Copy the rest of the project files
COPY . .

# Expose the default Cloud Run port
EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
