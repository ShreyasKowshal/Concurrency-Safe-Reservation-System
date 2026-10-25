FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /workspace/backend
COPY backend/pyproject.toml backend/requirements-dev.lock backend/alembic.ini ./
COPY backend/src ./src
COPY backend/migrations ./migrations
COPY backend/tests ./tests
COPY docs /workspace/docs
# This image is a development/test foundation, not the final production image.
RUN pip install --no-cache-dir -c requirements-dev.lock ".[dev]" \
    && useradd --create-home --uid 10001 app

ENV PYTHONPATH=/workspace/backend/src
USER app
EXPOSE 8000
CMD ["uvicorn", "csrs.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
