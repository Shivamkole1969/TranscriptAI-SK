FROM python:3.11-slim

# Install FFmpeg and clean up
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for Docker cache
COPY requirements-cloud.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy app files
COPY main.py .
COPY custom_bundle.pem .
COPY static/ ./static/
COPY templates/ ./templates/

# Create data directories
RUN mkdir -p /app/data /app/output

# Environment
ENV PYTHONUNBUFFERED=1
ENV PORT=10000
ENV RENDER=true

# Expose Render's default port
EXPOSE 10000

# Run with dynamic port binding
CMD ["python", "main.py"]
