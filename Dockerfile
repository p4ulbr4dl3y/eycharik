# One image, three commands: api, worker and one-off operator tasks.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# MAX and GigaChat chains anchor at the Russian Trusted Root CA, which is absent from the default
# Python store. Install it into the system bundle and make httpx use that merged bundle.
COPY infra/certs/russian_trusted_ca.crt /usr/local/share/ca-certificates/russian_trusted_ca.crt
RUN update-ca-certificates
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    MAX_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /uvx /usr/local/bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONPATH=/app/apps/api \
    PATH=/app/.venv/bin:$PATH

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY apps ./apps
COPY knowledge ./knowledge
COPY infra/demo ./infra/demo
COPY docs/prompts ./docs/prompts
COPY docs/product ./docs/product
COPY docs/contracts ./docs/contracts

RUN uv sync --frozen --no-dev

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "onboarding.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
