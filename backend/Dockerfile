FROM python:3.12-slim AS builder

ARG KICHU_PIP_INDEX_URL=https://pypi.org/simple
RUN python -m pip install --no-cache-dir --index-url "${KICHU_PIP_INDEX_URL}" uv==0.11.32

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_PROGRESS=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --format requirements.txt > requirements.lock.txt && \
    python -m venv .venv && \
    .venv/bin/pip install --no-cache-dir --require-hashes \
      --index-url "${KICHU_PIP_INDEX_URL}" -r requirements.lock.txt

COPY . .

FROM python:3.12-slim

WORKDIR /app

ARG KICHU_DEBIAN_MIRROR_HOST=http://deb.debian.org
ARG KICHU_PGDG_APT_URL=https://apt.postgresql.org/pub/repos/apt
RUN sed -i "s#http://deb.debian.org#${KICHU_DEBIAN_MIRROR_HOST}#g" /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y --no-install-recommends tzdata ca-certificates curl && \
    . /etc/os-release && \
    install -d /usr/share/postgresql-common/pgdg && \
    curl --fail --silent --show-error https://www.postgresql.org/media/keys/ACCC4CF8.asc \
      -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc && \
    printf 'Types: deb\nURIs: %s\nSuites: %s-pgdg\nComponents: main\nSigned-By: /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc\n' "$KICHU_PGDG_APT_URL" "$VERSION_CODENAME" \
      > /etc/apt/sources.list.d/pgdg.sources && \
    apt-get update && apt-get install -y --no-install-recommends postgresql-client-16 && \
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
COPY --from=builder /app/services /app/services
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
