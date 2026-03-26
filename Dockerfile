FROM python:3.12-slim

WORKDIR /app

# Install FUSE (for Linux FUSE support)
RUN apt-get update && apt-get install -y \
    fuse3 \
    libfuse3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install AVM
COPY . .
RUN pip install -e ".[server]"

# Default: run HTTP API server (no FUSE in Docker)
EXPOSE 8765
ENV AVM_AGENT=default

CMD ["avm-serve", "--host", "0.0.0.0", "--port", "8765"]
