# Jeden Dockerfile pro vývoj (target dev) i provoz (target prod, ZM-010).
ARG TAILWIND_VERSION=v4.3.3

# CSS se generuje na platformě buildu – u image pro arm64 se Tailwind neemuluje.
FROM --platform=$BUILDPLATFORM debian:bookworm-slim AS css
ARG TAILWIND_VERSION
ARG BUILDARCH
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && case "$BUILDARCH" in amd64) arch=x64 ;; arm64) arch=arm64 ;; \
         *) echo "Nepodporovaná platforma buildu: $BUILDARCH" >&2; exit 1 ;; esac \
    && curl -sfL -o /usr/local/bin/tailwindcss \
       "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-${arch}" \
    && chmod +x /usr/local/bin/tailwindcss
WORKDIR /src
COPY . .
RUN tailwindcss -i assets/css/input.css -o static/css/app.css --minify

FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
# Uživatel se stejným UID/GID jako vývojář v LXC, aby soubory vzniklé
# přes bind mount (migrace, přílohy v media/) nepatřily rootovi.
ARG UID=1000
ARG GID=1000
RUN groupadd --gid ${GID} app && useradd --uid ${UID} --gid ${GID} --create-home app \
    && mkdir -p /opt/venv /app && chown app:app /opt/venv /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# Vývoj: Tailwind pro --watch, dev závislosti, kód přes bind mount.
FROM base AS dev
ARG TAILWIND_VERSION
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && case "$TARGETARCH" in amd64) arch=x64 ;; arm64) arch=arm64 ;; \
         *) echo "Nepodporovaná platforma: $TARGETARCH" >&2; exit 1 ;; esac \
    && curl -sfL -o /usr/local/bin/tailwindcss \
       "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-${arch}" \
    && chmod +x /usr/local/bin/tailwindcss
USER app
COPY --chown=app:app pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project
COPY --chown=app:app . .
COPY --from=css --chown=app:app /src/static/css/app.css static/css/app.css
RUN uv sync --frozen
EXPOSE 8000
CMD ["uv", "run", "python", "manage.py", "runserver", "0.0.0.0:8000"]

# Sestavení provozu: jen provozní závislosti, statické soubory sebrané při buildu, Python
# zkompilovaný na .pyc a zdrojové .py smazané. Do výsledného image se kopíruje jen výsledek,
# takže .py nezůstanou ani v nižších vrstvách.
# Prázdná media/ patří uživateli app – volume pro přílohy převezme vlastníka při prvním připojení.
FROM base AS build
USER app
COPY --chown=app:app pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache
COPY --chown=app:app . .
COPY --from=css --chown=app:app /src/static/css/app.css static/css/app.css
ENV PATH=/opt/venv/bin:$PATH
RUN rm -rf apps/*/tests conftest.py docs assets scripts .github \
        CLAUDE.md README.md Dockerfile compose*.yml .env.example pyproject.toml uv.lock \
    && export DJANGO_SECRET_KEY=build DATABASE_URL=postgres://build:build@localhost/build \
    && python manage.py collectstatic --noinput -v0 \
    && python -m compileall -q -b -f apps config manage.py docker/selftest.py \
    && find apps config -name '*.py' -delete \
    && rm manage.py docker/selftest.py \
    && find . -name __pycache__ -prune -exec rm -rf {} + \
    && python docker/selftest.pyc \
    && rm docker/selftest.pyc \
    && mkdir media

FROM python:3.12-slim AS prod
ARG UID=1000
ARG GID=1000
RUN groupadd --gid ${GID} app && useradd --uid ${UID} --gid ${GID} --create-home app
COPY --from=build /opt/venv /opt/venv
COPY --from=build --chown=app:app /app /app
ARG APP_VERSION=místní
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_VERSION=${APP_VERSION}
WORKDIR /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["web"]
