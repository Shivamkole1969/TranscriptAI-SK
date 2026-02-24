FROM python:3.11-slim

# Install FFmpeg and clean up
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user (HF Spaces requirement)
RUN useradd -m -u 1000 appuser

WORKDIR /app

# Copy requirements first for Docker cache
COPY requirements-cloud.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy app files
COPY main.py .
COPY custom_bundle.pem .
COPY static/ ./static/
COPY templates/ ./templates/

# Create data directories with correct permissions
RUN mkdir -p /app/data /app/output && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Environment
ENV PYTHONUNBUFFERED=1
ENV PORT=7860
ENV RENDER=true

# Expose HF Spaces default port
EXPOSE 7860

# Run
CMD ["python", "main.py"]
