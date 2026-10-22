FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY pyproject.toml README.md ./
COPY engine engine
COPY app app
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY migrations migrations

EXPOSE 8000
# Migra o banco, garante o catálogo e sobe a API.
CMD ["sh", "-c", "alembic upgrade head && python -m app.cli seed-catalog && uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000"]
