# Small Debian image with Python 3.13 (matches .python-version).
FROM python:3.13-slim

# Copy the uv binary from its official image instead of installing it with pip.
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv

# Put the virtualenv outside /app, so the code folder mounted by docker-compose
# (which contains your Mac's .venv) can't hide or clash with it.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Install dependencies first, in their own layer: Docker reuses this cached layer
# on rebuilds unless pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-install-project

COPY . .

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
