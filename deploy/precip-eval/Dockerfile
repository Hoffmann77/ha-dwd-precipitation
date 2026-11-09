# The interpolation evaluation service (docs/interpolation-evaluation.md).
# Built from the repository root by compose.yaml.
FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv

WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# The dependencies first, so a code change does not reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --only-group precip-eval --no-install-project

# Only what the service runs: the integration's HA-free radar package, which
# it imports as `radar` (as the parser tests do), and the service itself.
COPY custom_components/dwd_precipitation/radar custom_components/dwd_precipitation/radar
COPY scripts/precip_eval scripts/precip_eval
COPY deploy/precip-eval/entrypoint.sh /entrypoint.sh

ARG PRECIP_EVAL_COMMIT=unknown
ENV PRECIP_EVAL_COMMIT=${PRECIP_EVAL_COMMIT} \
    PRECIP_EVAL_DATA_DIR=/data \
    PYTHONPATH=/app:/app/custom_components/dwd_precipitation \
    PATH=/opt/venv/bin:${PATH} \
    PYTHONUNBUFFERED=1 \
    TZ=UTC

# Unhealthy when the scheduler has not touched its heartbeat for 15 minutes.
HEALTHCHECK --interval=5m --timeout=10s --start-period=10m \
    CMD python -c "import os, sys, time; sys.exit(time.time() - os.path.getmtime('/data/heartbeat') > 900)"

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "scripts.precip_eval"]
