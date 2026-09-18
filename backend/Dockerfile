FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_PROGRESS=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends tzdata postgresql-client && \
    ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo "Asia/Shanghai" > /etc/timezone && \
    groupadd --gid 10001 app && \
    useradd --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app && \
    mkdir -p /app/data && \
    chown app:app /app/data && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/app.py /app/
COPY --from=builder /app/api_entrypoint.py /app/
COPY --from=builder /app/worker_entrypoint.py /app/
COPY --from=builder /app/config.py /app/
COPY --from=builder /app/logger.py /app/
COPY --from=builder /app/runtime_paths.py /app/
COPY --from=builder /app/collectors /app/collectors
COPY --from=builder /app/storage /app/storage
COPY --from=builder /app/analytics /app/analytics
COPY --from=builder /app/jobs /app/jobs
COPY --from=builder /app/utils /app/utils
COPY --from=builder /app/scripts /app/scripts
COPY --from=builder /app/alembic.ini /app/alembic.ini
COPY --from=builder /app/alembic /app/alembic

ENV PATH="/app/.venv/bin:$PATH"
ENV TZ=Asia/Shanghai
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

USER app
EXPOSE 5000
CMD ["gunicorn", "--bind=0.0.0.0:5000", "--workers=2", "--threads=4", "--access-logfile=-", "--error-logfile=-", "api_entrypoint:app"]
