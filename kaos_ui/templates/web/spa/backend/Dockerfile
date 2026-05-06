# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.14

# ── Builder ──────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# uv from the official image — pinned for reproducible builds.
COPY --from=ghcr.io/astral-sh/uv:0.5.0 /uv /uvx /bin/

# libmagic for python-magic (upload content-type verification)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Install deps from lockfile only — exclude dev group.
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy app and install the project itself.
COPY . .
RUN uv sync --frozen --no-dev


# ── Runtime ──────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Non-root user
RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --create-home --home-dir /home/app app

WORKDIR /app

# libmagic for content-type verification of uploads. Without it the
# upload service falls back to extension-only checks and logs a
# warning — we install it in production for the stronger gate.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder --chown=app:app /app /app

USER app

EXPOSE 8000

# urllib-based healthcheck so the image doesn't need curl.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/v1/health',timeout=4).status==200 else 1)" \
    || exit 1

CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
