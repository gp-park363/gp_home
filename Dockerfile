# syntax=docker/dockerfile:1

ARG PYTHON_IMAGE=python:3.15-slim
ARG TAILWIND_VERSION=v4.3.5

# ── Tailwind standalone CLI (Node 불필요) ─────────────────────────
FROM ${PYTHON_IMAGE} AS tailwind
ARG TAILWIND_VERSION
ARG TARGETARCH
RUN set -eu; \
    case "${TARGETARCH:-amd64}" in amd64) arch=x64 ;; arm64) arch=arm64 ;; *) echo "unsupported: $TARGETARCH"; exit 1 ;; esac; \
    python -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' \
      "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-${arch}" \
      /usr/local/bin/tailwindcss; \
    chmod 755 /usr/local/bin/tailwindcss
WORKDIR /srv

FROM tailwind AS css-build
COPY app/templates app/templates
COPY app/static/css/input.css app/static/css/input.css
RUN tailwindcss -i app/static/css/input.css -o app/static/css/app.css --minify

# ── Python 공통 ──────────────────────────────────────────────────
FROM ${PYTHON_IMAGE} AS base
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH
WORKDIR /srv

# ── 로컬 개발: 코드는 볼륨으로 마운트, --reload ───────────────────
FROM base AS dev
ENV PYTHONDONTWRITEBYTECODE=1
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "app"]

# ── 운영 ─────────────────────────────────────────────────────────
FROM base AS prod
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-dev
COPY alembic.ini ./
COPY migrations migrations
COPY scripts scripts
COPY app app
COPY --from=css-build /srv/app/static/css/app.css app/static/css/app.css
RUN useradd --system --uid 1000 --home /srv app \
    && mkdir -p /data/media/public /data/media/private \
    && chown -R app /data/media
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "3", "--proxy-headers", "--forwarded-allow-ips", "*"]

# ── 운영 Nginx: 정적 파일을 이미지에 포함 ─────────────────────────
FROM nginx:1.30-alpine AS nginx
COPY --from=prod /srv/app/static /srv/static
