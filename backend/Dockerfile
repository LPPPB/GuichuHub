# === builder 阶段：装依赖 + 编译字节码 ===
FROM python:3.12-slim AS builder

# pin uv 版本（不用 latest，保证可复现构建）
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

# uv 行为优化（ENV 不支持行内注释，注释单独一行）
# UV_COMPILE_BYTECODE=1: 构建期编译 .pyc，加速冷启动
# UV_LINK_MODE=copy: Docker cache mount 友好
# UV_NO_PROGRESS=1: 抑制构建日志进度条
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_NO_PROGRESS=1

WORKDIR /app

# 两阶段 sync 第一步：只装依赖不装项目（依赖未变时复用此缓存层）
COPY pyproject.toml uv.lock ./
RUN uv sync --extra dev --frozen --no-install-project

# 两阶段 sync 第二步：复制源码后装项目（editable 模式，适合平铺结构）
COPY . .
RUN uv sync --extra dev --frozen

# === 运行阶段：最小镜像，不含 uv 和构建工具 ===
FROM python:3.12-slim

WORKDIR /app

# 安装 tzdata 并设置时区（APScheduler cron 任务按 Asia/Shanghai 触发）
# python:3.12-slim 默认不含 tzdata，仅 ENV TZ 不生效；必须装包 + 建 /etc/localtime 软链
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && \
    ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo "Asia/Shanghai" > /etc/timezone && \
    rm -rf /var/lib/apt/lists/*

# 复制虚拟环境 + 源码（editable 模式需要源码在路径中）
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/app.py /app/
COPY --from=builder /app/config.py /app/
COPY --from=builder /app/logger.py /app/
COPY --from=builder /app/collectors /app/collectors
COPY --from=builder /app/storage /app/storage
COPY --from=builder /app/analytics /app/analytics
COPY --from=builder /app/jobs /app/jobs
COPY --from=builder /app/utils /app/utils

ENV PATH="/app/.venv/bin:$PATH"
ENV TZ=Asia/Shanghai
ENV PYTHONUNBUFFERED=1

EXPOSE 5000
CMD ["python", "app.py"]
