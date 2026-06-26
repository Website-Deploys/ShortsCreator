# Multi-stage image for the Olympus backend (API and workers share one image;
# the entry command selects the role). Kept minimal for the foundation; FFmpeg
# and GPU runtimes are layered into the worker image in the rendering milestone.

# --- Builder: install dependencies into a virtualenv -----------------------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install build deps and the project (editable not needed in the image).
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install .

# --- Runtime: slim image with only the venv and source ---------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Run as a non-root user (least privilege).
RUN useradd --create-home --uid 1000 olympus
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/src /app/src

USER olympus
EXPOSE 8000

# Default command runs the API; override to run a worker:
#   celery -A olympus.apps.workers.worker:celery_app worker ...
CMD ["uvicorn", "olympus.apps.backend_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
