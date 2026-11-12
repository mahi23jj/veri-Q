# Build from the repository root so the local VeriQ SDK can be installed:
#   docker build -f examples/celery-target-app/Dockerfile -t veriq-target-app .
# docker compose in this directory does that for you.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# The SDK ships with the repository in this milestone; a published package can
# replace this COPY later without touching the application code.
COPY sdk/ /opt/veriq-sdk/
COPY examples/celery-target-app/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir /opt/veriq-sdk

COPY examples/celery-target-app/app ./app

# Overridden per service in compose.yaml (the queue is the only difference).
CMD ["celery", "-A", "app.celery_app", "worker", "-Q", "normal", "--loglevel=INFO"]
