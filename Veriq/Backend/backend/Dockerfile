FROM docker:27-cli AS dockercli

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The reliability runner drives the Docker CLI to create the isolated per-run
# network, broker, database and worker. It needs the Docker socket at runtime.
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker

COPY . .

# Wait for PostgreSQL to accept connections before starting uvicorn.
# Migrations are NOT run here — run them explicitly:
#   docker compose exec backend alembic upgrade head
CMD ["sh", "-c", "python scripts/wait_for_database.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
