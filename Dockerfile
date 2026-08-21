# Multi-stage lightweight production image for Mangasurf Server & OPDS
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    MANGASURF_DOCKER=1 \
    HOME=/data

WORKDIR /app

# Install minimal runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY requirements.txt pyproject.toml setup.py /app/
COPY mangasurf /app/readerm
COPY ui /app/ui
COPY docs /app/docs
COPY server.py opdsserve.py launcher.py mangasurf.py README.md /app/

# Install dependencies and package
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -e .

# Create volume mount directory for library and user data
RUN mkdir -p /data/.mangasurf /data/library

EXPOSE 8577 8578

VOLUME ["/data"]

# Default entry point runs the LAN Web Server on :8577
CMD ["python3", "server.py", "--host", "0.0.0.0", "--port", "8577"]
