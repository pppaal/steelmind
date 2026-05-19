FROM python:3.12-slim

# Run as a non-root user. If the journal volume is mounted with mixed
# ownership, the entrypoint sets the data dir mode at startup.
RUN groupadd --system --gid 1000 steelmind \
    && useradd --system --uid 1000 --gid 1000 --create-home steelmind

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend

RUN mkdir -p /data && chown -R steelmind:steelmind /data /app

ENV PYTHONUNBUFFERED=1 \
    LOG_FORMAT=json

USER steelmind
EXPOSE 8000

# Use exec form so Python receives SIGTERM directly and uvicorn can run
# its graceful shutdown sequence.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
