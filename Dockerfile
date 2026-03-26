FROM python:3.12-slim

# Install ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY . .

# Initialize DB on first run
RUN python main.py init-db

EXPOSE 8501

# Default: run full automation engine
CMD ["python", "main.py", "run"]
