# Python worker / search service / migrations. Build from the repository root:
#   docker build -f workers/analyzer/Dockerfile -t codeatlas-worker .
# One image, three commands: `python -m analyzer.main` (worker), `python -m analyzer.service` (search+chat), `python -m analyzer.migrate`.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
WORKDIR /app/workers/analyzer
COPY workers/analyzer/pyproject.toml workers/analyzer/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY workers/analyzer/analyzer ./analyzer
COPY db /app/db

FROM python:3.12-slim
# git is needed to clone; nothing else from the OS
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 atlas && mkdir -p /home/atlas/.cache && chown atlas /home/atlas/.cache
COPY --from=build --chown=atlas /app /app
ENV PATH="/app/workers/analyzer/.venv/bin:$PATH" PYTHONUNBUFFERED=1 HF_HOME=/home/atlas/.cache/huggingface \
    EMBED_CACHE_DIR=/home/atlas/.cache/fastembed SEARCH_HOST=0.0.0.0
WORKDIR /app/workers/analyzer
USER atlas
CMD ["python", "-m", "analyzer.main"]
