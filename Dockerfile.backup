FROM python:3.11-slim

WORKDIR /app

# Install git for SDK installation from GitHub
RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*

# Copy all project files first
COPY pyproject.toml README.md start.py ./
COPY src/ src/

# Install dependencies
RUN pip install --no-cache-dir .

# Create data directory for SQLite (will be mounted as volume in Railway)
RUN mkdir -p /app/data

# Default database path (override with Railway volume)
ENV DATABASE_PATH=/app/data/subscribers.db

# Expose port
EXPOSE 8000

# Health check - removed, Railway handles this
# HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
#     CMD curl -f http://localhost:8000/health || exit 1

# Run the server
CMD ["python", "start.py"]
